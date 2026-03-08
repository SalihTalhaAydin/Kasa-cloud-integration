"""The Kasa Cloud integration."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

from tplinkcloud import TPLinkDeviceManager

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import (
    CONF_LOCAL_CONTROL,
    CONF_SCAN_INTERVAL,
    DEFAULT_LOCAL_CONTROL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import KasaCloudCoordinator
from .device_wrapper import KasaDeviceWrapper

_LOGGER = logging.getLogger(__name__)


def _is_supported_device(d) -> bool:
    """Check if a device should be included in the integration."""
    if getattr(d, "child_id", None) is not None:
        return True
    if hasattr(d, "device_info") and hasattr(d.device_info, "device_type"):
        return d.device_info.device_type == "IOT.SMARTPLUGSWITCH"
    return False


async def async_get_devices(
    hass: HomeAssistant, device_manager: TPLinkDeviceManager
) -> list:
    """Get devices without blocking the event loop.

    The library's get_devices() is async but internally calls
    get_device_info_list() which uses the sync `requests` library.
    HA 2026.3+ (Python 3.14) raises RuntimeError for blocking calls
    on the event loop. This helper runs the blocking part in an executor.
    """
    device_info_list = await hass.async_add_executor_job(
        device_manager._tplink_api.get_device_info_list,
        device_manager._auth_token,
    )

    devices = []
    children_gather_tasks = []
    for device_info in device_info_list:
        device = device_manager._construct_device(device_info)
        devices.append(device)
        if device.has_children():
            children_gather_tasks.append(device.get_children_async())

    devices_children = await asyncio.gather(*children_gather_tasks)
    for device_children in devices_children:
        devices.extend(device_children)

    # Handle multi-outlet devices not explicitly supported by the library
    # (e.g., KP200). Check sys_info for 'children' array and create child objects.
    unsupported_parents = [
        d for d in devices
        if not d.has_children()
        and getattr(d, "child_id", None) is None
        and hasattr(d, "device_info")
        and hasattr(d.device_info, "device_model")
        and d.device_info.device_model.startswith(("KP200", "KP400"))
    ]
    _LOGGER.debug(
        "Kasa Cloud: found %d unsupported multi-outlet devices", len(unsupported_parents)
    )
    if unsupported_parents:
        from tplinkcloud.device import TPLinkDevice

        child_tasks = [d.get_sys_info() for d in unsupported_parents]
        sys_infos = await asyncio.gather(*child_tasks, return_exceptions=True)
        for parent, sys_info in zip(unsupported_parents, sys_infos):
            if isinstance(sys_info, Exception):
                _LOGGER.warning(
                    "Kasa Cloud: sys_info failed for %s: %s",
                    parent.get_alias(),
                    sys_info,
                )
                continue
            if sys_info is None:
                _LOGGER.warning(
                    "Kasa Cloud: sys_info is None for %s", parent.get_alias()
                )
                continue
            raw = sys_info if isinstance(sys_info, dict) else vars(sys_info)
            children_data = raw.get("children", [])
            _LOGGER.info(
                "Kasa Cloud: %s has %d outlets, creating child devices",
                parent.get_alias(),
                len(children_data),
            )
            for child_info in children_data:
                child = TPLinkDevice(
                    parent._client,
                    parent.device_id,
                    type("ChildInfo", (), {
                        "alias": child_info.get("alias", parent.get_alias()),
                        "id": child_info.get("id"),
                        "state": child_info.get("state"),
                        "on_time": child_info.get("on_time"),
                    })(),
                    child_id=child_info.get("id"),
                )
                devices.append(child)
                _LOGGER.info(
                    "Kasa Cloud: created child '%s' (id=%s) for %s",
                    child_info.get("alias"),
                    child_info.get("id"),
                    parent.get_alias(),
                )

    return devices


@dataclass
class KasaCloudData:
    """Runtime data for the Kasa Cloud integration."""

    device_manager: TPLinkDeviceManager
    devices: list
    coordinator: KasaCloudCoordinator
    local_discovery: object | None = None


KasaCloudConfigEntry = ConfigEntry[KasaCloudData]


async def async_setup_entry(
    hass: HomeAssistant, entry: KasaCloudConfigEntry
) -> bool:
    """Set up Kasa Cloud from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    try:
        device_manager = await hass.async_add_executor_job(
            TPLinkDeviceManager, email, password
        )
        devices = await async_get_devices(hass, device_manager)
    except ValueError as err:
        raise ConfigEntryAuthFailed("Invalid credentials") from err
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to TP-Link cloud: {err}"
        ) from err

    child_count = sum(1 for d in devices if getattr(d, "child_id", None) is not None)
    _LOGGER.info("Kasa Cloud: found %d devices (%d children)", len(devices), child_count)

    smart_devices = [d for d in devices if _is_supported_device(d)]
    _LOGGER.info("Kasa Cloud: %d controllable smart devices", len(smart_devices))

    # Debug notification to verify deployment
    hass.components.persistent_notification.async_create(
        f"Total: {len(devices)}, Children: {child_count}, Smart: {len(smart_devices)}",
        title="Kasa Cloud Deploy Check",
        notification_id="kasa_cloud_deploy",
    )

    # Two-pass wrapping: parents/standalone first, then children with parent ref
    parent_wrappers: dict[str, KasaDeviceWrapper] = {}
    wrappers: dict[str, KasaDeviceWrapper] = {}
    wrapped_devices: list[KasaDeviceWrapper] = []

    for device in smart_devices:
        if getattr(device, "child_id", None) is None:
            wrapper = KasaDeviceWrapper(device)
            parent_wrappers[device.device_id] = wrapper
            wrappers[wrapper.device_id] = wrapper
            wrapped_devices.append(wrapper)

    for device in smart_devices:
        if getattr(device, "child_id", None) is not None:
            parent = parent_wrappers.get(device.device_id)
            wrapper = KasaDeviceWrapper(device, parent_wrapper=parent)
            wrappers[wrapper.device_id] = wrapper
            wrapped_devices.append(wrapper)

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = KasaCloudCoordinator(hass, wrapped_devices, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    # Start local discovery if enabled
    local_discovery = None
    local_control_enabled = entry.options.get(CONF_LOCAL_CONTROL, DEFAULT_LOCAL_CONTROL)
    if local_control_enabled:
        try:
            from kasa import Credentials

            from .local_discovery import LocalDeviceDiscovery

            credentials = Credentials(
                username=email,
                password=password,
            )
            local_wrappers = {
                w.device_id: w for w in wrapped_devices
                if w.child_id is None
            }
            local_discovery = LocalDeviceDiscovery(hass, local_wrappers, credentials)
            await local_discovery.async_start()
        except Exception:
            _LOGGER.warning("Failed to start local discovery, using cloud only")

    # Warn if official TP-Link integration is also loaded
    if "tplink" in hass.config.components:
        _LOGGER.warning(
            "The official TP-Link (tplink) integration is also loaded. "
            "Both may attempt local control of the same devices. "
            "Consider disabling local control in Kasa Cloud options."
        )

    entry.runtime_data = KasaCloudData(
        device_manager=device_manager,
        devices=wrapped_devices,
        coordinator=coordinator,
        local_discovery=local_discovery,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: KasaCloudConfigEntry
) -> None:
    """Handle options update — adjust coordinator polling and local control."""
    from datetime import timedelta

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = entry.runtime_data.coordinator
    if scan_interval > 0:
        coordinator.update_interval = timedelta(seconds=scan_interval)
    else:
        coordinator.update_interval = None
    _LOGGER.info("Kasa Cloud: polling interval changed to %ds", scan_interval)

    # Handle local control toggle
    local_enabled = entry.options.get(CONF_LOCAL_CONTROL, DEFAULT_LOCAL_CONTROL)
    discovery = entry.runtime_data.local_discovery

    if local_enabled and discovery is None:
        try:
            from kasa import Credentials

            from .local_discovery import LocalDeviceDiscovery

            credentials = Credentials(
                username=entry.data[CONF_EMAIL],
                password=entry.data[CONF_PASSWORD],
            )
            local_wrappers = {
                d.device_id: d for d in entry.runtime_data.devices
                if d.child_id is None
            }
            discovery = LocalDeviceDiscovery(hass, local_wrappers, credentials)
            await discovery.async_start()
            entry.runtime_data.local_discovery = discovery
            _LOGGER.info("Kasa Cloud: local control enabled")
        except Exception:
            _LOGGER.warning("Failed to start local discovery")
    elif not local_enabled and discovery is not None:
        discovery.async_stop()
        for wrapper in entry.runtime_data.devices:
            wrapper.detach_local()
        entry.runtime_data.local_discovery = None
        _LOGGER.info("Kasa Cloud: local control disabled")


async def async_unload_entry(
    hass: HomeAssistant, entry: KasaCloudConfigEntry
) -> bool:
    """Unload a config entry."""
    if entry.runtime_data.local_discovery:
        entry.runtime_data.local_discovery.async_stop()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
