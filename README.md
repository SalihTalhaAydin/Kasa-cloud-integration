<p align="center">
  <img src="https://brands.home-assistant.io/_/kasa/icon.png" alt="Kasa Cloud" width="120" height="120">
</p>

<h1 align="center">Kasa Cloud</h1>

<p align="center">
  <strong>A Home Assistant custom integration for TP-Link Kasa devices via cloud API</strong>
</p>

<p align="center">
  <a href="https://github.com/SalihTalhaAydin/Kasa-cloud-integration/releases"><img src="https://img.shields.io/github/v/release/SalihTalhaAydin/Kasa-cloud-integration?style=for-the-badge&color=blue" alt="Release"></a>
  <a href="https://github.com/SalihTalhaAydin/Kasa-cloud-integration/stargazers"><img src="https://img.shields.io/github/stars/SalihTalhaAydin/Kasa-cloud-integration?style=for-the-badge&color=yellow" alt="Stars"></a>
  <a href="https://github.com/SalihTalhaAydin/Kasa-cloud-integration/issues"><img src="https://img.shields.io/github/issues/SalihTalhaAydin/Kasa-cloud-integration?style=for-the-badge&color=red" alt="Issues"></a>
  <a href="https://github.com/SalihTalhaAydin/Kasa-cloud-integration/blob/main/LICENSE"><img src="https://img.shields.io/github/license/SalihTalhaAydin/Kasa-cloud-integration?style=for-the-badge" alt="License"></a>
  <a href="https://github.com/hacs/integration"><img src="https://img.shields.io/badge/HACS-Custom-41BDF5?style=for-the-badge" alt="HACS"></a>
</p>

<p align="center">
  Control your TP-Link Kasa devices through the cloud — no local network access required.<br>
  Perfect for devices behind separate VLANs, remote locations, or when local control isn't an option.
</p>

---

## Why Kasa Cloud?

The built-in TP-Link Kasa integration uses **local polling**, which can overwhelm device firmware and cause crashes. This integration uses the **TP-Link cloud API** instead, providing:

- **Reliable polling** — cloud API is stable at 60-second intervals (configurable)
- **No firmware crashes** — requests go to TP-Link servers, not directly to devices
- **Remote access** — control devices from anywhere, no local network needed
- **Full feature support** — brightness, motion sensors, ambient light, dimmer timing, and more

## Supported Devices

| Device | Type | Features |
|--------|------|----------|
| **ES20M** | Smart Dimmer Switch | Brightness, fade/gentle timing, PIR motion sensor, ambient light sensor |
| **KP405** | Outdoor Smart Dimmer Plug | Brightness, fade/gentle timing, PIR motion sensor, ambient light sensor |
| **HS200 / HS210 / HS220** | Wall Light Switch | On/off control (exposed as `light` entity) |
| **KP200** | Smart Plug (2-outlet) | On/off control (exposed as `switch` entity) |

> Other TP-Link Kasa devices may also work — the integration discovers all devices registered to your TP-Link cloud account.

## Entities

Each device gets a rich set of entities depending on its capabilities:

### Primary Controls
| Entity | Platform | Devices | Description |
|--------|----------|---------|-------------|
| Light (dimmer) | `light` | ES20M, KP405 | On/off + brightness (0–100%) with transition support |
| Light (on/off) | `light` | HS200, HS210, HS220 | Simple on/off for wall switches |
| Switch | `switch` | KP200 | On/off for smart plugs |

### Configuration
| Entity | Platform | Devices | Description |
|--------|----------|---------|-------------|
| LED Indicator | `switch` | All | Toggle the device's status LED |
| Motion Detection | `switch` | Dimmers | Enable/disable PIR motion sensor |
| Ambient Light Sensor | `switch` | Dimmers | Enable/disable ambient light sensor |
| Motion Sensitivity | `select` | Dimmers | Far (25ft) / Mid / Near |
| Fade On Time | `number` | Dimmers | 0–10,000 ms (100 ms steps) |
| Fade Off Time | `number` | Dimmers | 0–10,000 ms (100 ms steps) |
| Gentle On Time | `number` | Dimmers | 0–60,000 ms (1,000 ms steps) |
| Gentle Off Time | `number` | Dimmers | 0–60,000 ms (1,000 ms steps) |

