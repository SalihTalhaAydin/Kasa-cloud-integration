"""Base entity for the Kasa Cloud integration."""
from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONN_MODE_UNAVAILABLE, DOMAIN
from .coordinator import KasaCloudCoordinator


class KasaCloudEntity(CoordinatorEntity[KasaCloudCoordinator]):
    """Base entity for Kasa Cloud devices."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KasaCloudCoordinator,
        device_id: str,
        device_name: str,
        model: str,
        parent_device_id: str | None = None,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._device_name = device_name
        self._model = model
        self._parent_device_id = parent_device_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._device_name,
            manufacturer="TP-Link",
            model=self._model,
        )
        if self._parent_device_id:
            info["via_device"] = (DOMAIN, self._parent_device_id)
        return info

    @property
    def _device(self):
        """Return the underlying tplink device object."""
        return self.coordinator.get_device(self._device_id)

    @property
    def _sys_info(self) -> dict[str, Any]:
        """Return sys_info data from coordinator."""
        if self.coordinator.data and self._device_id in self.coordinator.data:
            return self.coordinator.data[self._device_id].get("sys_info", {})
        return {}

    @property
    def _device_data(self) -> dict[str, Any]:
        """Return all data for this device from coordinator."""
        if self.coordinator.data and self._device_id in self.coordinator.data:
            return self.coordinator.data[self._device_id]
        return {}

    @property
    def _connection_mode(self) -> str:
        """Return the current connection mode for this device."""
        device = self._device
        if device is None:
            return CONN_MODE_UNAVAILABLE
        return device.connection_mode

    @property
    def available(self) -> bool:
        """Return True if coordinator has data for this device."""
        return (
            self.coordinator.last_update_success
            and self.coordinator.data is not None
            and self._device_id in self.coordinator.data
        )
