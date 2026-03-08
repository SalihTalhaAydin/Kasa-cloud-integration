"""Light platform for Kasa Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import is_dimmer_device, is_light_switch
from .entity import KasaCloudEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KasaCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kasa Cloud lights from a config entry."""
    coordinator = entry.runtime_data.coordinator
    devices = entry.runtime_data.devices

    entities: list[LightEntity] = []
    for device in devices:
        alias = device.get_alias()
        device_id = device.device_id
        model = device.device_model

        if is_dimmer_device(device):
            entities.append(
                KasaCloudDimmerLight(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
        elif is_light_switch(device):
            entities.append(
                KasaCloudOnOffLight(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )

    async_add_entities(entities)
    _LOGGER.info("Kasa Cloud: added %d light entities", len(entities))


class KasaCloudDimmerLight(KasaCloudEntity, LightEntity):
    """A Kasa dimmer light (ES20M, KP405) with brightness control."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the dimmer light."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}"
        self._attr_name = None

    @property
    def is_on(self) -> bool | None:
        """Return True if the light is on."""
        relay = self._sys_info.get("relay_state")
        if relay is None:
            return None
        return relay == 1

    @property
    def brightness(self) -> int | None:
        """Return the brightness (0-255)."""
        brt = self._sys_info.get("brightness")
        if brt is None:
            return None
        # TP-Link uses 0-100, HA uses 0-255
        return round(brt * 255 / 100)

    def _update_sys_info(self, **updates: Any) -> None:
        """Optimistically update sys_info in coordinator data."""
        if self.coordinator.data and self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id]["sys_info"].update(updates)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the dimmer on, optionally with brightness/transition."""
        device = self._device
        if device is None:
            return

        brightness_pct = None
        if ATTR_BRIGHTNESS in kwargs:
            brightness_pct = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            brightness_pct = max(1, min(100, brightness_pct))

        transition_ms = None
        if ATTR_TRANSITION in kwargs:
            transition_ms = int(kwargs[ATTR_TRANSITION] * 1000)

        if brightness_pct is not None and transition_ms is not None:
            await device._pass_through_request(
                "smartlife.iot.dimmer",
                "set_dimmer_transition",
                {"brightness": brightness_pct, "duration": transition_ms},
            )
        elif brightness_pct is not None:
            await device.power_on()
            await device._pass_through_request(
                "smartlife.iot.dimmer",
                "set_brightness",
                {"brightness": brightness_pct},
            )
        else:
            await device.power_on()

        # Optimistic update
        updates = {"relay_state": 1}
        if brightness_pct is not None:
            updates["brightness"] = brightness_pct
        self._update_sys_info(**updates)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the dimmer off."""
        device = self._device
        if device is None:
            return

        transition_ms = None
        if ATTR_TRANSITION in kwargs:
            transition_ms = int(kwargs[ATTR_TRANSITION] * 1000)

        if transition_ms is not None:
            await device._pass_through_request(
                "smartlife.iot.dimmer",
                "set_dimmer_transition",
                {"brightness": 0, "duration": transition_ms},
            )
        else:
            await device.power_off()

        self._update_sys_info(relay_state=0)
        self.async_write_ha_state()


class KasaCloudOnOffLight(KasaCloudEntity, LightEntity):
    """A Kasa on/off wall switch (HS200) exposed as a light."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the on/off light."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}"
        self._attr_name = None

    @property
    def is_on(self) -> bool | None:
        """Return True if the light is on."""
        relay = self._sys_info.get("relay_state")
        if relay is None:
            return None
        return relay == 1

    def _update_sys_info(self, **updates: Any) -> None:
        """Optimistically update sys_info in coordinator data."""
        if self.coordinator.data and self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id]["sys_info"].update(updates)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        device = self._device
        if device is None:
            return
        await device.power_on()
        self._update_sys_info(relay_state=1)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        device = self._device
        if device is None:
            return
        await device.power_off()
        self._update_sys_info(relay_state=0)
        self.async_write_ha_state()
