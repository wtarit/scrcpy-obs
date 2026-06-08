# scrcpy-obs

OBS Studio plugin that adds **Android (scrcpy)** as a native source. Mirror an Android device straight into OBS over ADB — no window capture, no display mirror, no virtual camera driver.

> **Status:** pre-alpha, active development on `dev/rawstream`.

## Architecture

Plugin spawns a patched scrcpy subprocess per source instance. scrcpy tees the raw H.264 packet stream to a loopback TCP port; the plugin parses packets, feeds NAL units to libavcodec, and pushes decoded frames into OBS through `obs_source_output_video()`.

Full reasoning in [`DECISION.md`](./DECISION.md). Context map in [`AGENTS.md`](./AGENTS.md).

```
Android                     Plugin process (in OBS)
+--------------+           +-------------------------------+
| scrcpy-server| --ADB---> | scrcpy.exe (patched)          |
| (MediaCodec) |           |   --raw-video-tcp=<port>      |
+--------------+           +-------------+-----------------+
                                         | raw H.264 packets
                                         | [pts:u64|flags:u8|size:u32|NAL]
                                         v
                           +-------------------------------+
                           | scrcpy-obs plugin             |
                           |   packet merge + avcodec      |
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
- Android device with USB debugging enabled

## Repo layout

```
scrcpy-obs/
├── CMakeLists.txt          OBS plugin build
├── buildspec.json          OBS plugin dependency manifest
├── src/
│   └── plugin-main.c       module entry (stub)
├── data/locale/            i18n strings
├── cmake/                  CMake helpers
├── tests/                  pytest test suite (uv-managed)
│   ├── pyproject.toml
│   ├── conftest.py
│   ├── e2e/                OBS WebSocket end-to-end tests
│   └── wire/               raw H.264 wire-protocol tests
├── scrcpy/                 git submodule → wtarit/scrcpy fork
├── AGENTS.md               project context for coding agents
├── DECISION.md             architecture decision record
└── README.md               this file
```

## Build

### 1. Clone

```bash
git clone git@github.com:wtarit/scrcpy-obs.git
cd scrcpy-obs
git submodule update --init --recursive
```

### 2. Build the scrcpy subprocess binary (MSYS2 MINGW64 shell)

```bash
cd scrcpy
meson setup builddir --buildtype=release -Dcompile_server=false
ninja -C builddir
cd ..
```

Output: `scrcpy/builddir/app/scrcpy.exe` + DLLs. Copy these (plus `scrcpy-server`) into `data/bin/` before building the plugin, or the install step will fail.

### 3. Build the OBS plugin (PowerShell / Developer Command Prompt)

```powershell
cmake --preset windows-x64
cmake --build --preset windows-x64
```

### 4. Install to OBS

```powershell
cmake --install build_x64 --config RelWithDebInfo
```

Restart OBS after install. The source appears as **Android (scrcpy)** in the Add Source menu.

## Formatting

- **clang-format** for C sources (`src/*.c`, `src/*.h`)
- **gersemi** for CMake (`CMakeLists.txt`)

### clang-format (Windows)

Install via winget

```powershell
winget install -e --id LLVM.ClangFormat
```

### gersemi

Run with `uvx`

### Format the codebase

```powershell
Get-ChildItem src -Recurse -Include *.c,*.h | ForEach-Object { clang-format -i $_.FullName }
uvx gersemi@0.21.0 -i CMakeLists.txt
```

## Licensing

- Plugin: **GPL-2.0-or-later** (matching libobs).
- scrcpy (Apache-2.0) is shipped as a **separate binary**, not linked into the plugin — so the two remain separate works under their own licenses. See `DECISION.md` § Licensing for full reasoning.

## Testing

Test suite lives in `tests/`, managed by [uv](https://docs.astral.sh/uv/).

```bash
cd tests
uv sync          # first time: creates .venv and installs deps
```

**Wire tests** — validate raw H.264 packet stream from patched scrcpy. Requires device + `data/bin/` populated:

```bash
# auto-detects ADB device; or set ADB_SERIAL=<serial>
uv run pytest wire/ -v
```

**E2E tests** — validate full pipeline through OBS. Requires OBS running with WebSocket enabled (Tools → WebSocket Server Settings, port 4455):

```bash
OBS_PASSWORD=<your-password> ADB_SERIAL=<serial> uv run pytest e2e/ -v
```

Environment variables:

| Variable         | Default         | Description                                   |
| ---------------- | --------------- | --------------------------------------------- |
| `OBS_HOST`       | `127.0.0.1`     | OBS WebSocket host                            |
| `OBS_PORT`       | `4455`          | OBS WebSocket port                            |
| `OBS_PASSWORD`   | _(empty)_       | OBS WebSocket password                        |
| `ADB_SERIAL`     | `emulator-5554` | ADB device serial                             |
| `SCRCPY_BIN_DIR` | `data/bin`      | Directory with `scrcpy.exe` + `scrcpy-server` |

## ADB resolution

Both the plugin (device list dropdown) and scrcpy itself resolve `adb` in the same order:

1. `$ADB` environment variable — set to a full path to override
2. Bundled `adb.exe` in `data/bin/` (ships with the plugin)
3. `adb` on system `PATH`

Normal users never need to configure anything. Set `$ADB` only if you need a specific ADB version (e.g. enterprise MDM builds).

## Potential improvements

- **CI dep caching** — Windows CI job downloads OBS source, prebuilt obs-deps, and Qt6 on every run (~several GB). Adding `actions/cache` keyed on `buildspec.json` dep versions would skip re-download when deps haven't changed. macOS/Linux already cache compiler output (`.ccache`); Windows has no cache at all.

## See also

- [scrcpy](https://github.com/Genymobile/scrcpy) — upstream project
- [obs-plugintemplate](https://github.com/obsproject/obs-plugintemplate) — template this plugin is based on
- [DistroAV](https://github.com/DistroAV/DistroAV) — NDI-for-OBS plugin, architectural reference
- [stream-sink PR #6721](https://github.com/Genymobile/scrcpy/pull/6721) — scrcpy PR used for MPEG-TS output
