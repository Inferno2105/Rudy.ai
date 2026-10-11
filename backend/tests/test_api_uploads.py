"""Tests for audio upload and listing."""

from __future__ import annotations

import io

import numpy as np

from meeting_assistant.audio.wav_io import save_wav


def _wav_bytes(tmp_path, seconds=1.0, value=0) -> bytes:
    path = save_wav(
        tmp_path / "src.wav", np.full(int(16000 * seconds), value, dtype=np.int16), 16000
    )
    return path.read_bytes()


def _files(folder):
    return sorted(folder.iterdir()) if folder.is_dir() else []


def _upload(client, name, data, content_type="audio/wav"):
    return client.post("/api/uploads", files={"file": (name, io.BytesIO(data), content_type)})


def test_upload_stores_a_wav_and_reports_its_duration(client, my_audio_dir, tmp_path):
    response = _upload(client, "standup.wav", _wav_bytes(tmp_path, seconds=2.0))
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "standup.wav"
    assert body["duration_sec"] == 2.0
    assert body["already_present"] is False
    assert (my_audio_dir / "standup.wav").exists()


def test_uploaded_file_is_listed(client, tmp_path):
    _upload(client, "standup.wav", _wav_bytes(tmp_path))
    names = [f["name"] for f in client.get("/api/audio").json()]
    assert names == ["standup.wav"]


def test_file_name_is_reduced_to_a_safe_slug(client, my_audio_dir, tmp_path):
    response = _upload(client, "../../My Team Meeting (Final)!.wav", _wav_bytes(tmp_path))
    assert response.status_code == 201
    name = response.json()["name"]
    assert name == "my-team-meeting-final.wav"
    assert (my_audio_dir / name).exists()
    assert not (my_audio_dir / "My Team Meeting (Final)!.wav").exists()


def test_reuploading_identical_content_is_not_an_error(client, tmp_path):
    data = _wav_bytes(tmp_path)
    _upload(client, "standup.wav", data)
    response = _upload(client, "standup.wav", data)
    assert response.status_code == 201
    assert response.json()["already_present"] is True


def test_different_content_under_an_existing_name_is_refused(client, my_audio_dir, tmp_path):
    """Runs record their input's sha256; replacing the bytes behind a name would
    silently break that link for every earlier run of it."""
    _upload(client, "standup.wav", _wav_bytes(tmp_path, value=0))
    original = (my_audio_dir / "standup.wav").read_bytes()

    response = _upload(client, "standup.wav", _wav_bytes(tmp_path, value=7))

    assert response.status_code == 409
    assert (my_audio_dir / "standup.wav").read_bytes() == original


def test_unsupported_file_types_are_refused(client, api_env, my_audio_dir):
    response = _upload(client, "notes.txt", b"hello", content_type="text/plain")
    assert response.status_code == 415
    assert _files(my_audio_dir) == []


def test_oversized_upload_is_refused_and_leaves_nothing_behind(
    client, api_env, my_audio_dir, tmp_path, monkeypatch
):
    from meeting_assistant import config

    monkeypatch.setattr(config, "API_MAX_UPLOAD_MB", 0)
    response = _upload(client, "big.wav", _wav_bytes(tmp_path))
    assert response.status_code == 413
    assert _files(my_audio_dir) == []  # no .part file, no partial wav
