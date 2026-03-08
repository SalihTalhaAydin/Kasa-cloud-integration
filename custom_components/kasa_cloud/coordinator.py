"""DataUpdateCoordinator for the Kasa Cloud integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, is_dimmer_device

_LOGGER = logging.getLogger(__name__)


class KasaCloudCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Coordinator to poll all Kasa Cloud devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        devices: list,
        scan_interval: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval) if scan_interval > 0 else None,
        )
        self._devices = devices
        self._device_map: dict[str, Any] = {d.device_id: d for d in devices}

    def get_device(self, device_id: str):
        """Return a device object by ID."""
        return self._device_map.get(device_id)

    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        """Fetch state for all devices from the cloud."""
        tasks = [self._fetch_device_data(d) for d in self._devices]
        device_data_list = await asyncio.gather(*tasks, return_exceptions=True)

        results: dict[str, dict[str, Any]] = {}
        errors = 0
        for device, data in zip(self._devices, device_data_list):
            if isinstance(data, Exception):
                _LOGGER.warning("Failed to poll %s: %s", device.get_alias(), data)
                errors += 1
                continue
            results[device.device_id] = data

        if errors == len(self._devices) and len(self._devices) > 0:
            raise UpdateFailed(f"All {errors} devices failed to poll")

        return results

    async def _fetch_device_data(self, device) -> dict[str, Any]:
        """Fetch all data for a single device."""
        data: dict[str, Any] = {}

        sys_info = await device.get_sys_info()
        if sys_info is None:
            raise UpdateFailed(f"get_sys_info returned None for {device.get_alias()}")
        data["sys_info"] = sys_info if isinstance(sys_info, dict) else vars(sys_info)

        if is_dimmer_device(device):
            try:
                data["pir_config"] = await device._pass_through_request(
                    "smartlife.iot.PIR", "get_config", {}
                )
            except Exception:
                _LOGGER.debug("PIR config not available for %s", device.get_alias())
                data["pir_config"] = None

            try:
                data["las_config"] = await device._pass_through_request(
                    "smartlife.iot.LAS", "get_config", {}
                )
            except Exception:
                _LOGGER.debug("LAS config not available for %s", device.get_alias())
                data["las_config"] = None

            try:
                data["las_brightness"] = await device._pass_through_request(
                    "smartlife.iot.LAS", "get_current_brt", {}
                )
            except Exception:
                _LOGGER.debug("LAS brightness not available for %s", device.get_alias())
                data["las_brightness"] = None

            try:
                data["dimmer_params"] = await device._pass_through_request(
                    "smartlife.iot.dimmer", "get_dimmer_parameters", {}
                )
            except Exception:
                _LOGGER.debug("Dimmer params not available for %s", device.get_alias())
                data["dimmer_params"] = None

        return data
