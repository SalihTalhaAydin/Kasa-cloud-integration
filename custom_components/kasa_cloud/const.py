"""Constants for the Kasa Cloud integration."""
from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "kasa_cloud"
PLATFORMS: list[Platform] = [
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

DIMMER_MODELS = ("ES20M", "KP405")
LIGHT_SWITCH_MODELS = ("HS200", "HS210", "HS220")

DEFAULT_SCAN_INTERVAL = 60
CONF_SCAN_INTERVAL = "scan_interval"

# Local control constants
LOCAL_DISCOVERY_INTERVAL = 300  # seconds (5 minutes)
LOCAL_COMMAND_TIMEOUT = 3.0  # seconds before falling back to cloud
CONF_LOCAL_CONTROL = "local_control"
DEFAULT_LOCAL_CONTROL = True

# Connection mode values (for diagnostic sensor)
CONN_MODE_LOCAL = "Local"
CONN_MODE_CLOUD = "Cloud"
CONN_MODE_UNAVAILABLE = "Unavailable"


def normalize_mac(mac: str) -> str:
    """Normalize MAC address to uppercase hex without separators."""
    return mac.upper().replace(":", "").replace("-", "")


def is_dimmer_device(device) -> bool:
    """Return True if device is a dimmer (ES20M, KP405)."""
    model = device.device_info.device_model
    return any(model.startswith(p) for p in DIMMER_MODELS)


def is_light_switch(device) -> bool:
    """Return True for wall switches that control lights (HS200, etc.)."""
    model = device.device_info.device_model
    return any(model.startswith(p) for p in LIGHT_SWITCH_MODELS)


def is_plug_device(device) -> bool:
    """Return True for smart plugs (KP200, etc.) — use switch platform."""
    return not is_dimmer_device(device) and not is_light_switch(device)
