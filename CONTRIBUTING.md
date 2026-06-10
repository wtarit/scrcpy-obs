# Contributing

Developer guide for building, formatting, and testing scrcpy-obs.

## Architecture

The plugin spawns a patched scrcpy subprocess per source instance. scrcpy tees the raw H.264 packet stream to a loopback TCP port; the plugin parses packets, feeds NAL units to libavcodec, and pushes decoded frames into OBS through `obs_source_output_video()`.

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

- **Plugin:** GPL-2.0-or-later (matches libobs).
- **scrcpy:** Apache-2.0, shipped as a separate binary (not linked). The subprocess boundary keeps licenses separate.
- **adb:** bundled on Windows. Linux/macOS builds use the system package.
- No `libavformat` — raw packet framing is parsed directly in `scrcpy-reader.c` (CONFIG buffer + prepend pattern from scrcpy's `sc_packet_merger`).

## Repo layout

| Path                    | Purpose                                                                                                                  |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `src/plugin-main.c`     | Module entry, registers `scrcpy_source_info`                                                                             |
| `src/scrcpy-source.c`   | OBS source: properties, port, subprocess lifecycle                                                                       |
| `src/scrcpy-process.c`  | Cross-platform scrcpy subprocess spawn                                                                                   |
| `src/scrcpy-reader.c`   | TCP reader, packet merger, avcodec decode, frame output                                                                  |
| `data/locale/en-US.ini` | i18n strings                                                                                                             |
| `data/bin/`             | Bundled `scrcpy.exe`, `scrcpy-server`, DLLs (gitignored; populated by CI or local build)                                 |
| `tests/`                | pytest suite — see [tests/README.md](tests/README.md)                                                                    |
| `scrcpy/`               | **Git submodule** (fork: `wtarit/scrcpy`, tag `vX.Y.Z-rawstream.N`). Do not edit in place — changes go through the fork. |

## Build requirements (Windows)

- Visual Studio 2022 (MSVC v143)
- CMake ≥ 3.28
- OBS Studio 31.1.1 headers (fetched by `buildspec.json` via obs-deps)
- Qt 6 (bundled via obs-deps)
- MSYS2 at `C:\msys64` — packages: `mingw-w64-x86_64-meson mingw-w64-x86_64-ninja mingw-w64-x86_64-sdl3 mingw-w64-x86_64-ffmpeg mingw-w64-x86_64-libusb mingw-w64-x86_64-gcc` (scrcpy ≥ 4.0 requires SDL3 + FFmpeg ≥ 8.1)
- `gh` CLI on PATH

Also see [scrcpy's build guide](https://github.com/Genymobile/scrcpy/blob/master/doc/build.md) and the [OBS plugin template quick start](https://github.com/obsproject/obs-plugintemplate/wiki/Quick-Start-Guide).

## Build from source

### 1. Clone

```bash
git clone git@github.com:wtarit/scrcpy-obs.git
cd scrcpy-obs
git submodule update --init --recursive
```

### 2. Build the scrcpy subprocess binary (MSYS2 MINGW64 shell)

```bash
cd scrcpy
meson setup builddir --buildtype=release -Dcompile_server=false -Dportable=true
ninja -C builddir
cd ..
```

Use `-Dportable=true` so scrcpy finds `scrcpy-server` next to the executable.

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

Restart OBS. Dev install dir: `C:\ProgramData\obs-studio\plugins\scrcpy-obs\`. OBS ignores the AppData copy if the ProgramData one exists.

## Formatting

CI checks formatting (`.github/workflows/check-format.yaml`).

- **clang-format** for C sources (`src/*.c`, `src/*.h`)
- **gersemi** for CMake (`CMakeLists.txt`)

Install clang-format (Windows):

```powershell
winget install -e --id LLVM.ClangFormat
```

Format the codebase:

```powershell
Get-ChildItem src -Recurse -Include *.c,*.h | ForEach-Object { clang-format -i $_.FullName }
uvx gersemi@0.21.0 -i .\cmake\ .\CMakeLists.txt
```

## Testing

See [tests/README.md](tests/README.md).
