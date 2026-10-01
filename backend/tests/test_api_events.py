"""Tests for the server-sent progress stream."""

from __future__ import annotations

import json
import threading
import time

import pytest

from meeting_assistant.api import events


@pytest.fixture(autouse=True)
def fast_polling(monkeypatch):
    monkeypatch.setattr(events, "POLL_INTERVAL_SEC", 0.02)


def _collect(client, run_id, *, on_open=None, timeout=10.0):
    """Read the stream to its end; return [(event, data), ...]."""
    collected = []
    deadline = time.monotonic() + timeout
    with client.stream("GET", f"/api/runs/{run_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        if on_open is not None:
            on_open()
        event = None
        for line in response.iter_lines():
            assert time.monotonic() < deadline, "stream did not end"
            if line.startswith("event: "):
                event = line.removeprefix("event: ")
            elif line.startswith("data: "):
                collected.append((event, json.loads(line.removeprefix("data: "))))
    return collected


def test_a_finished_run_streams_its_state_once_and_ends(client, audio_file, wait_for_job):
    run_id = client.post("/api/runs/batch", json={"audio": audio_file.name}).json()["run_id"]
    wait_for_job(run_id)

    events_seen = _collect(client, run_id)
    names = [name for name, _ in events_seen]

    assert names[0] == "manifest"
    assert events_seen[0][1]["status"] == "completed"
    assert names[-1] == "end"
    assert "segments" in names


def test_a_run_with_no_job_ends_immediately(client, api_env):
    """A run made by the CLI: nothing is running for it, so state then end."""
    from meeting_assistant.paths import new_run
    from meeting_assistant.pipeline.manifest import RunManifest

    paths = new_run("batch", "cli.wav", runs_dir=api_env / "runs")
    RunManifest.start(paths, mode="batch").set_status("partial")

    names = [name for name, _ in _collect(client, paths.run_id)]
    assert names == ["manifest", "end"]


def test_a_live_run_streams_segments_as_they_are_recorded(client):
    run_id = client.post("/api/live/start", json={}).json()["run_id"]

    def stop_after_a_few_chunks():
        time.sleep(0.4)
        client.post("/api/live/stop")

    threading.Thread(target=stop_after_a_few_chunks, daemon=True).start()
    events_seen = _collect(client, run_id)

    segment_events = [data for name, data in events_seen if name == "segments"]
    assert len(segment_events) >= 2, "segments should arrive incrementally, not all at the end"

    # Each event carries only new segments, and together they are contiguous.
    received = []
    for data in segment_events:
        assert data["start_index"] == len(received)
        received.extend(data["segments"])
    assert [s["text"] for s in received] == [f"chunk {i}" for i in range(len(received))]

    job_states = [data["state"] for name, data in events_seen if name == "job"]
    assert job_states[-1] == "finished"
    assert events_seen[-1][0] == "end"


def test_the_final_manifest_is_never_missed(client, audio_file):
    """The stream must not end before reporting the run's terminal status."""
    run_id = client.post("/api/runs/batch", json={"audio": audio_file.name}).json()["run_id"]
    events_seen = _collect(client, run_id)
    statuses = [data["status"] for name, data in events_seen if name == "manifest"]
    assert statuses[-1] == "completed"
