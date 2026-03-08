"""Switch platform for Kasa Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchDeviceClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KasaCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kasa Cloud switches from a config entry."""
    data = entry.runtime_data
    devices = data.devices

    entities = []
    for device in devices:
        alias = device.get_alias()
        device_id = device.device_id
        model = device.device_info.device_model if hasattr(device, "device_info") else "Unknown"

        entities.append(
            KasaCloudSwitch(
                device=device,
                name=alias,
                device_id=device_id,
                model=model,
            )
        )

    async_add_entities(entities, update_before_add=False)
    _LOGGER.info("Kasa Cloud: added %d switch entities", len(entities))


class KasaCloudSwitch(SwitchEntity):
    """A Kasa device controlled via TP-Link cloud."""

    _attr_has_entity_name = True
    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_should_poll = False  # Zero background polling

    def __init__(
        self,
        device: Any,
        name: str,
        device_id: str,
        model: str,
    ) -> None:
        """Initialize the switch."""
        self._device = device
        self._attr_name = name
        self._attr_unique_id = f"kasa_cloud_{device_id}"
        self._attr_is_on = None
        self._device_id = device_id
        self._model = model

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._attr_name,
            manufacturer="TP-Link",
            model=self._model,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on via cloud."""
        try:
            await self._device.power_on()
            self._attr_is_on = True
            self.async_write_ha_state()
        except Exception:
            _LOGGER.exception("Failed to turn on %s", self._attr_name)
            raise

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off via cloud."""
        try:
            await self._device.power_off()
            self._attr_is_on = False
            self.async_write_ha_state()
        except Exception:
            _LOGGER.exception("Failed to turn off %s", self._attr_name)
            raise

    async def async_update(self) -> None:
        """Fetch state from cloud (only called on manual refresh)."""
        try:
            self._attr_is_on = await self._device.is_on()
        except Exception:
            _LOGGER.exception("Failed to update %s", self._attr_name)
