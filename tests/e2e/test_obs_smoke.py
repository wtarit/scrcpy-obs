"""E2E smoke test: create scrcpy source, verify frames change over time.

Requires: OBS running, WebSocket enabled, Android device via ADB_SERIAL.
"""
import base64
import hashlib
import subprocess
import threading
import time
import pytest
import obsws_python as obs

from conftest import ADB_SERIAL

pytestmark = pytest.mark.e2e

POLL_INTERVAL = 2
POLL_COUNT = 15  # 30s total


def _drive_adb(serial: str, stop: threading.Event):
    while not stop.is_set():
        subprocess.run(
            ["adb", "-s", serial, "shell", "input", "swipe",
             "500", "1200", "500", "400", "200"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)


def test_frames_change(obs_client, scrcpy_source):
    """Verify that screenshots hash changes — real frames flowing through."""
    stop = threading.Event()
    t = threading.Thread(target=_drive_adb, args=(ADB_SERIAL, stop), daemon=True)
    t.start()

    last_hash = None
    changed = 0
    ok = 0

    try:
        for i in range(POLL_COUNT):
            time.sleep(POLL_INTERVAL)
            try:
                shot = obs_client.get_source_screenshot(scrcpy_source, "png", 320, 240, 60)
                raw = shot.image_data
                if "," in raw:
                    raw = raw.split(",", 1)[1]
                data = base64.b64decode(raw)
                h = hashlib.sha256(data).hexdigest()[:16]
                if last_hash and h != last_hash:
                    changed += 1
                last_hash = h
                ok += 1
            except obs.error.OBSSDKRequestError:
                pass
    finally:
        stop.set()

    assert ok > 0, "no screenshots succeeded — source never rendered"
    assert changed > 0, f"frames never changed across {ok} screenshots — decoder stuck or no device"
