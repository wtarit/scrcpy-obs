# scrcpy-obs — Claude Context

## What this repo is
OBS Studio plugin that adds "Android (scrcpy)" as a native OBS source. Under the hood it uses [scrcpy](https://github.com/Genymobile/scrcpy) to capture Android screens over ADB — no display mirroring, no window capture, direct MediaCodec H.264 → decoded frame → OBS source.

Target platform: Windows first (user's primary OS). Linux/macOS later.

## Current status
Pre-alpha. **Pivot 2026-04-17:** abandoning the stream-sink (MPEG-TS over TCP via PR #6721) path. The PR is large, the MPEG-TS container is overkill for a loopback stream, and the sync-on-first-IDR problem stems from treating a stateful codec stream like a file. Replacing with a minimal scrcpy fork patch that tees the server→client raw H.264 packet protocol (12-byte header + NAL) to a TCP port; plugin parses those packets directly and feeds `avcodec`. See `DECISION.md` § *Revision 2026-04-17*.

### What's reusable from the prototype
- `src/scrcpy-process.c` — cross-platform spawn (keep as-is).
- `src/scrcpy-source.c` — OBS source-type skeleton, properties, ephemeral port (keep; CLI flags for scrcpy child change).
- `CMakeLists.txt` FFmpeg link (keep `libavcodec`, `libavutil`, `libswscale`; drop `libavformat` — not needed for raw packet input).
- scrcpy subprocess spawn + `data/bin/` bundling layout.

### What's being dropped
- `src/scrcpy-demuxer.c` — MPEG-TS demux via `avformat_open_input`. Replace with `src/scrcpy-reader.c` that reads `[pts:u64 | flags:u8 | size:u32]` headers and feeds NAL units to `avcodec_send_packet`.
- scrcpy fork branch `streamsink/v3.3.4` + tag `v3.3.4-streamsink.1`. Replace with `rawstream/v3.3.4` + tag `v3.3.4-rawstream.1`.
- stream-sink PR #6721 cherry-pick (no longer needed).

## Repo layout
- `CMakeLists.txt`, `buildspec.json` — OBS plugin build (based on `obsproject/obs-plugintemplate`)
- `src/plugin-main.c` — module entry, registers `scrcpy_source_info`
- `data/locale/en-US.ini` — i18n strings
- `cmake/`, `.github/`, `build-aux/` — build helpers and CI from obs-plugintemplate (unmodified)
- `scrcpy/` — **git submodule**. Points at fork `https://github.com/wtarit/scrcpy` (origin) with Genymobile upstream as secondary remote. Used for building the scrcpy subprocess binary that ships with the plugin. The fork carries a small patch on branch `rawstream/vX.Y.Z` (tagged `vX.Y.Z-rawstream.N`) that forwards the server→client video packet stream verbatim to a TCP port. Submodule pins that tag. Do not edit source files in place — go through the fork.
- `README.md` — user-facing docs (Option B architecture)

## Architecture (see DECISION.md for full reasoning)
Four options considered: (A) vendor scrcpy source + link, (B) spawn scrcpy subprocess + pipe, (C) run scrcpy standalone + OBS Media Source on TCP, (D) upstream `libscrcpy` C API. D is dead (scrcpy GH issue #3498, not planned).

**Option B chosen** (2026-04-16), **refined 2026-04-17**. Plugin spawns patched scrcpy subprocess; subprocess forwards the scrcpy server→client raw H.264 packet stream (12-byte header + NAL, unchanged) to a loopback TCP port. Plugin parses packet headers, feeds NAL units straight to `libavcodec`, emits frames via `obs_source_output_video()`. No MPEG-TS container, no `libavformat`. License clean (plugin GPL-2.0-or-later, scrcpy shipped as separate Apache-2.0 binary). Fork patch is small enough (~tens of LOC, one new CLI flag + a packet tee) to rebase on each scrcpy release with minimal effort.

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

Prototype (steps 1–6) delivered the process-spawn + source-type skeleton but committed to the stream-sink path. We're resetting that path (see DECISION.md § *Revision 2026-04-17*). Upcoming work:

1. **Author scrcpy fork patch** on `rawstream/v3.3.4`.
   - Add CLI flag, e.g. `--raw-video-tcp=PORT` (listens on `127.0.0.1:PORT`, accepts one client, blocks until connected).
   - In the existing server→client video packet loop, after the packet has been read from the adb socket, write the same bytes (`[pts:u64 BE | flags:u8 | size:u32 BE | NAL]`) to the accepted TCP client. Do not decode, do not mux.
   - Skip the local display sink when the flag is set (stdout stays for logs).
   - Tag `v3.3.4-rawstream.1`, push fork, move submodule pointer.
   - Reference: `app/src/demuxer.c` already parses that exact header — the patch is a tee in the same spot.

2. **Rebuild scrcpy subprocess binary** from new tag (`cd scrcpy && meson setup builddir --buildtype=release -Dcompile_server=false && ninja -C builddir`), reinstall `scrcpy.exe` to `data/bin/`.

3. **Replace `src/scrcpy-demuxer.c`** with `src/scrcpy-reader.c`:
   - Open `connect()`-style TCP socket to the scrcpy child's port (retry until accepted, scrcpy may need a moment to bind).
   - Loop: read 13 bytes (header), read `size` bytes (NAL), build `AVPacket` with PTS from header, set `AV_PKT_FLAG_KEY` if keyframe flag set, `avcodec_send_packet`, drain with `avcodec_receive_frame`, convert YUV→I420 via `sws_scale`, call `obs_source_output_video()`.
   - First header with the "config" flag carries SPS/PPS — hand to `avcodec_parameters_from_context` or prepend to extradata before the first `avcodec_open2`. (scrcpy emits config packet before the first IDR, so mid-stream sync problem from the stream-sink approach disappears.)
   - No `avformat`, no retry-on-IDR dance, no `avcodec_flush_buffers` workaround.

4. **Update `src/scrcpy-source.c`** to pass the new `--raw-video-tcp` flag to the subprocess instead of the stream-sink flag.

5. **Update `CMakeLists.txt`** — drop `libavformat` from `target_link_libraries`.

6. **Smoke test** — OBS + `emulator-5554`, verify frames reach the preview. Validate via OBS WebSocket (`GetSourceScreenshot` on port 4455) or visual.

7. **Bundling + CI** (same as before): `.github/scripts/Package-Windows.ps1` builds the patched scrcpy in CI, ships `scrcpy.exe` + `scrcpy-server.jar` + `adb.exe` + DLLs into `data/bin/`. Verify `.github/workflows/build-project.yaml` matrix across 3 platforms.

8. **Fork maintenance doc** in DECISION.md — replace `streamsink/*` branch convention with `rawstream/*`. (Done in this revision.)
