"""Device wrapper providing local-first command routing with cloud fallback."""
from __future__ import annotations

import asyncio
from base64 import b64decode
import logging
import time
from typing import Any

from .const import (
    CONN_MODE_CLOUD,
    CONN_MODE_LOCAL,
    CONN_MODE_UNAVAILABLE,
    LOCAL_COMMAND_TIMEOUT,
    PROTOCOL_IOT,
    PROTOCOL_SMART,
    normalize_mac,
)

_LOGGER = logging.getLogger(__name__)

# Minimum seconds between local retry after a failure
LOCAL_RETRY_BACKOFF = 10


class KasaDeviceWrapper:
    """Wraps cloud + local device, routes commands local-first."""

    def __init__(
        self,
        cloud_device,
        parent_wrapper: KasaDeviceWrapper | None = None,
        protocol_family: str = PROTOCOL_IOT,
    ) -> None:
        """Initialize with the cloud device. Local set later via attach_local()."""
        self._cloud = cloud_device
        self._parent: KasaDeviceWrapper | None = parent_wrapper
        self._protocol_family = protocol_family
        self._local = None
        self._local_available: bool = False
        self._last_local_failure: float = 0.0
        if protocol_family == PROTOCOL_SMART:
            self._connection_mode: str = CONN_MODE_UNAVAILABLE
        else:
            self._connection_mode: str = CONN_MODE_CLOUD
        self._is_parent: bool = False
        self._last_sys_info_alias: str | None = None

    # --- Proxy cloud device attributes ---

    @property
    def device_id(self) -> str:
        """Return unique identifier. For children, appends child_id to avoid collisions."""
        base_id = self._cloud.device_id
        child_id = self.child_id
        if child_id is not None:
            return f"{base_id}_{child_id}"
        return base_id

    @property
    def parent_device_id(self) -> str | None:
        """Return the parent's device_id if this is a child, else None."""
        if self.child_id is not None:
            return self._cloud.device_id
        return None

    @property
    def parent_wrapper(self) -> KasaDeviceWrapper | None:
        """Return the parent wrapper if this is a child device."""
        return self._parent

    @property
    def device_model(self) -> str:
        """Return device model string, safely handling children."""
        model = getattr(self._cloud.device_info, "device_model", None)
        if model:
            return model
        if self._parent:
            return self._parent.device_model
        return "Unknown"

    @property
    def device_info(self):
        """Return the cloud device info."""
        return self._cloud.device_info

    @property
    def child_id(self):
        """Return the child ID if this is a child device."""
        return getattr(self._cloud, "child_id", None)

    @property
    def protocol_family(self) -> str:
        """Return the protocol family (IOT or SMART)."""
        return self._protocol_family

    @property
    def is_tapo(self) -> bool:
        """Return True if this is a Tapo (SMART) device."""
        return self._protocol_family == PROTOCOL_SMART

    def get_alias(self) -> str:
        """Return the device alias, preferring the fresh name from sys_info."""
        return self._fresh_alias or self._decode_alias(
            self._cloud.get_alias(),
        )

    @staticmethod
    def _decode_alias(alias: str) -> str:
        """Decode base64-encoded aliases (Tapo cloud API)."""
        if not alias:
            return alias
        try:
            decoded = b64decode(alias).decode("utf-8")
            # Only use decoded if it looks like readable text
            if decoded.isprintable():
                return decoded
        except Exception:
            pass
        return alias

    @property
    def _fresh_alias(self) -> str | None:
        """Return alias from the most recent sys_info poll, if available."""
        return self._last_sys_info_alias

    def update_alias_from_sys_info(self, sys_info: dict) -> None:
        """Update cached alias from a sys_info poll result."""
        alias = sys_info.get("alias")
        if alias:
            self._last_sys_info_alias = alias

    def has_children(self) -> bool:
        """Return True if device has child devices."""
        return self._cloud.has_children() or self._is_parent

    async def get_children_async(self):
        """Return child devices."""
        return await self._cloud.get_children_async()

    async def get_sys_info(self):
        """Poll via cloud for IOT devices, local for Tapo."""
        if self.is_tapo:
            return await self._get_tapo_state()
        return await self._cloud.get_sys_info()

    async def _get_tapo_state(self) -> dict:
        """Get device state from local python-kasa for Tapo devices."""
        if self._local is None:
            raise Exception(
                f"Tapo device {self.get_alias()} has no local connection"
            )
        await self._local.update()
        state: dict[str, Any] = {
            "relay_state": 1 if self._local.is_on else 0,
            "alias": self._local.alias or self.get_alias(),
            "rssi": getattr(self._local, "rssi", None),
            "on_time": getattr(self._local, "on_since", None),
        }
        # Energy data for P110/P115
        if hasattr(self._local, "has_emeter") and self._local.has_emeter:
            try:
                emeter = self._local.emeter_realtime
                state["emeter"] = {
                    "power_w": getattr(emeter, "power", None),
                    "voltage_v": getattr(emeter, "voltage", None),
                    "current_a": getattr(emeter, "current", None),
                    "total_kwh": getattr(emeter, "total", None),
                }
            except Exception:
                _LOGGER.debug("Emeter read failed for %s", self.get_alias())
        return state

    @property
    def cloud_mac(self) -> str | None:
        """Return normalized MAC from cloud device_info, or None for children."""
        mac = getattr(self._cloud.device_info, "device_mac", None)
        if mac:
            return normalize_mac(mac)
        return None

    @property
    def connection_mode(self) -> str:
        """Return current connection mode."""
        return self._connection_mode

    @property
    def local_device(self):
        """Return the local python-kasa device, if attached."""
        return self._local

    # --- Local device management ---

    def attach_local(self, local_device) -> None:
        """Attach a discovered python-kasa device."""
        self._local = local_device
        self._local_available = True
        self._connection_mode = CONN_MODE_LOCAL
        _LOGGER.info(
            "Local control attached for %s (%s)",
            self.get_alias(),
            local_device.host,
        )

    def detach_local(self) -> None:
        """Remove local device (e.g., went offline)."""
        self._local = None
        self._local_available = False
        if self.is_tapo:
            self._connection_mode = CONN_MODE_UNAVAILABLE
        else:
            self._connection_mode = CONN_MODE_CLOUD

    def _should_try_local(self) -> bool:
        """Check if local path should be attempted."""
        if self._local is None:
            return False
        if self._local_available:
            return True
        # Retry after backoff period
        if time.monotonic() - self._last_local_failure > LOCAL_RETRY_BACKOFF:
            return True
        return False

    def _mark_local_failure(self) -> None:
        """Record a local command failure."""
        self._local_available = False
        self._last_local_failure = time.monotonic()
        if self.is_tapo:
            self._connection_mode = CONN_MODE_UNAVAILABLE
        else:
            self._connection_mode = CONN_MODE_CLOUD
        _LOGGER.debug(
            "Local command failed for %s, %s",
            self.get_alias(),
            "no fallback (Tapo)" if self.is_tapo
            else "falling back to cloud",
        )

    def _mark_local_success(self) -> None:
        """Record a local command success."""
        self._local_available = True
        self._connection_mode = CONN_MODE_LOCAL

    # --- Pre-command cloud poll ---

    async def _pre_poll(self) -> None:
        """Poll this device via cloud before sending a command.

        Ensures we have fresh state and confirms the device
        is reachable. 10s timeout so commands aren't blocked.
        """
        try:
            await asyncio.wait_for(
                self._cloud.get_sys_info(), timeout=10,
            )
        except Exception as err:
            _LOGGER.debug(
                "Pre-command poll failed for %s: %s",
                self.get_alias(), err,
            )

    # --- Command routing: power on/off ---

    async def power_on(self) -> None:
        """Turn device on, local-first."""
        if not self.is_tapo:
            await self._pre_poll()
        if self.is_tapo or self._should_try_local():
            try:
                await asyncio.wait_for(
                    self._local.turn_on(),
                    timeout=LOCAL_COMMAND_TIMEOUT,
                )
                self._mark_local_success()
                return
            except Exception:
                if self.is_tapo:
                    self._mark_local_failure()
                    raise
                self._mark_local_failure()
        await self._cloud.power_on()

    async def power_off(self) -> None:
        """Turn device off, local-first."""
        if not self.is_tapo:
            await self._pre_poll()
        if self.is_tapo or self._should_try_local():
            try:
                await asyncio.wait_for(
                    self._local.turn_off(),
                    timeout=LOCAL_COMMAND_TIMEOUT,
                )
                self._mark_local_success()
                return
            except Exception:
                if self.is_tapo:
                    self._mark_local_failure()
                    raise
                self._mark_local_failure()
        await self._cloud.power_off()

    # --- Command routing: LED state ---

    async def set_led_state(self, on: bool) -> None:
        """Set LED indicator state, local-first."""
        if self.is_tapo:
            return  # Tapo LED control not supported
        await self._pre_poll()
        if self._should_try_local():
            try:
                await asyncio.wait_for(
                    self._local.set_led(on),
                    timeout=LOCAL_COMMAND_TIMEOUT,
                )
                self._mark_local_success()
                return
            except Exception:
                self._mark_local_failure()
        await self._cloud.set_led_state(on)

    # --- Command routing: passthrough requests ---

    async def _pass_through_request(
        self, module: str, method: str,
        params: dict[str, Any] | None,
    ) -> Any:
        """Route passthrough commands (IOT only).

        For local, uses IotDevice._query_helper() which sends the
        same JSON format over the local protocol (XOR/KLAP).
        Tapo devices do not support cloud passthrough.
        """
        if self.is_tapo:
            raise NotImplementedError(
                "Cloud passthrough not supported for Tapo"
            )
        if params is None:
            params = {}

        await self._pre_poll()
        if self._should_try_local():
            try:
                result = await asyncio.wait_for(
                    self._local._query_helper(
                        module, method,
                        params if params else None,
                    ),
                    timeout=LOCAL_COMMAND_TIMEOUT,
                )
                self._mark_local_success()
                return result
            except Exception:
                self._mark_local_failure()

        return await self._cloud._pass_through_request(
            module, method, params,
        )
