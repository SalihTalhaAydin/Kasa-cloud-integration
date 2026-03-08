"""Switch platform for Kasa Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import is_dimmer_device, is_plug_device
from .entity import KasaCloudEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KasaCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kasa Cloud switches from a config entry."""
    coordinator = entry.runtime_data.coordinator
    devices = entry.runtime_data.devices

    entities: list[SwitchEntity] = []
    for device in devices:
        alias = device.get_alias()
        device_id = device.device_id
        model = device.device_info.device_model if hasattr(device, "device_info") else "Unknown"

        # Main on/off switch — only for smart plugs (KP200).
        # Dimmers and wall light switches use the light platform.
        if is_plug_device(device):
            entities.append(
                KasaCloudSwitch(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )

        # LED indicator switch — all devices
        entities.append(
            KasaCloudLEDSwitch(
                coordinator=coordinator,
                device_id=device_id,
                device_name=alias,
                model=model,
            )
        )

        # Motion and ambient switches — dimmers only
        if is_dimmer_device(device):
            entities.append(
                KasaCloudMotionSwitch(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
            entities.append(
                KasaCloudAmbientLightSwitch(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )

    async_add_entities(entities)
    _LOGGER.info("Kasa Cloud: added %d switch entities", len(entities))


class KasaCloudSwitch(KasaCloudEntity, SwitchEntity):
    """A Kasa smart plug (KP200) controlled via cloud."""

    _attr_device_class = SwitchDeviceClass.OUTLET

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}"
        self._attr_name = None

    @property
    def is_on(self) -> bool | None:
        """Return True if the switch is on."""
        relay = self._sys_info.get("relay_state")
        if relay is None:
            return None
        return relay == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on via cloud."""
        device = self._device
        if device is None:
            return
        await device.power_on()
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off via cloud."""
        device = self._device
        if device is None:
            return
        await device.power_off()
        await self.coordinator.async_request_refresh()


class KasaCloudLEDSwitch(KasaCloudEntity, SwitchEntity):
    """Switch to control the device's LED indicator."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the LED switch."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_led"
        self._attr_name = "LED indicator"

    @property
    def is_on(self) -> bool | None:
        """Return True if the LED is on (inverted: led_off=0 means on)."""
        led_off = self._sys_info.get("led_off")
        if led_off is None:
            return None
        return led_off == 0

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the LED on."""
        device = self._device
        if device is None:
            return
        await device.set_led_state(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the LED off."""
        device = self._device
        if device is None:
            return
        await device.set_led_state(False)
        await self.coordinator.async_request_refresh()


class KasaCloudMotionSwitch(KasaCloudEntity, SwitchEntity):
    """Switch to enable/disable PIR motion detection (dimmers only)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the motion switch."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_motion"
        self._attr_name = "Motion detection"

    @property
    def is_on(self) -> bool | None:
        """Return True if motion detection is enabled."""
        pir = self._device_data.get("pir_config")
        if pir is None:
            return None
        enable = pir.get("enable")
        if enable is None:
            return None
        return enable == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable motion detection."""
        device = self._device
        if device is None:
            return
        await device._pass_through_request(
            "smartlife.iot.PIR", "set_enable", {"enable": 1}
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable motion detection."""
        device = self._device
        if device is None:
            return
        await device._pass_through_request(
            "smartlife.iot.PIR", "set_enable", {"enable": 0}
        )
        await self.coordinator.async_request_refresh()


class KasaCloudAmbientLightSwitch(KasaCloudEntity, SwitchEntity):
    """Switch to enable/disable ambient light sensor (dimmers only)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the ambient light switch."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_ambient_light_enable"
        self._attr_name = "Ambient light sensor"

    @property
    def is_on(self) -> bool | None:
        """Return True if the ambient light sensor is enabled."""
        las = self._device_data.get("las_config")
        if las is None:
            return None
        enable = las.get("enable")
        if enable is None:
            return None
        return enable == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable the ambient light sensor."""
        device = self._device
        if device is None:
            return
        await device._pass_through_request(
            "smartlife.iot.LAS", "set_enable", {"enable": 1}
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable the ambient light sensor."""
        device = self._device
        if device is None:
            return
        await device._pass_through_request(
            "smartlife.iot.LAS", "set_enable", {"enable": 0}
        )
        await self.coordinator.async_request_refresh()
