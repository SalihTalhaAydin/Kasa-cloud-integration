"""Button platform for Kasa Cloud integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import KasaCloudConfigEntry
from .const import is_child_device
from .entity import KasaCloudEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KasaCloudConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Kasa Cloud button entities."""
    coordinator = entry.runtime_data.coordinator
    devices = entry.runtime_data.devices

    entities = []
    for device in devices:
        alias = device.get_alias()
        device_id = device.device_id
        model = device.device_model
        parent_device_id = device.parent_device_id

        if is_child_device(device):
            # Children: refresh only (reboot affects entire physical device)
            entities.append(
                KasaCloudRefreshButton(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                    parent_device_id=parent_device_id,
                )
            )
        else:
            # Parent/standalone: reboot + refresh
            entities.append(
                KasaCloudRebootButton(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )
            entities.append(
                KasaCloudRefreshButton(
                    coordinator=coordinator,
                    device_id=device_id,
                    device_name=alias,
                    model=model,
                )
            )

    async_add_entities(entities)
    _LOGGER.info("Kasa Cloud: added %d button entities", len(entities))


class KasaCloudRebootButton(KasaCloudEntity, ButtonEntity):
    """Button to reboot the device."""

    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, device_id, device_name, model) -> None:
        """Initialize the reboot button."""
        super().__init__(coordinator, device_id, device_name, model)
        self._attr_unique_id = f"kasa_cloud_{device_id}_reboot"
        self._attr_name = "Reboot"

    async def async_press(self) -> None:
        """Reboot the device."""
        device = self._device
        if device is None:
            return
        await device._pass_through_request(
            "system", "reboot", {"delay": 1}
        )
        _LOGGER.info("Reboot command sent to %s", self._device_name)


class KasaCloudRefreshButton(KasaCloudEntity, ButtonEntity):
    """Button to refresh device state immediately."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, device_id, device_name, model, parent_device_id=None) -> None:
        """Initialize the refresh button."""
        super().__init__(coordinator, device_id, device_name, model, parent_device_id=parent_device_id)
        self._attr_unique_id = f"kasa_cloud_{device_id}_refresh"
        self._attr_name = "Refresh state"

    async def async_press(self) -> None:
        """Trigger an immediate state refresh."""
        await self.coordinator.async_request_refresh()
