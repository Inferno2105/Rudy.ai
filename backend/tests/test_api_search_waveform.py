"""Search across meetings, and the recording's waveform envelope."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from meeting_assistant.audio.wav_io import save_wav
from meeting_assistant.audio.waveform import _decode_any, envelope, waveform


def _finished_run(client, wait_for_job, audio="meeting.wav") -> str:
    run_id = client.post("/api/runs/batch", json={"audio": audio}).json()["run_id"]
    wait_for_job(run_id)
    return run_id


# --- search ----------------------------------------------------------------------
def test_search_finds_transcript_lines_case_insensitively(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    hits = client.get("/api/runs/search", params={"q": "HELLO"}).json()
    assert [(h["run_id"], h["idx"], h["text"]) for h in hits] == [(run_id, 1, "hello")]
    assert hits[0]["start"] == 2.0 and hits[0]["speaker"] == "SPEAKER_01"


def test_search_treats_wildcards_literally(client, uploaded_audio, wait_for_job):
    _finished_run(client, wait_for_job)
    assert client.get("/api/runs/search", params={"q": "%"}).json() == []
    assert client.get("/api/runs/search", params={"q": "h_llo"}).json() == []


def test_search_needs_some_text(client):
    assert client.get("/api/runs/search", params={"q": ""}).status_code == 422


def test_search_never_returns_another_accounts_lines(client, uploaded_audio, wait_for_job):
    _finished_run(client, wait_for_job)
    other = TestClient(client.app)
    assert (
        other.post(
            "/api/auth/register", json={"username": "second", "password": "long-password-1"}
        ).status_code
        == 201
    )
    assert other.get("/api/runs/search", params={"q": "hello"}).json() == []


# --- waveform ----------------------------------------------------------------------
def test_envelope_is_scaled_to_the_loudest_slice():
    samples = np.concatenate([np.zeros(100), np.full(100, 0.5), np.full(100, 1.0)])
    assert envelope(samples.astype(np.float32), 3) == [0.0, 0.5, 1.0]


def test_envelope_of_silence_is_flat():
    assert envelope(np.zeros(1000, dtype=np.float32), 4) == [0.0, 0.0, 0.0, 0.0]


def test_waveform_reports_duration_and_bins(tmp_path):
    rate = 16000
    tone = (np.sin(np.linspace(0, 2000, rate * 2)) * 8000).astype(np.int16)
    tone[:rate] //= 4  # quieter first second
    path = save_wav(tmp_path / "tone.wav", tone, rate)
    duration, peaks = waveform(path, 64)
    assert duration == pytest.approx(2.0)
    assert len(peaks) == 64 and max(peaks) == 1.0
    assert np.mean(peaks[:32]) < np.mean(peaks[32:])


def test_formats_other_than_wav_are_decoded_too(tmp_path):
    path = save_wav(tmp_path / "x.wav", np.full(8000, 1000, dtype=np.int16), 8000)
    samples, rate = _decode_any(path)
    assert rate == 8000 and samples.size == pytest.approx(8000, abs=200)


def test_waveform_endpoint(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    body = client.get(f"/api/runs/{run_id}/waveform", params={"bins": 100}).json()
    assert body["duration_sec"] == pytest.approx(1.0)
    assert len(body["peaks"]) == 100


def test_waveform_of_another_accounts_run_is_not_found(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    other = TestClient(client.app)
    other.post("/api/auth/register", json={"username": "second", "password": "long-password-1"})
    assert other.get(f"/api/runs/{run_id}/waveform").status_code == 404
