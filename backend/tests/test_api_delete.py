"""Deleting meetings and uploaded recordings."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from meeting_assistant import config
from meeting_assistant.io_utils import write_json


def _finished_run(client, wait_for_job) -> str:
    run_id = client.post("/api/runs/batch", json={"audio": "meeting.wav"}).json()["run_id"]
    wait_for_job(run_id)
    return run_id


def _second_account(client) -> TestClient:
    other = TestClient(client.app)
    response = other.post(
        "/api/auth/register", json={"username": "second", "password": "long-password-1"}
    )
    assert response.status_code == 201
    return other


# --- meetings --------------------------------------------------------------------
def test_deleting_a_meeting_removes_its_files_and_list_entry(
    client, uploaded_audio, wait_for_job
):
    run_id = _finished_run(client, wait_for_job)
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert not (config.RUNS_DIR / run_id).exists()
    assert client.get("/api/runs").json() == []
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get("/api/runs/search", params={"q": "hello"}).json() == []
    # The recording it came from is kept.
    assert uploaded_audio.exists()


def test_a_meeting_still_processing_cannot_be_deleted(client, uploaded_audio, stub_pipeline):
    stub_pipeline.gate = threading.Event()
    run_id = client.post("/api/runs/batch", json={"audio": "meeting.wav"}).json()["run_id"]
    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 409
    assert "still being processed" in response.json()["detail"]
    stub_pipeline.gate.set()


def test_a_meeting_scored_in_the_evaluation_report_is_kept(
    client, uploaded_audio, wait_for_job
):
    run_id = _finished_run(client, wait_for_job)
    write_json(
        config.EVAL_DIR / "reports" / "latest.json",
        {"generated_at": "2026-10-11T12:00:00", "clips": [{"source": {"run_id": run_id}}]},
    )
    response = client.delete(f"/api/runs/{run_id}")
    assert response.status_code == 409
    assert "evaluation report generated 2026-10-11T12:00:00" in response.json()["detail"]
    assert (config.RUNS_DIR / run_id).exists()


def test_another_account_cannot_delete_a_meeting(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    assert _second_account(client).delete(f"/api/runs/{run_id}").status_code == 404
    assert (config.RUNS_DIR / run_id).exists()


# --- recordings --------------------------------------------------------------------
def test_deleting_a_recording_keeps_the_meetings_made_from_it(
    client, uploaded_audio, wait_for_job
):
    run_id = _finished_run(client, wait_for_job)
    assert client.get("/api/audio").json()[0]["meetings"] == 1

    assert client.delete("/api/audio/meeting.wav").status_code == 204
    assert not uploaded_audio.exists()
    assert client.get("/api/audio").json() == []
    # The meeting stays readable; only its playback is gone.
    assert client.get(f"/api/runs/{run_id}/transcript").status_code == 200
    assert client.get(f"/api/runs/{run_id}/audio").status_code == 404


def test_a_recording_being_processed_cannot_be_deleted(client, uploaded_audio, stub_pipeline):
    stub_pipeline.gate = threading.Event()
    client.post("/api/runs/batch", json={"audio": "meeting.wav"})
    response = client.delete("/api/audio/meeting.wav")
    assert response.status_code == 409
    assert uploaded_audio.exists()
    stub_pipeline.gate.set()


def test_another_account_cannot_delete_a_recording(client, uploaded_audio):
    assert _second_account(client).delete("/api/audio/meeting.wav").status_code == 404
    assert uploaded_audio.exists()


def test_recording_names_cannot_reach_outside_the_upload_folder(client, uploaded_audio):
    assert client.delete("/api/audio/..%2F..%2Fusers.sqlite").status_code in (400, 404)
    assert client.delete("/api/audio/.upload.part").status_code in (400, 404)
