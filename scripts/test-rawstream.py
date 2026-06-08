"""End-to-end smoke test for the rawstream scrcpy fork patch.

Spawns patched scrcpy (--raw-video-tcp=PORT), connects a TCP client, parses
the 12-byte prelude and per-packet headers, and pipes the NAL bytes to
ffplay so you can eyeball the device screen.

Usage:
    python scripts/test-rawstream.py [--serial DEVICE] [--max-size N]
                                     [--bitrate 8000] [--codec h264]
                                     [--bin-dir PATH]

The bin dir must contain scrcpy.exe + scrcpy-server + ffmpeg DLLs. Default
is <repo>/data/bin (populated by installing the patched build).
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SC_PACKET_FLAG_CONFIG = 1 << 63
SC_PACKET_FLAG_KEY_FRAME = 1 << 62
SC_PACKET_PTS_MASK = SC_PACKET_FLAG_KEY_FRAME - 1


def pick_ephemeral_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError(f"scrcpy closed mid-read (wanted {n}, got {len(buf)})")
        buf += chunk
    return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", default="")
    ap.add_argument("--max-size", type=int, default=0)
    ap.add_argument("--bitrate", type=int, default=8000, help="kbps")
    ap.add_argument("--codec", default="h264", choices=["h264", "h265", "av1"])
    ap.add_argument("--bin-dir", default=str(REPO_ROOT / "data" / "bin"))
    ap.add_argument("--no-ffplay", action="store_true",
                    help="parse packets and print stats; do not launch ffplay")
    ap.add_argument("--frames", type=int, default=0,
                    help="exit after receiving N packets (0 = run forever)")
    args = ap.parse_args()

    bin_dir = Path(args.bin_dir)
    scrcpy = bin_dir / "scrcpy.exe"
    server = bin_dir / "scrcpy-server"
    if not scrcpy.exists():
        print(f"scrcpy not found at {scrcpy}", file=sys.stderr)
        return 2
    if not server.exists():
        print(f"scrcpy-server not found at {server}", file=sys.stderr)
        return 2

    port = pick_ephemeral_port()
    print(f"[test] picked port {port}")

    scrcpy_args = [
        str(scrcpy),
        "--no-window",
        "--no-audio",
        "--no-control",
        "-V", "info",
        f"--video-bit-rate={args.bitrate}K",
        f"--video-codec={args.codec}",
        # Nudge MediaCodec to emit packets even when the screen is idle so
        # ffplay keeps redrawing. Safe to keep on for testing.
        "--video-codec-options="
        "repeat-previous-frame-after-us:long=100000,"
        "i-frame-interval:int=1",
        f"--raw-video-tcp={port}",
    ]
    if args.max_size:
        scrcpy_args.append(f"--max-size={args.max_size}")
    if args.serial:
        scrcpy_args.append(f"--serial={args.serial}")

    env = os.environ.copy()
    env["SCRCPY_SERVER_PATH"] = str(server)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    print(f"[test] spawning: {' '.join(scrcpy_args)}")
    scrcpy_proc = subprocess.Popen(scrcpy_args, env=env)

    try:
        # Retry connect — scrcpy takes a moment to bind.
        deadline = time.monotonic() + 15.0
        sock = None
        while time.monotonic() < deadline:
            try:
                sock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
                break
            except (ConnectionRefusedError, socket.timeout, OSError):
                time.sleep(0.1)
        if sock is None:
            print("[test] could not connect to scrcpy --raw-video-tcp port",
                  file=sys.stderr)
            return 3

        sock.settimeout(60.0)
        print("[test] connected, reading prelude")
        prelude = recv_exact(sock, 12)
        codec_id, width, height = struct.unpack(">III", prelude)
        codec_str = codec_id.to_bytes(4, "big").decode("ascii",
                                                       errors="replace").strip("\x00")
        print(f"[test] prelude: codec=0x{codec_id:08x} ({codec_str!r}) "
              f"{width}x{height}")

        ffplay = None
        if not args.no_ffplay:
            ffplay_cmd = [
                "ffplay",
                "-hide_banner",
                "-loglevel", "warning",
                "-fflags", "nobuffer+discardcorrupt",
                "-flags", "low_delay",
                "-analyzeduration", "100000",
                "-probesize", "65536",
                "-f", args.codec,
                "-i", "pipe:0",
            ]
            print(f"[test] launching ffplay: {' '.join(ffplay_cmd)}")
            ffplay = subprocess.Popen(ffplay_cmd, stdin=subprocess.PIPE)

        total_packets = 0
        total_bytes = 0
        first_key_at = None
        t0 = time.monotonic()

        while True:
            hdr = recv_exact(sock, 12)
            pts_flags, size = struct.unpack(">QI", hdr)
            is_config = bool(pts_flags & SC_PACKET_FLAG_CONFIG)
            is_key = bool(pts_flags & SC_PACKET_FLAG_KEY_FRAME)
            pts = None if is_config else (pts_flags & SC_PACKET_PTS_MASK)
            nal = recv_exact(sock, size)

            total_packets += 1
            total_bytes += size
            if is_key and first_key_at is None:
                first_key_at = time.monotonic() - t0
                print(f"[test] first keyframe at +{first_key_at*1000:.0f} ms "
                      f"(packet #{total_packets})")

            if total_packets <= 5 or total_packets % 60 == 0:
                print(f"[test] pkt #{total_packets} "
                      f"size={size} "
                      f"{'CONFIG ' if is_config else ''}"
                      f"{'KEY ' if is_key else ''}"
                      f"pts={pts}")

            if ffplay is not None:
                try:
                    ffplay.stdin.write(nal)
                    ffplay.stdin.flush()
                except (BrokenPipeError, OSError):
                    print("[test] ffplay pipe closed; exiting")
                    break

            if args.frames and total_packets >= args.frames:
                print(f"[test] reached {args.frames} packets, stopping")
                break

        print(f"[test] read {total_packets} packets, {total_bytes} bytes")
        return 0

    finally:
        try:
            if 'sock' in locals() and sock is not None:
                sock.close()
        except Exception:
            pass
        if scrcpy_proc.poll() is None:
            scrcpy_proc.terminate()
            try:
                scrcpy_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                scrcpy_proc.kill()


if __name__ == "__main__":
    sys.exit(main())
