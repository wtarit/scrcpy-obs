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
- `cmake/`, `.github/`, `build-aux/` — build helpers and CI from obs-plugintemplate (unmodified)
- `scrcpy/` — **git submodule**, pinned to `v3.3.4`. Points at fork `https://github.com/wtarit/scrcpy` (origin) with Genymobile upstream as secondary remote. Used for building the scrcpy subprocess binary that ships with the plugin. Once PR #6721 is cherry-picked on a `streamsink/vX.Y.Z` branch in the fork, submodule moves to that tag. Do not edit source files in place — go through the fork.
- `README.md` — user-facing docs (Option B architecture)

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
- MSYS2 at `C:\msys64` — packages confirmed installed (2026-04-16): `mingw-w64-x86_64-meson mingw-w64-x86_64-ninja mingw-w64-x86_64-SDL2 mingw-w64-x86_64-ffmpeg mingw-w64-x86_64-libusb mingw-w64-x86_64-gcc`
- `gh` CLI on PATH (v2.89.0, `/c/Program Files/GitHub CLI/gh`) — invoke as `gh` directly
- ADB binary — bundled at release time (see DECISION.md § Bundling)

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
- Branches: `master` = template baseline, `dev/prototype` = active dev. PRs target `dev/prototype` for now.
- Remote: `git@github.com:wtarit/scrcpy-obs.git` (SSH).

## Next implementation steps (resume here)

Ordered by dependency. Skip any that have since been done — check git log.

1. **Fork prep — streamsink branch.** In `scrcpy/` submodule:
   ```bash
   git fetch upstream --tags
   git fetch upstream pull/6721/head:pr-6721
   git checkout -b streamsink/v3.3.4 v3.3.4
   git cherry-pick v3.3.4..pr-6721    # resolve conflicts if any
   git tag v3.3.4-streamsink.1 -m "scrcpy v3.3.4 + PR #6721"
   git push origin streamsink/v3.3.4 v3.3.4-streamsink.1
   ```
   Then bump plugin submodule: `cd scrcpy && git checkout v3.3.4-streamsink.1 && cd .. && git add scrcpy && git commit -m "deps: pin scrcpy to v3.3.4-streamsink.1"`.

2. **Build scrcpy binary** from MSYS2 MINGW64:
   ```bash
   cd scrcpy && meson setup builddir --buildtype=release -Dcompile_server=false && ninja -C builddir
   ```
   Confirm `builddir/app/scrcpy.exe` runs with `--stream-sink=tcp://127.0.0.1:1234`.

3. **Source type skeleton** — `src/scrcpy-source.c`:
   - Register via `obs_register_source(&scrcpy_source_info)`.
   - Properties: device serial dropdown (populated via `adb devices`), video source (display/camera), camera-id, max-size, bitrate, codec, audio toggle.
   - `create` callback: pick ephemeral port (`bind 127.0.0.1:0` + `getsockname` + close + retry-on-`EADDRINUSE`), spawn scrcpy child with matching `--stream-sink=tcp://127.0.0.1:<port>` and other flags from properties.
   - `destroy` callback: signal child, wait, close sockets.

4. **Cross-platform process spawn** — `src/scrcpy-process.{h,c}`:
   - Windows: `CreateProcessW` + job object to auto-kill child on plugin unload.
   - POSIX: `posix_spawn` + `prctl(PR_SET_PDEATHSIG)` on Linux, `kqueue EVFILT_PROC` on macOS.
   - Abstraction: single `scrcpy_proc_t` handle + `scrcpy_proc_spawn/kill/wait`.

5. **MPEG-TS demux + decode** — `src/scrcpy-demuxer.c`:
   - Connect to scrcpy's TCP sink via `libavformat` (`avformat_open_input` with `tcp://127.0.0.1:<port>` + options `nobuffer`, `analyzeduration=0`, `probesize=32`).
   - `libavcodec` decode H.264/H.265/AV1 → `AVFrame`.
   - `sws_scale` to OBS-native format (NV12 or I420) → `obs_source_output_video(source, &obs_frame)`.
   - Run in dedicated thread; clean shutdown on `destroy`.

6. **Link FFmpeg** — CMakeLists.txt:
   - `find_package(FFmpeg COMPONENTS avformat avcodec avutil swscale REQUIRED)` (obs-deps ships these).
   - `target_link_libraries(${CMAKE_PROJECT_NAME} PRIVATE FFmpeg::avformat FFmpeg::avcodec FFmpeg::avutil FFmpeg::swscale)`.

7. **Bundling** — modify `.github/scripts/Package-Windows.ps1` (and macos/ubuntu equivalents):
   - Build scrcpy binary in CI per platform.
   - Bundle `scrcpy`, `scrcpy-server.jar`, `adb.exe` (Win only) into plugin release zip under `bin/`.
   - Plugin resolves binary path via `obs_get_module_data_path()` → `<plugin-data>/bin/scrcpy{,.exe}`.

8. **CI matrix** — verify `.github/workflows/build-project.yaml` builds all 3 platforms. Add scrcpy build step before packaging.

9. **Kill remaining template cruft** — confirm `src/plugin-support.{h,c.in}` are wired correctly (they auto-configure via `cmake/common/helpers_common.cmake`, no manual target_sources needed).

10. **Smoke test** — load plugin in OBS 31.1.1+, verify "Android (scrcpy)" appears in source menu. Add Android device, confirm video feed.
