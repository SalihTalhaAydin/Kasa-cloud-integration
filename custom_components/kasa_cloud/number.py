"""Number platform for Kasa Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import is_dimmer_device
from .entity import KasaCloudEntity

_LOGGER = logging.getLogger(__name__)

DIMMER_TIME_SETTINGS = [
    {
        "key": "fade_on_time",
        "api_key": "fadeOnTime",
        "name": "Fade on time",
        "set_method": "set_fade_on_time",
        "param_key": "fadeTime",
        "min_value": 0,
        "max_value": 10000,
        "step": 100,
    },
    {
        "key": "fade_off_time",
        "api_key": "fadeOffTime",
        "name": "Fade off time",
        "set_method": "set_fade_off_time",
        "param_key": "fadeTime",
        "min_value": 0,
        "max_value": 10000,
        "step": 100,
    },
    {
        "key": "gentle_on_time",
        "api_key": "gentleOnTime",
        "name": "Gentle on time",
        "set_method": "set_gentle_on_time",
        "param_key": "duration",
        "min_value": 0,
        "max_value": 60000,
        "step": 1000,
    },
    {
        "key": "gentle_off_time",
        "api_key": "gentleOffTime",
        "name": "Gentle off time",
        "set_method": "set_gentle_off_time",
        "param_key": "duration",
        "min_value": 0,
        "max_value": 60000,
        "step": 1000,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KasaCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kasa Cloud number entities."""
    coordinator = entry.runtime_data.coordinator
    devices = entry.runtime_data.devices

    entities = []
    for device in devices:
        if not is_dimmer_device(device):
            continue
        alias = device.get_alias()
        device_id = device.device_id
        model = device.device_info.device_model if hasattr(device, "device_info") else "Unknown"

        for setting in DIMMER_TIME_SETTINGS:
            entities.append(
                KasaCloudDimmerTimeNumber(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                    setting=setting,
                )
            )

    async_add_entities(entities)
    _LOGGER.info("Kasa Cloud: added %d number entities", len(entities))


class KasaCloudDimmerTimeNumber(KasaCloudEntity, NumberEntity):
    """Number entity for dimmer timing settings (fade/gentle on/off)."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfTime.MILLISECONDS

    def __init__(self, coordinator, device_id, device_name, model, setting: dict) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, device_id, device_name, model)
        self._setting = setting
        self._attr_unique_id = f"kasa_cloud_{device_id}_{setting['key']}"
        self._attr_name = setting["name"]
        self._attr_native_min_value = setting["min_value"]
        self._attr_native_max_value = setting["max_value"]
        self._attr_native_step = setting["step"]

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        params = self._device_data.get("dimmer_params")
        if params is None:
            return None
        return params.get(self._setting["api_key"])

    async def async_set_native_value(self, value: float) -> None:
        """Set the timing value."""
        device = self._device
        if device is None:
            return
        await device._pass_through_request(
            "smartlife.iot.dimmer",
            self._setting["set_method"],
            {self._setting["param_key"]: int(value)},
        )
        await self.coordinator.async_request_refresh()
