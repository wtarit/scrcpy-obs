# Architecture Decision Record — scrcpy-obs

## Problem

Integrate scrcpy's Android screen capture into OBS Studio without the user having to run scrcpy as a separate window and use a lossy screen capture source. Target UX: pick "Android (scrcpy)" in OBS → Add Source → stream appears.

## Reference: how DistroAV does it

DistroAV (NDI plugin for OBS) is the closest architectural analogue. Investigated via `src/ndi-source.cpp`:

1. Plugin is an in-process `.dll`/`.so` loaded by OBS.
2. Plugin links against the NDI Runtime (`Processing.NDI.Lib.dll`) — the NDI SDK is a real C library.
3. Worker thread calls `ndiLib->recv_capture_v3(recv, &video, &audio, nullptr, 100)`.
4. NDI runtime owns the network I/O and hands back a buffer pointer (`p_data`).
5. Plugin wraps the pointer in an OBS frame struct and calls `obs_source_output_video(source, &frame)` — same address space, zero copies.

There is no localhost socket between NDI runtime and OBS. The NDI-only network I/O is between the runtime and the remote NDI sender.

This pattern works because NDI ships a stable C API. scrcpy does not.

## Options

### Option A — Vendor scrcpy source into the plugin
Copy scrcpy's C client modules (`demuxer`, `decoder`, `adb/`, `server.c`) into the plugin, replace the SDL display sink with an `obs_source_output_video()` sink, link against OBS-provided FFmpeg libs.

- **Pros:** Tight integration. Feature parity with scrcpy (input injection, resolution control, audio, camera). In-process, fast.
- **Cons:**
  - Must rebase vendored source on every upstream release — user pays release lag.
  - **License conflict:** scrcpy is Apache-2.0; libobs is GPL-2.0-or-later. Apache-2.0 is incompatible with GPL-2.0-only but is compatible with GPL-3.0. Plugin must license as **GPL-3.0-or-later** and include both license texts.
  - Larger code surface = more maintenance.

### Option B — Plugin spawns scrcpy as a subprocess
Plugin becomes a thin wrapper. On source activation, fork `scrcpy.exe` (or a scrcpy fork with a raw-frame output mode) and read frames over a pipe / localhost socket / named pipe.

- **Pros:**
  - **License clean:** subprocess boundary means scrcpy and plugin are separate programs, not a combined work. Plugin can stay GPL-2.0-or-later matching libobs. (Arguably the FSF view is stricter, but spawning a standalone program over a defined IPC is the textbook "aggregate" case.)
  - Upstream scrcpy updates land free — no rebase.
  - Minimal plugin code to maintain.
- **Cons:**
  - Extra process lifecycle to manage (crash recovery, clean shutdown on OBS exit, stderr plumbing for logs).
  - IPC overhead (one extra copy of video frames — small at typical Android resolutions).
  - Requires either a scrcpy CLI mode that emits raw frames to stdout/socket, or accepting encoded H.264 over pipe and decoding in the plugin. Current upstream scrcpy does not expose a stable raw-pipe mode; stream-sink PR #6721 adds an MPEG-TS-over-TCP sink that we could piggyback on.
  - Input injection (touch from OBS preview) needs a separate IPC channel back to scrcpy.

### Option C — Run scrcpy standalone, OBS Media Source on TCP
User runs `scrcpy --stream-sink tcp://…`. OBS picks it up via built-in Media Source. No plugin.

- **Pros:** Zero plugin code. Works today with PR #6721. Already prototyped — see `scripts/` and old `README.md`.
- **Cons:** Poor UX — user juggles two apps. No OBS-native source type. No touch injection. Lives or dies by PR #6721 landing upstream.

### Option D — Upstream `libscrcpy` C API
Ask scrcpy to expose a stable C API. Plugin then links against it like DistroAV links NDI.

