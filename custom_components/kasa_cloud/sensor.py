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
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import (
    CONN_MODE_LOCAL,
    is_child_device,
    is_dimmer_device,
    is_tapo_energy_plug,
)
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
        model = device.device_model
        parent_device_id = device.parent_device_id

        if device.is_tapo:
            # Tapo: connection mode + energy sensors
            entities.append(
                KasaCloudConnectionModeSensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
            if is_tapo_energy_plug(device):
                entities.append(
                    TapoPowerSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=alias,
                        model=model,
                    )
                )
                entities.append(
                    TapoVoltageSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=alias,
                        model=model,
                    )
                )
                entities.append(
                    TapoCurrentSensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=alias,
                        model=model,
                    )
                )
                entities.append(
                    TapoTotalEnergySensor(
                        coordinator=coordinator,
                        device_id=device_id,
                        device_name=alias,
                        model=model,
                    )
                )
            continue
        elif is_child_device(device):
            # Children: on-time only
            entities.append(
                KasaCloudOnTimeSensor(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                    parent_device_id=parent_device_id,
                )
            )
        else:
            # Parent/standalone IOT: all sensors
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
            entities.append(
                KasaCloudConnectionModeSensor(
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

    def __init__(self, coordinator, device_id, device_name, model, parent_device_id=None) -> None:
        """Initialize the on-time sensor."""
        super().__init__(coordinator, device_id, device_name, model, parent_device_id=parent_device_id)
        self._attr_unique_id = f"kasa_cloud_{device_id}_on_time"
        self._attr_name = "On time"

    @property
    def native_value(self) -> int | None:
        """Return the on-time in seconds."""
        return self._sys_info.get("on_time")


class KasaCloudConnectionModeSensor(KasaCloudEntity, SensorEntity):
    """Diagnostic sensor showing Local or Cloud connection mode."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the connection mode sensor."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_connection_mode"
        self._attr_name = "Connection mode"

    @property
    def native_value(self) -> str | None:
        """Return the current connection mode."""
        return self._connection_mode

    @property
    def icon(self) -> str:
        """Return icon based on connection mode."""
        if self._connection_mode == CONN_MODE_LOCAL:
            return "mdi:lan"
        return "mdi:cloud"


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


# --- Tapo energy monitoring sensors ---


class TapoPowerSensor(KasaCloudEntity, SensorEntity):
    """Real-time power consumption (W)."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, coordinator, device_id, device_name, model,
    ) -> None:
        super().__init__(
            coordinator, device_id, device_name, model,
        )
        self._attr_unique_id = (
            f"kasa_cloud_{device_id}_power"
        )
        self._attr_name = "Power"

    @property
    def native_value(self) -> float | None:
        emeter = self._sys_info.get("emeter", {})
        return emeter.get("power_w")


class TapoVoltageSensor(KasaCloudEntity, SensorEntity):
    """Real-time voltage (V)."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = (
        UnitOfElectricPotential.VOLT
    )
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator, device_id, device_name, model,
    ) -> None:
        super().__init__(
            coordinator, device_id, device_name, model,
        )
        self._attr_unique_id = (
            f"kasa_cloud_{device_id}_voltage"
        )
        self._attr_name = "Voltage"

    @property
    def native_value(self) -> float | None:
        emeter = self._sys_info.get("emeter", {})
        return emeter.get("voltage_v")


class TapoCurrentSensor(KasaCloudEntity, SensorEntity):
    """Real-time current (A)."""

    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = (
        UnitOfElectricCurrent.AMPERE
    )
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator, device_id, device_name, model,
    ) -> None:
        super().__init__(
            coordinator, device_id, device_name, model,
        )
        self._attr_unique_id = (
            f"kasa_cloud_{device_id}_current"
        )
        self._attr_name = "Current"

    @property
    def native_value(self) -> float | None:
        emeter = self._sys_info.get("emeter", {})
        return emeter.get("current_a")


class TapoTotalEnergySensor(KasaCloudEntity, SensorEntity):
    """Total energy consumption (kWh)."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = (
        UnitOfEnergy.KILO_WATT_HOUR
    )
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self, coordinator, device_id, device_name, model,
    ) -> None:
        super().__init__(
            coordinator, device_id, device_name, model,
        )
        self._attr_unique_id = (
            f"kasa_cloud_{device_id}_total_energy"
        )
        self._attr_name = "Total energy"

    @property
    def native_value(self) -> float | None:
        emeter = self._sys_info.get("emeter", {})
        return emeter.get("total_kwh")
