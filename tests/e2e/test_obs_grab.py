"""E2E grab test: save timestamped screenshots to disk for manual inspection.

Requires: OBS running, WebSocket enabled, Android device via ADB_SERIAL.

Run:
    uv run pytest e2e/test_obs_grab.py -s
Screenshots saved to %TEMP%/scrcpy-obs-shots/.
"""
import base64
import os
import subprocess
import threading
import time
import pytest

from conftest import ADB_SERIAL

pytestmark = pytest.mark.e2e

OUT_DIR = os.path.join(os.environ.get("TEMP", os.getcwd()), "scrcpy-obs-shots")
SAMPLES = 15
INTERVAL = 2


def _drive_adb(serial: str, stop: threading.Event):
    while not stop.is_set():
        subprocess.run(
            ["adb", "-s", serial, "shell", "input", "swipe",
             "500", "1200", "500", "400", "200"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1)


def test_grab_screenshots(obs_client, scrcpy_source):
    """Capture screenshots over 30s and save to disk. Passes if at least one non-empty PNG saved."""
    os.makedirs(OUT_DIR, exist_ok=True)
    for f in os.listdir(OUT_DIR):
        if f.endswith(".png"):
            os.remove(os.path.join(OUT_DIR, f))

    stop = threading.Event()
    t = threading.Thread(target=_drive_adb, args=(ADB_SERIAL, stop), daemon=True)
    t.start()

    saved = []
    try:
        for i in range(SAMPLES):
            time.sleep(INTERVAL)
            try:
                shot = obs_client.get_source_screenshot(scrcpy_source, "png", 288, 640, 90)
                raw = shot.image_data
                if "," in raw:
                    raw = raw.split(",", 1)[1]
                data = base64.b64decode(raw)
                path = os.path.join(OUT_DIR, f"t{(i+1)*INTERVAL:02d}s.png")
                with open(path, "wb") as f:
                    f.write(data)
                saved.append((path, len(data)))
                print(f"\n[t+{(i+1)*INTERVAL:02d}s] {len(data)}B → {path}")
            except Exception as e:
                print(f"\n[t+{(i+1)*INTERVAL:02d}s] err: {e}")
    finally:
        stop.set()

    assert saved, "no screenshots saved"
    assert any(size > 1000 for _, size in saved), "all screenshots suspiciously small (<1KB)"
    print(f"\nSaved {len(saved)} screenshots to {OUT_DIR}")
