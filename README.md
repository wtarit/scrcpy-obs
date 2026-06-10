# scrcpy Source for OBS

Android screen and camera mirroring for OBS Studio, powered by [scrcpy](https://github.com/Genymobile/scrcpy). Each source captures a connected Android device natively — no window capture or extra desktop app.

> **Status:** alpha — Windows x64 only for now.

## Requirements

- **OBS Studio 31** or newer (64-bit)
- **Windows 11** (x64)
- **Android device** with [USB debugging](https://developer.android.com/studio/debug/dev-options) enabled

## Install

1. Download the latest **Windows installer** from [Releases](https://github.com/wtarit/scrcpy-obs/releases).
2. Run the installer and restart OBS.

The source appears as **Android (scrcpy)** in the Add Source menu.

## Usage

1. Connect your Android device.
2. In OBS, click **+** → **Android (scrcpy)** → create the source.
3. Approve the USB debugging prompt on the phone.

You can add multiple sources for multiple devices (one source per device).

## Source settings

| Setting             | Description                                                   |
| ------------------- | ------------------------------------------------------------- |
| **Device**          | Android device from the ADB device list.                      |
| **Refresh Devices** | Update devices list.                                          |
| **Video source**    | **Display** (screen mirror) or **Camera** (device camera).    |
| **Camera ID**       | Camera index when Video source is Camera (0–9).               |
| **Max size**        | Longest-edge cap in pixels; `0` = native resolution.          |
| **Bitrate (Kbps)**  | Encoder bitrate (default 8000). Lower if you see lag.         |
| **Video codec**     | H.264 (default), H.265, or AV1. H.264 is the most compatible. |

## Troubleshooting

**Device not in the list**

- Unlock the phone and accept the USB debugging authorization dialog.
- Click **Refresh Devices**.
- Open a terminal and run `adb devices` — the device should show as `device` (not `unauthorized` or `offline`).

## Building from source

For developers and contributors: [CONTRIBUTING.md](CONTRIBUTING.md).