### Diagnostics
| Entity | Platform | Devices | Description |
|--------|----------|---------|-------------|
| WiFi Signal (RSSI) | `sensor` | All | Signal strength in dBm |
| On Time | `sensor` | All | Uptime since last power cycle |
| Ambient Light Level | `sensor` | Dimmers | Current light level (%) |

### Actions
| Entity | Platform | Devices | Description |
|--------|----------|---------|-------------|
| Reboot | `button` | All | Restart the device |
| Refresh State | `button` | All | Force an immediate state refresh |

## Installation

### HACS (Recommended)

1. Open **HACS** in Home Assistant
2. Click the **three dots** menu (top right) → **Custom repositories**
3. Add this repository URL:
   ```
   https://github.com/SalihTalhaAydin/Kasa-cloud-integration
   ```
4. Select **Integration** as the category
5. Click **Add** → find **Kasa Cloud** → click **Download**
6. **Restart Home Assistant**

### Manual Installation

1. Download the [latest release](https://github.com/SalihTalhaAydin/Kasa-cloud-integration/releases)
2. Copy `custom_components/kasa_cloud/` to your Home Assistant `config/custom_components/` directory
3. **Restart Home Assistant**

## Setup

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for **Kasa Cloud**
3. Enter your **TP-Link / Kasa account** email and password
4. All devices registered to your cloud account will be discovered automatically

> **Note:** Two-factor authentication (2FA) must be **disabled** on your TP-Link account.

### Options

After setup, configure the integration via **Settings** → **Devices & Services** → **Kasa Cloud** → **Configure**:

| Option | Default | Range | Description |
|--------|---------|-------|-------------|
| Polling Interval | 60s | 0–300s | How often to sync state from the cloud. Set to `0` to disable automatic polling. |

## How It Works

```
┌──────────────┐     Cloud API      ┌─────────────────┐     Reports state     ┌──────────────┐
│ Home         │ ◄────────────────► │  TP-Link Cloud   │ ◄──────────────────── │  Kasa Device │
│ Assistant    │   (60s polling)    │  (wap.tplink     │    (~40s after        │  (ES20M,     │
│              │   + commands       │   cloud.com)     │     physical toggle)  │   KP405, ..) │
└──────────────┘                    └─────────────────┘                        └──────────────┘
```

- **Polling**: A single `DataUpdateCoordinator` polls all devices every 60 seconds via the cloud API
- **Commands**: Turn on/off, brightness changes, and configuration updates are sent immediately through the cloud
- **Optimistic Updates**: The UI updates instantly after commands — no waiting for the next poll cycle
- **Physical Toggles**: When someone flips a physical switch, the device reports the change to TP-Link's cloud within ~40 seconds, picked up at the next poll

## Known Limitations

- **Cloud latency**: Physical switch changes take ~40 seconds to reach the cloud, then up to 60 seconds to be polled
- **No real-time motion events**: The cloud API allows configuring motion detection (enable/disable, sensitivity) but does **not** expose real-time motion detection events
- **2FA not supported**: Two-factor authentication must be disabled on your TP-Link account
- **KP200 multi-outlet**: Currently shows the parent device only; individual outlet control is a known limitation

## Contributing

Contributions are welcome! Please open an [issue](https://github.com/SalihTalhaAydin/Kasa-cloud-integration/issues) or submit a pull request.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built on [tplink-cloud-api](https://pypi.org/project/tplink-cloud-api/) by Moe Seoud
- Inspired by the official [TP-Link Kasa Smart](https://www.home-assistant.io/integrations/tplink/) integration
