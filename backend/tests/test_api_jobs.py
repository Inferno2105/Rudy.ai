"""Tests for job orchestration: queueing, busy refusal, live control, failures, resume."""

from __future__ import annotations

import threading
import time

from meeting_assistant.io_utils import read_json


def _start_batch(client, audio_file):
    response = client.post("/api/runs/batch", json={"audio": audio_file.name})
    assert response.status_code == 202
    return response.json()


def _wait_state(client, run_id, state, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/runs/{run_id}").json().get("job")
        if job and job["state"] == state:
            return job
        time.sleep(0.02)
    raise AssertionError(f"{run_id} never reached {state}")


def test_batch_returns_the_run_id_immediately_and_runs_in_the_background(
    client, audio_file, wait_for_job, stub_pipeline
):
    accepted = _start_batch(client, audio_file)
    detail = wait_for_job(accepted["run_id"])
    assert detail["status"] == "completed"
    assert stub_pipeline.batch_calls[0].resume_run_id == accepted["run_id"]


def test_batch_passes_num_speakers_through(client, audio_file, wait_for_job, stub_pipeline):
    run_id = client.post(
        "/api/runs/batch", json={"audio": audio_file.name, "num_speakers": 3}
    ).json()["run_id"]
    wait_for_job(run_id)
    assert stub_pipeline.batch_calls[0].num_speakers == 3


def test_batch_on_a_missing_file_is_404(client):
    assert client.post("/api/runs/batch", json={"audio": "nope.wav"}).status_code == 404


def test_batch_audio_must_be_a_bare_name_not_a_path(client, audio_file):
    for name in ("../meeting.wav", "..\\meeting.wav", "C:/Windows/win.ini"):
        response = client.post("/api/runs/batch", json={"audio": name})
        assert response.status_code == 400, name


def test_jobs_run_one_at_a_time_in_submission_order(client, audio_file, stub_pipeline):
    stub_pipeline.gate = threading.Event()
    first = _start_batch(client, audio_file)
    second = _start_batch(client, audio_file)

    _wait_state(client, first["run_id"], "running")
    assert client.get(f"/api/runs/{second['run_id']}").json()["job"]["state"] == "queued"
    assert client.get("/api/jobs/current").json()["run_id"] == first["run_id"]

    stub_pipeline.gate.set()
    _wait_state(client, second["run_id"], "finished")
    order = [opts.resume_run_id for opts in stub_pipeline.batch_calls]
    assert order == [first["run_id"], second["run_id"]]


def test_live_start_is_refused_while_another_job_is_busy(client, audio_file, stub_pipeline):
    stub_pipeline.gate = threading.Event()
    _start_batch(client, audio_file)

    response = client.post("/api/live/start", json={})
    assert response.status_code == 409
    assert stub_pipeline.live_calls == []


def test_live_start_then_stop(client, stub_pipeline, wait_for_job):
    accepted = client.post("/api/live/start", json={"num_speakers": 2}).json()
    _wait_state(client, accepted["run_id"], "running")

    stopped = client.post("/api/live/stop")
    assert stopped.status_code == 202
    assert stopped.json()["state"] == "stopping"

    detail = wait_for_job(accepted["run_id"])
    assert detail["job"]["state"] == "finished"
    assert detail["mode"] == "live"
    assert stub_pipeline.live_calls[0].num_speakers == 2


def test_live_stop_with_nothing_recording_is_409(client):
    assert client.post("/api/live/stop").status_code == 409


def test_a_failing_job_is_recorded_and_the_worker_keeps_going(
    client, audio_file, stub_pipeline, wait_for_job, api_env
):
    stub_pipeline.fail = True
    failed = _start_batch(client, audio_file)
    detail = wait_for_job(failed["run_id"])
    assert detail["job"]["state"] == "failed"
    assert "stub pipeline failed" in detail["job"]["error"]
    # Also recorded on disk, so the run does not read as resumable-partial.
    assert detail["status"] == "failed"
    assert "stub pipeline failed" in detail["extra"]["error"]

    stub_pipeline.fail = False
    later = _start_batch(client, audio_file)
    assert wait_for_job(later["run_id"])["job"]["state"] == "finished"


def test_resume_reruns_from_a_forced_stage(client, audio_file, stub_pipeline, wait_for_job):
    run_id = _start_batch(client, audio_file)["run_id"]
    wait_for_job(run_id)

    response = client.post(f"/api/runs/{run_id}/resume", json={"force_stage": "tagged"})
    assert response.status_code == 202
    wait_for_job(run_id)
    assert stub_pipeline.batch_calls[-1].force_stage == "tagged"
    assert stub_pipeline.batch_calls[-1].resume_run_id == run_id


def test_resume_rejects_an_unknown_stage(client, audio_file, wait_for_job):
    run_id = _start_batch(client, audio_file)["run_id"]
    wait_for_job(run_id)
    response = client.post(f"/api/runs/{run_id}/resume", json={"force_stage": "nope"})
    assert response.status_code == 422


def test_resume_refuses_a_live_run(client, wait_for_job):
    run_id = client.post("/api/live/start", json={}).json()["run_id"]
    _wait_state(client, run_id, "running")
    client.post("/api/live/stop")
    wait_for_job(run_id)
    assert client.post(f"/api/runs/{run_id}/resume", json={}).status_code == 409


def test_resume_refuses_a_run_that_already_has_an_active_job(client, audio_file, stub_pipeline):
    stub_pipeline.gate = threading.Event()
    run_id = _start_batch(client, audio_file)["run_id"]
    _wait_state(client, run_id, "running")
    assert client.post(f"/api/runs/{run_id}/resume", json={}).status_code == 409


def test_finished_live_run_records_its_stats(client, api_env, wait_for_job):
    run_id = client.post("/api/live/start", json={}).json()["run_id"]
    _wait_state(client, run_id, "running")
    time.sleep(0.2)
    client.post("/api/live/stop")
    wait_for_job(run_id)

    manifest = read_json(api_env / "runs" / run_id / "manifest.json")
    assert manifest["extra"]["live_stats"]["chunks_recorded"] >= 1


def test_resume_under_a_changed_config_is_refused_with_409_and_queues_nothing(
    client, audio_file, stub_pipeline, wait_for_job, monkeypatch
):
    from meeting_assistant import config

    run_id = _start_batch(client, audio_file)["run_id"]
    wait_for_job(run_id)
    calls_before = len(stub_pipeline.batch_calls)

    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.1:8b")
    response = client.post(f"/api/runs/{run_id}/resume", json={"force_stage": "summary"})

    assert response.status_code == 409
    assert "ollama_model" in response.json()["detail"]
    assert len(stub_pipeline.batch_calls) == calls_before
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "completed"


def test_resume_with_mixed_config_allowed_is_passed_through(
    client, audio_file, stub_pipeline, wait_for_job, monkeypatch
):
    from meeting_assistant import config

    run_id = _start_batch(client, audio_file)["run_id"]
    wait_for_job(run_id)

    monkeypatch.setattr(config, "OLLAMA_MODEL", "llama3.1:8b")
    response = client.post(
        f"/api/runs/{run_id}/resume",
        json={"force_stage": "summary", "allow_mixed_config": True},
    )

    assert response.status_code == 202
    wait_for_job(run_id)
    assert stub_pipeline.batch_calls[-1].allow_mixed_config is True


def test_a_refusal_inside_the_job_does_not_mark_the_run_failed(
    client, audio_file, stub_pipeline, wait_for_job
):
    """If the pipeline itself refuses (config changed while queued), the run
    on disk is untouched and must stay resumable, not become "failed"."""
    from meeting_assistant.errors import ProvenanceError

    run_id = _start_batch(client, audio_file)["run_id"]
    wait_for_job(run_id)

    def refuse(audio_path, opts):
        raise ProvenanceError("config changed")

    client.app.state.jobs._run_batch = refuse
    response = client.post(f"/api/runs/{run_id}/resume", json={})
    assert response.status_code == 202

    detail = wait_for_job(run_id)
    assert detail["job"]["state"] == "failed"
    assert "ProvenanceError" in detail["job"]["error"]
    assert detail["status"] == "completed"
    assert "error" not in detail["extra"]


def test_run_detail_reports_consistency(client, audio_file, wait_for_job):
    run_id = _start_batch(client, audio_file)["run_id"]
    detail = wait_for_job(run_id)

    assert detail["consistency"] == {"executions": [0], "config": True, "code": True}
    assert detail["resumes"] == []
