"""Finding a run's recording when it was processed on another machine."""

from __future__ import annotations

import pytest

from meeting_assistant import config
from meeting_assistant.audio.locate import locate_recording
from meeting_assistant.io_utils import sha256_file


@pytest.fixture
def audio_dir(tmp_path, monkeypatch):
    folder = tmp_path / "data" / "audio"
    (folder / "users" / "abc").mkdir(parents=True)
    monkeypatch.setattr(config, "AUDIO_DIR", folder)
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    return folder


def _file(path, content=b"RIFF-not-really-audio"):
    path.write_bytes(content)
    return path, sha256_file(path)


def test_a_path_that_exists_here_is_used_as_is(audio_dir):
    path, sha = _file(audio_dir / "test.wav")
    assert locate_recording(str(path), sha) == path.resolve()


def test_a_relative_path_resolves_from_the_repo_root(audio_dir):
    path, sha = _file(audio_dir / "test.wav")
    assert locate_recording("data/audio/test.wav", sha) == path.resolve()


@pytest.mark.parametrize(
    "recorded",
    [
        r"C:\Users\someone\whisper-project\data\audio\users\abc\meeting.wav",  # native Windows
        "/app/data/audio/users/abc/meeting.wav",  # Docker
        r"data\audio\users\abc\meeting.wav",  # relative, Windows separators
    ],
)
def test_a_path_from_another_machine_is_found_in_the_audio_folder(audio_dir, recorded):
    path, sha = _file(audio_dir / "users" / "abc" / "meeting.wav")
    assert locate_recording(recorded, sha) == path.resolve()


def test_a_relocated_file_with_different_bytes_is_refused(audio_dir):
    _file(audio_dir / "test.wav", b"other recording")
    assert locate_recording("/app/data/audio/test.wav", "0" * 64) is None


def test_nothing_outside_the_audio_folder_is_returned(audio_dir, tmp_path):
    secret, sha = _file(tmp_path / "secret.wav")
    assert locate_recording(str(secret), sha) is None
    assert locate_recording("/etc/audio/../../secret.wav", sha) is None
    assert locate_recording("/elsewhere/secret.wav", sha) is None


def test_a_missing_file_or_path_is_none(audio_dir):
    assert locate_recording("/app/data/audio/gone.wav", None) is None
    assert locate_recording(None, None) is None


def test_the_api_plays_a_run_recorded_with_a_docker_path(
    client, test_user, uploaded_audio, wait_for_job
):
    """A run made in Docker, opened on the native server (or the other way round)."""
    from meeting_assistant.io_utils import read_json, write_json
    from meeting_assistant.paths import open_run

    run_id = client.post("/api/runs/batch", json={"audio": "meeting.wav"}).json()["run_id"]
    wait_for_job(run_id)
    paths = open_run(run_id)
    manifest = read_json(paths.manifest_path)
    manifest["provenance"]["input"]["path"] = (
        f"/app/data/audio/users/{test_user.uid}/meeting.wav"
    )
    write_json(paths.manifest_path, manifest)

    assert client.get(f"/api/runs/{run_id}/audio").status_code == 200
    assert client.get(f"/api/runs/{run_id}/waveform").status_code == 200
