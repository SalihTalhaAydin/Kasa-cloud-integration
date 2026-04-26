"""Light platform for Kasa Cloud integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ATTR_TRANSITION,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import (
    is_dimmer_device,
    is_iot_bulb,
    is_iot_light_strip,
    is_light_switch,
    is_tapo_bulb,
)
from .entity import KasaCloudEntity

_LOGGER = logging.getLogger(__name__)


def _is_smart_kasa_dimmer(device) -> bool:
    """Return True for SMART-protocol Kasa dimmers (e.g. new HS220)."""
    if not device.is_tapo:
        return False
    model = device.device_model
    # HS220 is a dimmer, even when using SMART protocol
    return model.startswith("HS220")


def _is_smart_kasa_switch(device) -> bool:
    """Return True for SMART-protocol Kasa on/off switches."""
    if not device.is_tapo:
        return False
    model = device.device_model
    return model.startswith(("HS200", "HS210"))


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

        # SMART-protocol Kasa dimmers (new HS220 firmware)
        if _is_smart_kasa_dimmer(device):
            entities.append(
                KasaCloudSmartDimmerLight(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
            continue

        # SMART-protocol Kasa on/off switches
        if _is_smart_kasa_switch(device):
            entities.append(
                KasaCloudSmartOnOffLight(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
            continue

        # Tapo bulbs (L530E, etc.) — color/brightness/color_temp via local
        if is_tapo_bulb(device):
            entities.append(
                KasaCloudTapoBulbLight(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
            continue

        # Skip other Tapo devices (plugs handled by switch platform)
        if device.is_tapo:
            continue

        # IOT smart bulbs/strips (KL400L5, etc.) — via cloud passthrough
        if is_iot_bulb(device):
            entities.append(
                KasaCloudIotBulbLight(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
            continue

        # IOT dimmers (ES20M, KP405)
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

        # When no brightness specified, preserve the current brightness
        # to prevent repeated turn_on calls from slowly dimming to 1%
        if brightness_pct is None:
            current_brt = self._sys_info.get("brightness")
            if current_brt is not None and current_brt > 0:
                brightness_pct = current_brt

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


class KasaCloudSmartDimmerLight(KasaCloudEntity, LightEntity):
    """A SMART-protocol Kasa dimmer (new HS220) with brightness via local python-kasa."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize."""
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
        return round(brt * 255 / 100)

    def _update_sys_info(self, **updates: Any) -> None:
        """Optimistically update sys_info in coordinator data."""
        if self.coordinator.data and self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id]["sys_info"].update(updates)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on via local python-kasa device."""
        device = self._device
        if device is None:
            return
        local = device.local_device
        if local is None:
            _LOGGER.warning("No local device for %s — cannot control", device.get_alias())
            return

        brightness_pct = None
        if ATTR_BRIGHTNESS in kwargs:
            brightness_pct = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            brightness_pct = max(1, min(100, brightness_pct))

        if brightness_pct is not None:
            await local.set_brightness(brightness_pct)
        else:
            await local.turn_on()

        updates = {"relay_state": 1}
        if brightness_pct is not None:
            updates["brightness"] = brightness_pct
        self._update_sys_info(**updates)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off via local python-kasa device."""
        device = self._device
        if device is None:
            return
        local = device.local_device
        if local is None:
            _LOGGER.warning("No local device for %s — cannot control", device.get_alias())
            return
        await local.turn_off()
        self._update_sys_info(relay_state=0)
        self.async_write_ha_state()


