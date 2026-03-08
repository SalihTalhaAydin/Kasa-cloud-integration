"""Sensor platform for Kasa Cloud integration."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfTime,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import is_dimmer_device
from .entity import KasaCloudEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KasaCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kasa Cloud sensor entities."""
    coordinator = entry.runtime_data.coordinator
    devices = entry.runtime_data.devices

    entities: list[SensorEntity] = []
    for device in devices:
        alias = device.get_alias()
        device_id = device.device_id
        model = device.device_info.device_model if hasattr(device, "device_info") else "Unknown"

        entities.append(
            KasaCloudRSSISensor(
                coordinator=coordinator,
                device_id=device_id,
                device_name=alias,
                model=model,
            )
        )
        entities.append(
            KasaCloudOnTimeSensor(
                coordinator=coordinator,
                device_id=device_id,
                device_name=alias,
                model=model,
            )
        )

        if is_dimmer_device(device):
            entities.append(
                KasaCloudAmbientLightSensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )

    async_add_entities(entities)
    _LOGGER.info("Kasa Cloud: added %d sensor entities", len(entities))


class KasaCloudRSSISensor(KasaCloudEntity, SensorEntity):
    """WiFi signal strength sensor."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the RSSI sensor."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_rssi"
        self._attr_name = "WiFi signal"

    @property
    def native_value(self) -> int | None:
        """Return the WiFi RSSI value."""
        return self._sys_info.get("rssi")


class KasaCloudOnTimeSensor(KasaCloudEntity, SensorEntity):
    """On time sensor (seconds since last power on)."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the on-time sensor."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_on_time"
        self._attr_name = "On time"

    @property
    def native_value(self) -> int | None:
        """Return the on-time in seconds."""
        return self._sys_info.get("on_time")


class KasaCloudAmbientLightSensor(KasaCloudEntity, SensorEntity):
    """Ambient light level sensor (dimmers only)."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the ambient light sensor."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_ambient_light"
        self._attr_name = "Ambient light"

    @property
    def native_value(self) -> int | None:
        """Return the ambient light level."""
        las_brt = self._device_data.get("las_brightness")
        if las_brt is None:
            return None
        if isinstance(las_brt, dict):
            return las_brt.get("value", las_brt.get("brt"))
        return None
