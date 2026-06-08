"""Shared fixtures for scrcpy-obs tests."""
import os
import time
import pytest
import obsws_python as obs

OBS_HOST = os.environ.get("OBS_HOST", "127.0.0.1")
OBS_PORT = int(os.environ.get("OBS_PORT", "4455"))
OBS_PASSWORD = os.environ.get("OBS_PASSWORD", "")
ADB_SERIAL = os.environ.get("ADB_SERIAL", "emulator-5554")
SCRCPY_BIN_DIR = os.environ.get(
    "SCRCPY_BIN_DIR",
    str(((__import__("pathlib").Path(__file__).parent.parent / "data" / "bin")).resolve()),
)

TEST_SCENE = "ScrcpyTest"
TEST_SOURCE = "ScrcpySmokeInput"


@pytest.fixture(scope="session")
def obs_client():
    cl = obs.ReqClient(host=OBS_HOST, port=OBS_PORT, password=OBS_PASSWORD, timeout=8)
    yield cl


@pytest.fixture
def obs_scene(obs_client):
    scenes = [s["sceneName"] for s in obs_client.get_scene_list().scenes]
    if TEST_SCENE not in scenes:
        obs_client.create_scene(TEST_SCENE)
    obs_client.set_current_program_scene(TEST_SCENE)
    yield TEST_SCENE


@pytest.fixture
def scrcpy_source(obs_client, obs_scene):
    try:
        obs_client.remove_input(TEST_SOURCE)
        time.sleep(0.5)
    except Exception:
        pass

    obs_client.create_input(
        obs_scene,
        TEST_SOURCE,
        "scrcpy_source",
        {
            "serial": ADB_SERIAL,
            "video_source": "display",
            "max_size": 1280,
            "bitrate_kbps": 8000,
            "codec": "h264",
        },
        True,
    )
    yield TEST_SOURCE

    try:
        obs_client.remove_input(TEST_SOURCE)
    except Exception:
        pass
