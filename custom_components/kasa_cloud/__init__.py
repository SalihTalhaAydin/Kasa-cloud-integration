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

from .const import CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN, PLATFORMS
from .coordinator import KasaCloudCoordinator

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

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = KasaCloudCoordinator(hass, smart_devices, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = KasaCloudData(
        device_manager=device_manager,
        devices=smart_devices,
        coordinator=coordinator,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def _async_update_listener(
    hass: HomeAssistant, entry: KasaCloudConfigEntry
) -> None:
    """Handle options update — adjust coordinator polling interval."""
    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    coordinator = entry.runtime_data.coordinator
    if scan_interval > 0:
        from datetime import timedelta

        coordinator.update_interval = timedelta(seconds=scan_interval)
    else:
        coordinator.update_interval = None
    _LOGGER.info("Kasa Cloud: polling interval changed to %ds", scan_interval)


async def async_unload_entry(
    hass: HomeAssistant, entry: KasaCloudConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
