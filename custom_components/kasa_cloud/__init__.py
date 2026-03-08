"""The Kasa Cloud integration."""
from __future__ import annotations

from dataclasses import dataclass
import logging

from tplinkcloud import TPLinkDeviceManager

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


@dataclass
class KasaCloudData:
    """Runtime data for the Kasa Cloud integration."""

    device_manager: TPLinkDeviceManager
    devices: list


KasaCloudConfigEntry = ConfigEntry[KasaCloudData]


async def async_setup_entry(
    hass: HomeAssistant, entry: KasaCloudConfigEntry
) -> bool:
    """Set up Kasa Cloud from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]

    try:
        # login() is synchronous (uses requests), run in executor
        device_manager = await hass.async_add_executor_job(
            TPLinkDeviceManager, email, password
        )
        devices = await device_manager.get_devices()
    except ValueError as err:
        raise ConfigEntryAuthFailed("Invalid credentials") from err
    except Exception as err:
        raise ConfigEntryNotReady(
            f"Cannot connect to TP-Link cloud: {err}"
        ) from err

    _LOGGER.info("Kasa Cloud: found %d devices", len(devices))

    # Filter to only IOT smart plug/switch devices (skip routers, decos, etc.)
    smart_devices = [
        d for d in devices
        if hasattr(d, 'device_info') and d.device_info.device_type == 'IOT.SMARTPLUGSWITCH'
    ]
    _LOGGER.info("Kasa Cloud: %d controllable smart devices", len(smart_devices))

    entry.runtime_data = KasaCloudData(
        device_manager=device_manager,
        devices=smart_devices,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: KasaCloudConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
