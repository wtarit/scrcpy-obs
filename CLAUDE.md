# scrcpy-obs — Claude Context

## What this repo is
OBS Studio plugin that adds "Android (scrcpy)" as a native OBS source. Under the hood it uses [scrcpy](https://github.com/Genymobile/scrcpy) to capture Android screens over ADB — no display mirroring, no window capture, direct MediaCodec H.264 → decoded frame → OBS source.

Target platform: Windows first (user's primary OS). Linux/macOS later.

## Current status
Pre-alpha. Skeleton only. No source type registered yet, no scrcpy integration wired. See `DECISION.md` for architecture rationale.

## Repo layout
- `CMakeLists.txt`, `buildspec.json` — OBS plugin build (based on `obsproject/obs-plugintemplate`)
- `src/plugin-main.c` — module entry, stub
- `data/locale/en-US.ini` — i18n strings
- `cmake/`, `.github/` — build helpers (to copy from obs-plugintemplate as needed)
- `scrcpy/` — **git submodule**, pinned to `v3.3.4`. Points at fork `https://github.com/wtarit/scrcpy` (origin) with Genymobile upstream as secondary remote. Used for building the scrcpy subprocess binary that ships with the plugin. Once PR #6721 is cherry-picked on a `streamsink/vX.Y.Z` branch in the fork, submodule moves to that tag. Do not edit source files in place — go through the fork.
- `scripts/` — legacy MPEG-TS stream-sink scripts (pre-pivot). Kept for reference. See `DECISION.md`.
- `README.md` — user-facing docs. Currently describes old stream-sink approach — **needs rewrite** once plugin path picked.

## Architecture (see DECISION.md for full reasoning)
Four options considered: (A) vendor scrcpy source + link, (B) spawn scrcpy subprocess + pipe, (C) run scrcpy standalone + OBS Media Source on TCP (current stream-sink scripts), (D) upstream `libscrcpy` C API.

D is dead (rom1v won't do the refactor — scrcpy GH issue #3498 closed as not planned).
**Option B chosen** (2026-04-16). Plugin spawns scrcpy subprocess, reads MPEG-TS over loopback TCP, decodes via OBS-provided FFmpeg libs, feeds `obs_source_output_video()`. License clean (plugin = GPL-2.0-or-later, scrcpy shipped as separate binary under Apache-2.0). Upstream scrcpy features flow in via CLI flags — low maintenance.

## Licensing
- Plugin: **GPL-2.0-or-later** (matches libobs).
- scrcpy: Apache-2.0, shipped as separate binary, not linked.
- Subprocess boundary keeps them separate works — no combined-license entanglement.
- adb: bundled on Windows (matching scrcpy upstream's posture). Linux/macOS use system package.

## Build requirements (Windows)
- Visual Studio 2022 (MSVC v143) — primary OBS plugin toolchain
- CMake ≥ 3.28
- OBS Studio 31.1.1 headers (fetched by buildspec.json via obs-deps)
- Qt 6 (bundled via obs-deps)
- MSYS2 at `C:\msys64` — available for building scrcpy client if Option A/B chosen (`meson`, `SDL2`, `ffmpeg`, `libusb` from MINGW64)
- ADB binary — not bundled yet, see DECISION.md

## Commands
- `git submodule update --init --recursive` after fresh clone.
- Build (Windows, from plugin repo root):
  ```powershell
  cmake --preset windows-x64
  cmake --build --preset windows-x64
  ```
- Build plugintemplate-style presets: see `CMakePresets.json`.
- Build scrcpy subprocess binary (separate, in `scrcpy/`):
  ```bash
  # MSYS2 MINGW64 shell
  cd scrcpy && meson setup builddir --buildtype=release -Dcompile_server=false \
    && ninja -C builddir
  ```

## Useful upstream refs
- OBS plugin template: https://github.com/obsproject/obs-plugintemplate
- DistroAV (NDI → OBS plugin, architectural reference): https://github.com/DistroAV/DistroAV
- scrcpy source modules of interest: `app/src/demuxer.c`, `app/src/decoder.c`, `app/src/adb/`, `app/src/server.c`
- Stream-sink PR that prototype used: https://github.com/Genymobile/scrcpy/pull/6721

## Conventions
- Windows paths: forward slashes in bash, backslashes only in PowerShell.
- Don't touch files under `scrcpy/` — submodule, pinned tag.
- Keep plugin sources in `src/`, one source type per file when added (`scrcpy-source.c`, etc.).
