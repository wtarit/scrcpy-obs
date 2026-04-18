# scrcpy-obs

OBS Studio plugin that adds **Android (scrcpy)** as a native source. Mirror an Android device straight into OBS over ADB — no window capture, no display mirror, no virtual camera driver.

> **Status:** pre-alpha, plugin scaffolding in progress. A working prototype using scrcpy's stream-sink feature + OBS Media Source is documented at the bottom of this README.

## Architecture

Plugin spawns a scrcpy subprocess per source instance, reads the MPEG-TS video stream over loopback TCP, decodes via OBS-provided FFmpeg libs, and pushes frames into OBS through `obs_source_output_video()`. Platform-agnostic — works on Windows, Linux, macOS.

Full reasoning in [`DECISION.md`](./DECISION.md). Context map in [`CLAUDE.md`](./CLAUDE.md).

```
Android                     Plugin process (in OBS)
+--------------+           +-------------------------------+
| scrcpy-server| --ADB---> | scrcpy.exe (subprocess)       |
| (MediaCodec) |           |   --stream-sink=tcp://...     |
+--------------+           +-------------+-----------------+
                                         | MPEG-TS loopback
                                         v
                           +-------------------------------+
                           | scrcpy-obs plugin             |
                           |   demux + decode + output     |
                           +-------------+-----------------+
                                         v
                                      OBS source
```

## Targets

- **Windows** (x64) — primary, MSVC
- **Linux** (x64, arm64) — secondary
- **macOS** (AppleSilicon, x64) — secondary

## Build requirements

- Visual Studio 2022 + Desktop C++ workload (Windows)
- CMake ≥ 3.28
- OBS Studio 31.1.1+ installed (for runtime testing)
- Qt 6 (pulled automatically by `buildspec.json` via obs-deps)
- MSYS2 MINGW64 (Windows only, for building the scrcpy subprocess binary):
  ```bash
  pacman -S mingw-w64-x86_64-meson mingw-w64-x86_64-ninja \
            mingw-w64-x86_64-SDL2 mingw-w64-x86_64-ffmpeg \
            mingw-w64-x86_64-libusb mingw-w64-x86_64-gcc
  ```
- Android device with USB debugging enabled, `adb` in PATH

## Repo layout

```
scrcpy-obs/
├── CMakeLists.txt          OBS plugin build
├── buildspec.json          OBS plugin dependency manifest
├── src/
│   └── plugin-main.c       module entry (stub)
├── data/locale/            i18n strings
├── cmake/                  CMake helpers (TODO: copy from obs-plugintemplate)
├── scrcpy/                 git submodule → Genymobile/scrcpy v3.3.4
├── CLAUDE.md               project context for Claude Code
├── DECISION.md             architecture decision record
└── README.md               this file
```

## Setup

```bash
git clone <repo-url>
cd scrcpy-obs
git submodule update --init --recursive
```

Build wiring not complete yet. See `DECISION.md` for next steps.

## Licensing

- Plugin: **GPL-2.0-or-later** (matching libobs).
- scrcpy (Apache-2.0) is shipped as a **separate binary**, not linked into the plugin — so the two remain separate works under their own licenses. See `DECISION.md` § Licensing for full reasoning.

## Potential improvements

- **CI dep caching** — Windows CI job downloads OBS source, prebuilt obs-deps, and Qt6 on every run (~several GB). Adding `actions/cache` keyed on `buildspec.json` dep versions would skip re-download when deps haven't changed. macOS/Linux already cache compiler output (`.ccache`); Windows has no cache at all.

## See also

- [scrcpy](https://github.com/Genymobile/scrcpy) — upstream project
- [obs-plugintemplate](https://github.com/obsproject/obs-plugintemplate) — template this plugin is based on
- [DistroAV](https://github.com/DistroAV/DistroAV) — NDI-for-OBS plugin, architectural reference
- [stream-sink PR #6721](https://github.com/Genymobile/scrcpy/pull/6721) — scrcpy PR used for MPEG-TS output
