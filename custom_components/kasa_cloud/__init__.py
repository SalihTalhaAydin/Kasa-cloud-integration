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

    _LOGGER.info("Kasa Cloud: found %d devices", len(devices))

    smart_devices = [
        d for d in devices
        if hasattr(d, "device_info")
        and d.device_info.device_type == "IOT.SMARTPLUGSWITCH"
    ]
    _LOGGER.info("Kasa Cloud: %d controllable smart devices", len(smart_devices))

    # Wrap cloud devices in KasaDeviceWrapper for local+cloud routing
    wrappers: dict[str, KasaDeviceWrapper] = {}
    wrapped_devices: list[KasaDeviceWrapper] = []
    for device in smart_devices:
        wrapper = KasaDeviceWrapper(device)
        wrappers[device.device_id] = wrapper
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
            local_discovery = LocalDeviceDiscovery(hass, wrappers, credentials)
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
            wrappers = {d.device_id: d for d in entry.runtime_data.devices}
            discovery = LocalDeviceDiscovery(hass, wrappers, credentials)
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
