"""
Launch OBS, wait for WebSocket, run e2e pytest suite, kill OBS, exit with pytest code.

Usage:
    uv run python run_e2e.py [extra pytest args...]

Environment:
    OBS_EXE         path to obs64.exe (default: C:/Program Files/obs-studio/bin/64bit/obs64.exe)
    OBS_WORKDIR     OBS working directory (default: same dir as OBS_EXE)
    OBS_HOST        WebSocket host (default: 127.0.0.1)
    OBS_PORT        WebSocket port (default: 4455)
    OBS_PASSWORD    WebSocket password (default: empty)
    ADB_SERIAL      ADB device serial (default: emulator-5554)
    OBS_STARTUP_TIMEOUT  seconds to wait for WebSocket (default: 30)
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

OBS_EXE = Path(os.environ.get(
    "OBS_EXE",
    r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
))
OBS_WORKDIR = Path(os.environ.get("OBS_WORKDIR", str(OBS_EXE.parent)))
OBS_HOST = os.environ.get("OBS_HOST", "127.0.0.1")
OBS_PORT = int(os.environ.get("OBS_PORT", "4455"))
OBS_PASSWORD = os.environ.get("OBS_PASSWORD", "")
STARTUP_TIMEOUT = int(os.environ.get("OBS_STARTUP_TIMEOUT", "30"))

HERE = Path(__file__).parent


def _obs_ws_reachable() -> bool:
    try:
        with socket.create_connection((OBS_HOST, OBS_PORT), timeout=1.0):
            return True
    except OSError:
        return False


def _wait_for_obs(timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _obs_ws_reachable():
            return True
        time.sleep(0.5)
    return False


def main() -> int:
    extra_args = sys.argv[1:]

    already_running = _obs_ws_reachable()
    obs_proc = None

    if not already_running:
        if not OBS_EXE.exists():
            print(f"[run_e2e] OBS not found at {OBS_EXE}", file=sys.stderr)
            return 1

        print(f"[run_e2e] spawning OBS from {OBS_WORKDIR}")
        obs_proc = subprocess.Popen(
            [str(OBS_EXE), "--minimize-to-tray"],
            cwd=str(OBS_WORKDIR),
        )

        print(f"[run_e2e] waiting up to {STARTUP_TIMEOUT}s for WebSocket on {OBS_HOST}:{OBS_PORT}")
        if not _wait_for_obs(STARTUP_TIMEOUT):
            print("[run_e2e] OBS WebSocket never became reachable", file=sys.stderr)
            obs_proc.terminate()
            return 1
    else:
        print(f"[run_e2e] OBS WebSocket already reachable on {OBS_HOST}:{OBS_PORT}")

    print("[run_e2e] running e2e suite")
    pytest_cmd = [
        sys.executable, "-m", "pytest",
        "e2e/",
        "-v",
        *extra_args,
    ]
    env = os.environ.copy()
    env.setdefault("OBS_HOST", OBS_HOST)
    env.setdefault("OBS_PORT", str(OBS_PORT))
    env.setdefault("OBS_PASSWORD", OBS_PASSWORD)

    result = subprocess.run(pytest_cmd, cwd=str(HERE), env=env)

    if obs_proc is not None:
        print("[run_e2e] shutting down OBS")
        obs_proc.terminate()
        try:
            obs_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            obs_proc.kill()

    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
