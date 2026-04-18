"""E2E multi-device test: create two scrcpy sources simultaneously, verify both active.

Requires: OBS running, WebSocket enabled, 2+ Android devices connected.
"""
import subprocess
import time
import pytest
import obsws_python as obs

pytestmark = pytest.mark.e2e

SOURCE_NAMES = ["scrcpy-test-device1", "scrcpy-test-device2"]


def _get_adb_devices():
    result = subprocess.run(
        ["adb", "devices", "-l"], capture_output=True, text=True, timeout=5
    )
    devices = []
    for line in result.stdout.splitlines():
        if line.startswith("List") or not line.strip():
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        status_rest = " ".join(parts[1:])
        if status_rest.startswith(("offline", "unauthorized", "no permissions")):
            continue
        serial = parts[0]
        model = next((t[6:].replace("_", " ") for t in parts if t.startswith("model:")), "")
        devices.append((serial, model))
    return devices


def test_two_sources_simultaneously(obs_client):
    """Both sources must be video-active at the same time."""
    devices = _get_adb_devices()
    if len(devices) < 2:
        pytest.skip(f"need 2 ADB devices, found {len(devices)}")

    scene = obs_client.get_current_program_scene().current_program_scene_name
    created = []

    try:
        for i, (serial, model) in enumerate(devices[:2]):
            name = SOURCE_NAMES[i]
            try:
                obs_client.remove_input(name)
            except Exception:
                pass
            obs_client.create_input(
                scene, name, "scrcpy_source",
                {"serial": serial, "video_source": "display",
                 "max_size": 720, "bitrate_kbps": 4000, "codec": "h264"},
                True,
            )
            created.append(name)

        time.sleep(8)

        failures = []
        for name in created:
            try:
                active = obs_client.get_source_active(name)
                if not active.video_active:
                    failures.append(f"{name}: INACTIVE")
            except obs.error.OBSSDKRequestError as e:
                failures.append(f"{name}: ERROR {e}")

        assert not failures, "sources not active:\n" + "\n".join(failures)

    finally:
        for name in created:
            try:
                obs_client.remove_input(name)
            except Exception:
                pass


def test_serial_change(obs_client):
    """Changing serial on existing source must produce an active stream on the new device."""
    devices = _get_adb_devices()
    if len(devices) < 2:
        pytest.skip(f"need 2 ADB devices, found {len(devices)}")

    serial1, _ = devices[0]
    serial2, _ = devices[1]
    scene = obs_client.get_current_program_scene().current_program_scene_name
    name = "scrcpy-test-serial-change"

    try:
        obs_client.remove_input(name)
    except Exception:
        pass

    try:
        obs_client.create_input(
            scene, name, "scrcpy_source",
            {"serial": serial1, "video_source": "display",
             "max_size": 720, "bitrate_kbps": 4000, "codec": "h264"},
            True,
        )
        time.sleep(8)

        active = obs_client.get_source_active(name)
        assert active.video_active, f"device1 ({serial1}) never went active"

        # Switch to second device — triggers src_update in the plugin
        obs_client.set_input_settings(name, {"serial": serial2}, True)
        time.sleep(10)  # scrcpy restart needs extra time after kill+respawn

        active = obs_client.get_source_active(name)
        assert active.video_active, (
            f"device2 ({serial2}) never went active after serial change"
        )

    finally:
        try:
            obs_client.remove_input(name)
        except Exception:
            pass
