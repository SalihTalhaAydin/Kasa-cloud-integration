"""Local network device discovery and MAC-based matching."""
from __future__ import annotations

import logging
from datetime import timedelta

from kasa import Credentials, Discover

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import LOCAL_DISCOVERY_INTERVAL, normalize_mac
from .device_wrapper import KasaDeviceWrapper

_LOGGER = logging.getLogger(__name__)


class LocalDeviceDiscovery:
    """Discovers python-kasa devices on the LAN and matches them to cloud wrappers."""

    def __init__(
        self,
        hass: HomeAssistant,
        wrappers: dict[str, KasaDeviceWrapper],
        credentials: Credentials | None = None,
    ) -> None:
        """Initialize."""
        self._hass = hass
        self._wrappers = wrappers
        self._credentials = credentials
        self._cancel_timer = None
        # MAC -> device_id lookup for matching
        self._mac_to_device_id: dict[str, str] = {}
        for device_id, wrapper in wrappers.items():
            try:
                mac = wrapper.cloud_mac
                self._mac_to_device_id[mac] = device_id
            except Exception:
                _LOGGER.debug("No MAC for cloud device %s", device_id)

    async def async_start(self) -> None:
        """Run initial discovery and start periodic timer."""
        await self._async_discover()
        self._cancel_timer = async_track_time_interval(
            self._hass,
            self._async_discover_callback,
            timedelta(seconds=LOCAL_DISCOVERY_INTERVAL),
        )

    @callback
    def async_stop(self) -> None:
        """Stop periodic discovery."""
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

    async def _async_discover_callback(self, _now=None) -> None:
        """Timer callback wrapper."""
        await self._async_discover()

    async def _async_discover(self) -> None:
        """Run python-kasa discovery and match to cloud devices by MAC."""
        _LOGGER.debug("Starting local device discovery")
        try:
            discovered = await Discover.discover(
                credentials=self._credentials,
                discovery_timeout=10,
            )
        except Exception as err:
            _LOGGER.warning("Local discovery failed: %s", err)
            return

        found_macs: set[str] = set()
        for ip, device in discovered.items():
            try:
                mac = normalize_mac(device.mac)
                found_macs.add(mac)
                device_id = self._mac_to_device_id.get(mac)
                if device_id and device_id in self._wrappers:
                    wrapper = self._wrappers[device_id]
                    if wrapper.local_device is None:
                        wrapper.attach_local(device)
                    elif wrapper.local_device.host != ip:
                        # IP changed
                        wrapper.detach_local()
                        wrapper.attach_local(device)
            except Exception:
                _LOGGER.debug("Could not process discovered device at %s", ip)

        # Detach wrappers whose local devices were not found
        for wrapper in self._wrappers.values():
            if wrapper.local_device is not None:
                if wrapper.cloud_mac not in found_macs:
                    wrapper.detach_local()

        matched = sum(1 for w in self._wrappers.values() if w.local_device is not None)
        _LOGGER.info(
            "Local discovery: %d found, %d matched of %d cloud devices",
            len(discovered),
            matched,
            len(self._wrappers),
        )