- **Pros:** Ideal architecture if it existed.
- **Cons:** **Dead.** GH issues confirm maintainer (rom1v) won't do the refactor on free time:
  - [#3498 "A library in scrcpy for clients is wanted"](https://github.com/Genymobile/scrcpy/issues/3498) — closed, not planned. rom1v: *"Ideally, I'd like scrcpy to be exposed as a library... But that requires a lot of work, that I cannot do on my free time."*
  - [#1355 "Creating libscrcpy"](https://github.com/Genymobile/scrcpy/issues/1355) — open since 2020, no maintainer engagement.
  - [#3728 "Adding a server interface library"](https://github.com/Genymobile/scrcpy/issues/3728) — no maintainer response.
  - [#6219 "Embedding scrcpy in Qt 6 app"](https://github.com/genymobile/scrcpy/issues/6219) — closed, no lib exposed.
  - [#237 "Want to embed scrcpy in .net"](https://github.com/Genymobile/scrcpy/issues/237) — 2018, still no lib.
  - Six years of asks, zero movement. Not coming.

## Decision

**Option B (subprocess wrapper) — confirmed 2026-04-16.**

Rationale:
1. License cleanliness is decisive. Option A drags the plugin to GPL-3.0 and couples it to an Apache-2.0 upstream's release cadence.
2. Feature lag is the top concern the user raised. Option B eliminates it — when scrcpy adds camera support, front camera, audio improvements, the subprocess gets them for free.
3. Option C is a regression in UX compared to a real plugin.
4. Option D is unavailable.

Resolved:
- **IPC format:** MPEG-TS over loopback TCP (ephemeral port, bind `127.0.0.1:0`, retry on `EADDRINUSE`). Path of least resistance with PR #6721. Revisit named pipes / Unix sockets only if Windows firewall prompts annoy users.
- **Binary shipping:** bundle `scrcpy` + `scrcpy-server.jar` alongside the plugin `.dll`. Windows also bundles `adb.exe`; Linux/macOS use system-packaged `adb`.
- **Control scope:** v1 = view-only (source configuration: display/camera, resolution, bitrate, codec — all via scrcpy CLI flags). v2 = live touch/keyboard via scrcpy's control socket if user demand materializes.

## Bundling scrcpy and ADB

### scrcpy binary
- **Recommendation:** ship a `scrcpy.exe` alongside the plugin `.dll`, matching the submodule-pinned version. User never installs scrcpy separately.
- scrcpy license is Apache-2.0 — redistribution permitted with attribution (NOTICE file + LICENSE shipped in plugin data dir).
- Update cadence: tag-per-scrcpy-release. `git submodule update` → rebuild → release.

### `scrcpy-server.jar`
- Required on every run. scrcpy client pushes it to `/data/local/tmp/` on the device via ADB.
- Version-locked to the scrcpy client. Ship it alongside the scrcpy binary. Both covered by Apache-2.0.

### ADB binary
Research results:
- Google's Android SDK Terms prohibit redistribution of the SDK as a package, but the platform-tools are downloadable as a standalone ZIP. Strict reading: redistribution is restricted. Pragmatic reading: every scrcpy-for-Windows release ships `adb.exe` and nobody has been sued.
- Upstream scrcpy's own Windows release bundles `adb.exe` — precedent established for this exact use case.

**Recommendation:** ship `adb.exe` bundled with the plugin on Windows. Match scrcpy's approach. Document the source (Google platform-tools, specific version) in the plugin's about dialog. If legal caution matters more than UX, fall back to PATH lookup with a clear error message pointing users at `https://developer.android.com/tools/releases/platform-tools`.

- Linux: use distro-packaged `adb` (`android-tools` / `adb` package). Don't bundle.
- macOS: fetch via Homebrew (`brew install android-platform-tools`). Don't bundle.

Versioning note: ADB is strict about client/server version match. If the user already has `adb.exe` running (Android Studio, other tooling), the bundled one will either attach to the existing server or fail with a version mismatch. Worth calling out in the README.

## Tooling required

For **Option B** (current lean):
- **Visual Studio 2022** with C++ workload — OBS plugin builds with MSVC on Windows.
- **CMake ≥ 3.28** (bundled with VS 2022).
- **OBS Studio 31.1.1** installed (for runtime testing) + headers via `buildspec.json` → obs-deps.
- **Qt 6** — pulled by buildspec.json automatically from obs-deps. Only needed if the plugin grows UI beyond the default OBS properties panel.
- **MSYS2 MINGW64** at `C:\msys64` (already installed) — used only for building the scrcpy subprocess binary if we want to ship a custom build. Packages:
  ```
  pacman -S mingw-w64-x86_64-meson mingw-w64-x86_64-ninja \
            mingw-w64-x86_64-SDL2 mingw-w64-x86_64-ffmpeg \
            mingw-w64-x86_64-libusb
  ```
- **Java JDK 17+** and **Android SDK / platform-33+** — only needed to rebuild `scrcpy-server.jar`. The scrcpy GitHub Releases ship a prebuilt jar; use that unless you're modifying the server.
- **ADB** (platform-tools) — for manual device testing during dev.

For **Option A** (if reconsidered): same as B, plus linking against OBS-provided `libavcodec`/`libavformat`/`libavutil`/`libswscale` inside the plugin.

## scrcpy fork maintenance

Fork lives at https://github.com/wtarit/scrcpy (created 2026-04-16).
Submodule in this repo points at the fork; upstream `Genymobile/scrcpy` is a secondary remote inside the submodule checkout for pulling new releases.

### Branch / tag convention

```
fork master  ← tracks upstream master (never commit here)
fork tags v3.3.4, v3.3.5, …  ← copied from upstream
fork branch streamsink/v3.3.4  ← v3.3.4 + PR #6721 cherry-picks
fork tag    v3.3.4-streamsink.1  ← what the submodule pins
```

Suffix `.1 / .2 / …` increments for fixes to the streamsink patch at the same upstream version.

### Creating a streamsink branch for a new upstream release

```bash
cd scrcpy   # submodule checkout
git fetch upstream --tags
git fetch upstream pull/6721/head:pr-6721
git checkout -b streamsink/vX.Y.Z vX.Y.Z
git cherry-pick vX.Y.Z..pr-6721       # adjust if PR rebased
# resolve conflicts (PR mostly adds new files, conflicts rare)
git tag vX.Y.Z-streamsink.1 -m "scrcpy vX.Y.Z + stream-sink PR #6721"
git push origin streamsink/vX.Y.Z vX.Y.Z-streamsink.1

# bump submodule in plugin repo
cd ..
git add scrcpy
git commit -m "deps: bump scrcpy fork to vX.Y.Z-streamsink.1"
```

### Kill switch — PR #6721 merges upstream

Drop streamsink branches entirely, point submodule at stock upstream tag, celebrate.

## Historical note

Before this repo was restructured as an OBS plugin, it shipped shell scripts that ran a scrcpy binary with PR #6721 applied and exposed an MPEG-TS TCP stream for OBS's built-in Media Source (Option C). Those scripts were deleted on 2026-04-16 when Option B was picked — the plugin subsumes the same data path internally.
