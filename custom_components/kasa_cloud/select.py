"""Select platform for Kasa Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import is_dimmer_device
from .entity import KasaCloudEntity

_LOGGER = logging.getLogger(__name__)

MOTION_SENSITIVITY_OPTIONS = ["Far (25ft)", "Mid", "Near"]
SENSITIVITY_INDEX_MAP = {v: i for i, v in enumerate(MOTION_SENSITIVITY_OPTIONS)}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KasaCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kasa Cloud select entities."""
    coordinator = entry.runtime_data.coordinator
    devices = entry.runtime_data.devices

    entities = []
    for device in devices:
        if not is_dimmer_device(device):
            continue
        alias = device.get_alias()
        device_id = device.device_id
        model = device.device_info.device_model if hasattr(device, "device_info") else "Unknown"
        entities.append(
            KasaCloudMotionSensitivitySelect(
                coordinator=coordinator,
                device_id=device_id,
                device_name=alias,
                model=model,
            )
        )

    async_add_entities(entities)
    _LOGGER.info("Kasa Cloud: added %d select entities", len(entities))


class KasaCloudMotionSensitivitySelect(KasaCloudEntity, SelectEntity):
    """Select entity for motion sensor sensitivity."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = MOTION_SENSITIVITY_OPTIONS
    _attr_translation_key = "motion_sensitivity"

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_motion_sensitivity"
        self._attr_name = "Motion sensitivity"

    @property
    def current_option(self) -> str | None:
        """Return the current sensitivity option."""
        pir = self._device_data.get("pir_config")
        if pir is None:
            return None
        index = pir.get("trigger_index")
        if index is not None and 0 <= index < len(MOTION_SENSITIVITY_OPTIONS):
            return MOTION_SENSITIVITY_OPTIONS[index]
        return None

    async def async_select_option(self, option: str) -> None:
        """Set the motion sensitivity."""
        device = self._device
        if device is None:
            return
        index = SENSITIVITY_INDEX_MAP.get(option)
        if index is None:
            return
        await device._pass_through_request(
            "smartlife.iot.PIR", "set_trigger_sens", {"index": index}
        )
        await self.coordinator.async_request_refresh()
