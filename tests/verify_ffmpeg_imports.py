#!/usr/bin/env python3
"""Check that a Windows OBS plugin's FFmpeg DLL imports exist in its OBS runtime."""

from __future__ import annotations

import argparse
import re
import struct
import sys
from pathlib import Path


def _read_u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _read_u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def pe_imports(image_path: Path) -> set[str]:
    """Return imported DLL names from a PE image using only the Python stdlib."""
    data = image_path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError(f"{image_path} is not a Windows PE image")

    pe_offset = _read_u32(data, 0x3C)
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError(f"{image_path} has no PE signature")

    file_header = pe_offset + 4
    section_count = _read_u16(data, file_header + 2)
    optional_size = _read_u16(data, file_header + 16)
    optional_header = file_header + 20
    magic = _read_u16(data, optional_header)
    if magic == 0x20B:  # PE32+
        data_directory_offset = optional_header + 112
    elif magic == 0x10B:  # PE32
        data_directory_offset = optional_header + 96
    else:
        raise ValueError(f"{image_path} has unsupported optional-header magic 0x{magic:x}")

    import_rva = _read_u32(data, data_directory_offset + 8)
    if import_rva == 0:
        return set()

    section_table = optional_header + optional_size
    sections: list[tuple[int, int, int]] = []
    for index in range(section_count):
        section = section_table + 40 * index
        virtual_size = _read_u32(data, section + 8)
        virtual_address = _read_u32(data, section + 12)
        raw_size = _read_u32(data, section + 16)
        raw_offset = _read_u32(data, section + 20)
        sections.append((virtual_address, max(virtual_size, raw_size), raw_offset))

    def rva_to_offset(rva: int) -> int:
        for virtual_address, span, raw_offset in sections:
            if virtual_address <= rva < virtual_address + span:
                return raw_offset + rva - virtual_address
        if rva < len(data):
            return rva
        raise ValueError(f"{image_path} contains an unmapped PE RVA 0x{rva:x}")

    descriptor = rva_to_offset(import_rva)
    imports: set[str] = set()
    for index in range(4096):
        entry = descriptor + 20 * index
        name_rva = _read_u32(data, entry + 12)
        if name_rva == 0:
            break
        name_offset = rva_to_offset(name_rva)
        end = data.find(b"\0", name_offset)
        if end < 0:
            raise ValueError(f"{image_path} contains an unterminated import name")
        imports.add(data[name_offset:end].decode("ascii").lower())
    else:
        raise ValueError(f"{image_path} contains an unterminated import table")

    return imports


def verify_ffmpeg_imports(plugin_path: Path, runtime_dir: Path) -> list[str]:
    imports = pe_imports(plugin_path)
    ffmpeg_imports = sorted(
        name
        for name in imports
        if re.fullmatch(r"(?:avcodec|avutil)-\d+\.dll", name)
    )
    if not ffmpeg_imports:
        raise ValueError(f"{plugin_path} imports no versioned avcodec/avutil DLLs")

    missing = [name for name in ffmpeg_imports if not (runtime_dir / name).is_file()]
    if missing:
        raise FileNotFoundError(
            "OBS runtime is missing FFmpeg DLLs imported by the plugin: "
            + ", ".join(missing)
        )
    return ffmpeg_imports


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", type=Path, required=True, help="Built OBS plugin DLL")
    parser.add_argument("--runtime-dir", type=Path, required=True, help="OBS bin/64bit directory")
    args = parser.parse_args()

    try:
        imports = verify_ffmpeg_imports(args.plugin, args.runtime_dir)
    except (OSError, ValueError, struct.error) as error:
        print(f"FFmpeg import check failed: {error}", file=sys.stderr)
        return 1

    print("FFmpeg imports available in OBS runtime: " + ", ".join(imports))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