class KasaCloudSmartOnOffLight(KasaCloudEntity, LightEntity):
    """A SMART-protocol Kasa on/off switch (new HS200/HS210) via local python-kasa."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize."""
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
        """Turn on via local python-kasa."""
        device = self._device
        if device is None:
            return
        await device.power_on()
        self._update_sys_info(relay_state=1)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off via local python-kasa."""
        device = self._device
        if device is None:
            return
        await device.power_off()
        self._update_sys_info(relay_state=0)
        self.async_write_ha_state()


class KasaCloudTapoBulbLight(KasaCloudEntity, LightEntity):
    """A Tapo smart bulb (L530E, etc.) controlled via local python-kasa."""

    _attr_supported_color_modes = {
        ColorMode.HS,
        ColorMode.COLOR_TEMP,
    }

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}"
        self._attr_name = None

    @property
    def color_mode(self) -> ColorMode:
        """Return the current color mode."""
        ct = self._sys_info.get("color_temp")
        if ct and ct > 0:
            return ColorMode.COLOR_TEMP
        return ColorMode.HS

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
        return round(brt * 255 / 100)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation."""
        hue = self._sys_info.get("hue")
        sat = self._sys_info.get("saturation")
        if hue is not None and sat is not None:
            return (hue, sat)
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        return self._sys_info.get("color_temp")

    @property
    def min_color_temp_kelvin(self) -> int:
        """Return min supported color temp."""
        ct_range = self._sys_info.get("color_temp_range")
        if ct_range:
            return ct_range[0]
        return 2500

    @property
    def max_color_temp_kelvin(self) -> int:
        """Return max supported color temp."""
        ct_range = self._sys_info.get("color_temp_range")
        if ct_range:
            return ct_range[1]
        return 6500

    def _update_sys_info(self, **updates: Any) -> None:
        """Optimistically update sys_info in coordinator data."""
        if self.coordinator.data and self._device_id in self.coordinator.data:
            self.coordinator.data[self._device_id]["sys_info"].update(updates)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on via local python-kasa device."""
        device = self._device
        if device is None:
            return
        local = device.local_device
        if local is None:
            _LOGGER.warning("No local device for %s", device.get_alias())
            return

        updates: dict[str, Any] = {"relay_state": 1}

        if ATTR_HS_COLOR in kwargs:
            hue, sat = kwargs[ATTR_HS_COLOR]
            brt_pct = round(kwargs.get(ATTR_BRIGHTNESS, self.brightness or 255) * 100 / 255)
            brt_pct = max(1, min(100, brt_pct))
            await local.set_hsv(int(hue), int(sat), brt_pct)
            updates["hue"] = int(hue)
            updates["saturation"] = int(sat)
            updates["brightness"] = brt_pct
            updates["color_temp"] = 0
        elif ATTR_COLOR_TEMP_KELVIN in kwargs:
            ct = kwargs[ATTR_COLOR_TEMP_KELVIN]
            await local.set_color_temp(ct)
            updates["color_temp"] = ct
            if ATTR_BRIGHTNESS in kwargs:
                brt_pct = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
                brt_pct = max(1, min(100, brt_pct))
                await local.set_brightness(brt_pct)
                updates["brightness"] = brt_pct
        elif ATTR_BRIGHTNESS in kwargs:
            brt_pct = round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)
            brt_pct = max(1, min(100, brt_pct))
            await local.set_brightness(brt_pct)
            updates["brightness"] = brt_pct
        else:
            await local.turn_on()

        self._update_sys_info(**updates)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off via local python-kasa device."""
        device = self._device
        if device is None:
            return
        local = device.local_device
        if local is None:
            _LOGGER.warning("No local device for %s", device.get_alias())
            return
        await local.turn_off()
        self._update_sys_info(relay_state=0)
        self.async_write_ha_state()


