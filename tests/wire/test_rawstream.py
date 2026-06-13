"""Wire-protocol test: spawn patched scrcpy, parse raw H.264 packet stream.

Requires: patched scrcpy binary in SCRCPY_BIN_DIR, Android device via ADB_SERIAL.
"""
import os
import socket
import struct
import subprocess
import time
from pathlib import Path

import pytest

from conftest import ADB_SERIAL, SCRCPY_BIN_DIR

pytestmark = pytest.mark.wire

SC_PACKET_FLAG_CONFIG = 1 << 63
SC_PACKET_FLAG_KEY_FRAME = 1 << 62
SC_PACKET_PTS_MASK = SC_PACKET_FLAG_KEY_FRAME - 1

CONNECT_TIMEOUT = 15.0
FIRST_KEYFRAME_TIMEOUT = 30.0
MIN_PACKETS = 10


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise EOFError(f"connection closed (wanted {n}, got {len(buf)})")
        buf += chunk
    return bytes(buf)


@pytest.fixture
def scrcpy_proc():
    bin_dir = Path(SCRCPY_BIN_DIR)
    scrcpy = bin_dir / "scrcpy.exe"
    server = bin_dir / "scrcpy-server"

    if not scrcpy.exists():
        pytest.skip(f"scrcpy.exe not found at {scrcpy}")
    if not server.exists():
        pytest.skip(f"scrcpy-server not found at {server}")

    port = _pick_port()
    args = [
        str(scrcpy), "--no-window", "--no-audio", "--no-control",
        "-V", "info",
        "--video-bit-rate=8000K",
        "--video-codec=h264",
        "--video-codec-options=repeat-previous-frame-after-us:long=100000,i-frame-interval:int=1",
        f"--raw-video-tcp={port}",
        "--max-size=720",
    ]
    if ADB_SERIAL:
        args.append(f"--serial={ADB_SERIAL}")

    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")

    proc = subprocess.Popen(args, env=env)
    yield proc, port

    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_wire_prelude(scrcpy_proc):
    """Verify scrcpy emits valid 12-byte prelude with non-zero dimensions."""
    proc, port = scrcpy_proc

    deadline = time.monotonic() + CONNECT_TIMEOUT
    sock = None
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            break
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.1)

    assert sock is not None, "could not connect to scrcpy --raw-video-tcp port within 15s"

    with sock:
        sock.settimeout(10.0)
        prelude = _recv_exact(sock, 12)
        codec_id, width, height = struct.unpack(">III", prelude)
        assert width > 0, f"prelude width={width}"
        assert height > 0, f"prelude height={height}"
        assert codec_id != 0, "prelude codec_id=0"


def test_wire_packets(scrcpy_proc):
    """Verify stream delivers CONFIG packet then keyframe within timeout."""
    proc, port = scrcpy_proc

    deadline = time.monotonic() + CONNECT_TIMEOUT
    sock = None
    while time.monotonic() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=2.0)
            break
        except (ConnectionRefusedError, socket.timeout, OSError):
            time.sleep(0.1)

    assert sock is not None, "could not connect to scrcpy port"

    with sock:
        sock.settimeout(FIRST_KEYFRAME_TIMEOUT)
        _recv_exact(sock, 12)  # prelude

        got_config = False
        got_keyframe = False
        total = 0

        while total < MIN_PACKETS or not (got_config and got_keyframe):
            hdr = _recv_exact(sock, 12)
            pts_flags, size = struct.unpack(">QI", hdr)
            is_config = bool(pts_flags & SC_PACKET_FLAG_CONFIG)
            is_key = bool(pts_flags & SC_PACKET_FLAG_KEY_FRAME)
            _recv_exact(sock, size)
            total += 1
            if is_config:
                got_config = True
            if is_key:
                got_keyframe = True
            if total >= 120:
                break

    assert got_config, "never received CONFIG (SPS/PPS) packet"
    assert got_keyframe, f"never received keyframe in {total} packets"
