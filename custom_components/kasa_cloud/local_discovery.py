"""Local network device discovery and MAC-based matching."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from kasa import Credentials, Device, Discover

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from .const import LOCAL_DISCOVERY_INTERVAL, normalize_mac
from .device_wrapper import KasaDeviceWrapper

_LOGGER = logging.getLogger(__name__)

# Discovery can be flaky — retry up to this many times
DISCOVERY_RETRIES = 3
DISCOVERY_RETRY_DELAY = 5  # seconds between retries


class LocalDeviceDiscovery:
    """Discovers python-kasa devices on the LAN and matches them to cloud wrappers."""

    def __init__(
        self,
        hass: HomeAssistant,
        wrappers: dict[str, KasaDeviceWrapper],
        credentials: Credentials | None = None,
    ) -> None:
        """Initialize."""
        self._hass = hass
        self._wrappers = wrappers
        self._credentials = credentials
        self._cancel_timer = None
        # MAC -> device_id lookup for matching
        self._mac_to_device_id: dict[str, str] = {}
        for device_id, wrapper in wrappers.items():
            try:
                mac = wrapper.cloud_mac
                self._mac_to_device_id[mac] = device_id
            except Exception:
                _LOGGER.debug("No MAC for cloud device %s", device_id)
        # Store last known IPs for direct retry
        self._known_ips: dict[str, str] = {}  # MAC -> IP

    async def async_start(self) -> None:
        """Run initial discovery and start periodic timer."""
        await self._async_discover()
        self._cancel_timer = async_track_time_interval(
            self._hass,
            self._async_discover_callback,
            timedelta(seconds=LOCAL_DISCOVERY_INTERVAL),
        )

    @callback
    def async_stop(self) -> None:
        """Stop periodic discovery."""
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None

    async def _async_discover_callback(self, _now=None) -> None:
        """Timer callback wrapper."""
        await self._async_discover()

    async def _async_discover(self) -> None:
        """Run python-kasa discovery with retries and direct IP fallback."""
        _LOGGER.debug("Starting local device discovery")

        all_discovered: dict[str, Device] = {}

        # Broadcast discovery with retries
        for attempt in range(DISCOVERY_RETRIES):
            try:
                discovered = await Discover.discover(
                    credentials=self._credentials,
                    discovery_timeout=10,
                    discovery_packets=5,
                )
                all_discovered.update(discovered)
            except Exception as err:
                _LOGGER.debug("Discovery attempt %d failed: %s", attempt + 1, err)

            # Check if we've matched all cloud devices
            found_macs = set()
            for ip, device in all_discovered.items():
                try:
                    found_macs.add(normalize_mac(device.mac))
                except Exception:
                    pass

            unmatched = set(self._mac_to_device_id.keys()) - found_macs
            if not unmatched:
                break  # All devices found

            if attempt < DISCOVERY_RETRIES - 1:
                _LOGGER.debug(
                    "Discovery attempt %d: %d unmatched, retrying in %ds",
                    attempt + 1,
                    len(unmatched),
                    DISCOVERY_RETRY_DELAY,
                )
                await asyncio.sleep(DISCOVERY_RETRY_DELAY)

        # Direct IP fallback for any still-unmatched devices with known IPs
        found_macs = set()
        for ip, device in all_discovered.items():
            try:
                found_macs.add(normalize_mac(device.mac))
            except Exception:
                pass

        unmatched = set(self._mac_to_device_id.keys()) - found_macs
        if unmatched and self._known_ips:
            for mac in list(unmatched):
                known_ip = self._known_ips.get(mac)
                if known_ip and known_ip not in all_discovered:
                    try:
                        device = await Discover.discover_single(
                            known_ip,
                            credentials=self._credentials,
                            timeout=5,
                        )
                        if device:
                            all_discovered[known_ip] = device
                            _LOGGER.debug(
                                "Direct connection to %s succeeded for MAC %s",
                                known_ip,
                                mac,
                            )
                    except Exception:
                        _LOGGER.debug(
                            "Direct connection to %s failed for MAC %s",
                            known_ip,
                            mac,
                        )

        # Process all discovered devices
        found_macs = set()
        for ip, device in all_discovered.items():
            try:
                mac = normalize_mac(device.mac)
                found_macs.add(mac)
                # Remember this IP for future direct fallback
                self._known_ips[mac] = ip
                device_id = self._mac_to_device_id.get(mac)
                if device_id and device_id in self._wrappers:
                    wrapper = self._wrappers[device_id]
                    if wrapper.local_device is None:
                        wrapper.attach_local(device)
                    elif wrapper.local_device.host != ip:
                        # IP changed
                        wrapper.detach_local()
                        wrapper.attach_local(device)
            except Exception:
                _LOGGER.debug("Could not process discovered device at %s", ip)

        # Detach wrappers whose local devices were not found
        for wrapper in self._wrappers.values():
            if wrapper.local_device is not None:
                if wrapper.cloud_mac not in found_macs:
                    wrapper.detach_local()

        matched = sum(1 for w in self._wrappers.values() if w.local_device is not None)
        _LOGGER.info(
            "Local discovery: %d found, %d matched of %d cloud devices",
            len(all_discovered),
            matched,
            len(self._wrappers),
        )
