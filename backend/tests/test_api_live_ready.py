"""A live session gets ready first, then records when told to."""

from __future__ import annotations

import json
import threading
import time

from fastapi.testclient import TestClient

from meeting_assistant import config
from meeting_assistant.io_utils import read_json


def _phase(run_id):
    path = config.RUNS_DIR / run_id / "manifest.json"
    if not path.exists():
        return None
    return (read_json(path).get("extra") or {}).get("live_phase", {}).get("phase")


def _wait_phase(run_id, phase, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _phase(run_id) == phase:
            return
        time.sleep(0.02)
    raise AssertionError(f"session never reached {phase!r} (last: {_phase(run_id)!r})")


def test_a_session_waits_until_recording_is_started(client, stub_pipeline, wait_for_job):
    stub_pipeline.live_auto_start = False
    run_id = client.post("/api/live/start", json={}).json()["run_id"]
    _wait_phase(run_id, "ready")
    time.sleep(0.2)
    assert not (config.RUNS_DIR / run_id / "artifacts" / "05_tagged.json").exists()

    assert client.post("/api/live/record").status_code == 202
    _wait_phase(run_id, "recording")
    time.sleep(0.2)
    client.post("/api/live/stop")
    detail = wait_for_job(run_id)
    assert detail["status"] == "completed"


def test_cancelling_before_recording_keeps_nothing(client, stub_pipeline, wait_for_job):
    stub_pipeline.live_auto_start = False
    run_id = client.post("/api/live/start", json={}).json()["run_id"]
    _wait_phase(run_id, "ready")
    assert client.post("/api/live/stop").status_code == 202

    deadline = time.monotonic() + 5
    while client.get("/api/jobs/current").json() is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert client.get("/api/jobs/current").json() is None
    assert not (config.RUNS_DIR / run_id).exists()
    assert client.get("/api/runs").json() == []


def test_the_level_stream_reports_the_microphone_until_the_session_ends(client, stub_pipeline):
    stub_pipeline.live_auto_start = False
    run_id = client.post("/api/live/start", json={}).json()["run_id"]
    _wait_phase(run_id, "ready")

    def stop_soon():
        time.sleep(0.5)
        client.post("/api/live/stop")

    threading.Thread(target=stop_soon, daemon=True).start()
    levels = []
    with client.stream("GET", "/api/live/level") as response:
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():  # ends when the session does
            if line.startswith("data: "):
                levels.append(json.loads(line[6:])["level"])
    assert len(levels) >= 3
    assert all(0 <= level <= 1 for level in levels)
    assert max(levels) > 0


def test_record_and_level_need_a_session(client):
    assert client.post("/api/live/record").status_code == 409
    assert client.get("/api/live/level").status_code == 404


def test_another_account_cannot_start_your_recording(client, stub_pipeline):
    stub_pipeline.live_auto_start = False
    run_id = client.post("/api/live/start", json={}).json()["run_id"]
    _wait_phase(run_id, "ready")
    other = TestClient(client.app)
    other.post("/api/auth/register", json={"username": "second", "password": "long-password-1"})
    assert other.post("/api/live/record").status_code == 409
    assert other.get("/api/live/level").status_code == 404
    assert _phase(run_id) == "ready"
    client.post("/api/live/stop")