class KasaCloudIotBulbLight(KasaCloudEntity, LightEntity):
    """A Kasa IOT smart bulb/strip via cloud passthrough only.

    No local polling — uses cloud API exclusively.
    Light strips (KL400, KL430) use smartlife.iot.lightStrip.
    Other bulbs use smartlife.iot.smartbulb.lightingservice.
    """

    _attr_supported_color_modes = {
        ColorMode.HS,
        ColorMode.COLOR_TEMP,
    }

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}"
        self._attr_name = None
        # Light strips use a different cloud module
        if is_iot_light_strip(self._device):
            self._light_module = "smartlife.iot.lightStrip"
            self._light_method = "set_light_state"
        else:
            self._light_module = (
                "smartlife.iot.smartbulb.lightingservice"
            )
            self._light_method = "transition_light_state"

    @property
    def color_mode(self) -> ColorMode:
        """Return the current color mode."""
        ct = self._active_light_state.get("color_temp")
        if ct and ct > 0:
            return ColorMode.COLOR_TEMP
        return ColorMode.HS

    @property
    def is_on(self) -> bool | None:
        """Return True if the light is on."""
        light_state = self._sys_info.get("light_state", {})
        if isinstance(light_state, dict):
            on_off = light_state.get("on_off")
            if on_off is not None:
                return on_off == 1
        relay = self._sys_info.get("relay_state")
        if relay is not None:
            return relay == 1
        return None

    @property
    def brightness(self) -> int | None:
        """Return the brightness (0-255)."""
        brt = self._active_light_state.get("brightness")
        if brt is None:
            return None
        return round(brt * 255 / 100)

    @property
    def hs_color(self) -> tuple[float, float] | None:
        """Return the hue and saturation."""
        ls = self._active_light_state
        hue = ls.get("hue")
        sat = ls.get("saturation")
        if hue is not None and sat is not None:
            return (hue, sat)
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the color temperature in Kelvin."""
        return self._active_light_state.get("color_temp")

    @property
    def min_color_temp_kelvin(self) -> int:
        return 2500

    @property
    def max_color_temp_kelvin(self) -> int:
        return 9000

    @property
    def _active_light_state(self) -> dict:
        """Return the active light state dict.

        IOT bulbs nest state in light_state. When off, the active params
        are in light_state.dft_on_state instead.
        """
        ls = self._sys_info.get("light_state", {})
        if not isinstance(ls, dict):
            return {}
        if ls.get("on_off") == 0:
            return ls.get("dft_on_state", ls)
        return ls

    def _update_sys_info(self, **updates: Any) -> None:
        """Optimistically update sys_info in coordinator data."""
        if self.coordinator.data and self._device_id in self.coordinator.data:
            si = self.coordinator.data[self._device_id]["sys_info"]
            if "light_state" in si:
                si["light_state"].update(updates)
            else:
                si.update(updates)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on via cloud passthrough."""
        device = self._device
        if device is None:
            return

        params: dict[str, Any] = {"on_off": 1}

        if ATTR_HS_COLOR in kwargs:
            hue, sat = kwargs[ATTR_HS_COLOR]
            params["hue"] = int(hue)
            params["saturation"] = int(sat)
            params["color_temp"] = 0
            if ATTR_BRIGHTNESS in kwargs:
                params["brightness"] = max(1, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            params["color_temp"] = kwargs[ATTR_COLOR_TEMP_KELVIN]
            if ATTR_BRIGHTNESS in kwargs:
                params["brightness"] = max(1, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))

        if ATTR_BRIGHTNESS in kwargs and "brightness" not in params:
            params["brightness"] = max(1, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))

        if ATTR_TRANSITION in kwargs:
            params["transition_period"] = int(kwargs[ATTR_TRANSITION] * 1000)

        await device._pass_through_request(
            self._light_module,
            self._light_method,
            params,
        )

        self._update_sys_info(**params)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off via cloud passthrough."""
        device = self._device
        if device is None:
            return

        params: dict[str, Any] = {"on_off": 0}
        if ATTR_TRANSITION in kwargs:
            params["transition_period"] = (
                int(kwargs[ATTR_TRANSITION] * 1000)
            )

        await device._pass_through_request(
            self._light_module,
            self._light_method,
            params,
        )

        self._update_sys_info(**params)
        self.async_write_ha_state()
