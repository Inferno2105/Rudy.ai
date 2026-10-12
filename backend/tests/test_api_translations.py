"""Translating a meeting and downloading its transcript as a PDF, over the API."""

from __future__ import annotations

import threading
import time

from fastapi.testclient import TestClient


def _finished_run(client, wait_for_job) -> str:
    run_id = client.post("/api/runs/batch", json={"audio": "meeting.wav"}).json()["run_id"]
    wait_for_job(run_id)
    return run_id


def _wait_translation(client, run_id, target, *, states=("ready", "failed"), timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/runs/{run_id}/translations/{target}").json()
        if body["state"] in states:
            return body
        time.sleep(0.02)
    raise AssertionError(f"translation never reached {states}")


def test_a_meeting_is_translated_on_request(client, uploaded_audio, wait_for_job, stub_pipeline):
    run_id = _finished_run(client, wait_for_job)
    assert client.get(f"/api/runs/{run_id}/translations/english").json()["state"] == "missing"

    started = client.post(f"/api/runs/{run_id}/translations/english")
    assert started.status_code == 202
    assert started.json()["state"] in ("queued", "running", "ready")

    body = _wait_translation(client, run_id, "english")
    assert body["state"] == "ready"
    assert body["model"] == "stub-llm"
    # "namaste" was Hindi and is translated; "hello" was already English.
    assert [s["text"] for s in body["segments"]] == ["[english] namaste", "hello"]
    assert body["done"] == body["total"] == 2

    # Asking again returns the stored translation instead of making another.
    again = client.post(f"/api/runs/{run_id}/translations/english")
    assert again.json()["state"] == "ready"
    assert stub_pipeline.translate_calls == ["english"]


def test_translating_does_not_look_like_processing(
    client, uploaded_audio, wait_for_job, stub_pipeline
):
    run_id = _finished_run(client, wait_for_job)
    stub_pipeline.gate = threading.Event()
    client.post(f"/api/runs/{run_id}/translations/hindi")
    _wait_translation(client, run_id, "hindi", states=("running",))

    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["job"]["kind"] == "batch"
    assert detail["job"]["state"] == "finished"
    # It is still busy with the meeting, though, so the meeting cannot be deleted.
    assert client.delete(f"/api/runs/{run_id}").status_code == 409
    stub_pipeline.gate.set()
    assert _wait_translation(client, run_id, "hindi")["state"] == "ready"


def test_a_failed_translation_leaves_the_meeting_untouched(
    client, uploaded_audio, wait_for_job, stub_pipeline
):
    run_id = _finished_run(client, wait_for_job)
    stub_pipeline.fail = True
    client.post(f"/api/runs/{run_id}/translations/english")
    body = _wait_translation(client, run_id, "english")
    assert body["state"] == "failed"
    assert "stub translation failed" in body["error"]
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "completed"

    # Retrying after the cause is fixed makes a new attempt.
    stub_pipeline.fail = False
    client.post(f"/api/runs/{run_id}/translations/english")
    assert _wait_translation(client, run_id, "english")["state"] == "ready"


def test_unknown_languages_are_refused(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    assert client.post(f"/api/runs/{run_id}/translations/french").status_code == 422


def test_the_transcript_downloads_as_a_pdf(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    response = client.get(f"/api/runs/{run_id}/transcript.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert 'filename="meeting_transcript_original.pdf"' in response.headers["content-disposition"]


def test_a_translated_pdf_needs_the_translation_first(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    url = f"/api/runs/{run_id}/transcript.pdf"
    refused = client.get(url, params={"version": "english"})
    assert refused.status_code == 409
    assert "not been translated" in refused.json()["detail"]

    client.post(f"/api/runs/{run_id}/translations/english")
    _wait_translation(client, run_id, "english")
    assert client.get(url, params={"version": "english"}).status_code == 200
    # The stub run has no romanized transcript.
    assert client.get(url, params={"version": "romanized"}).status_code == 404
    assert client.get(url, params={"version": "klingon"}).status_code == 422


def test_another_account_cannot_translate_or_download(client, uploaded_audio, wait_for_job):
    run_id = _finished_run(client, wait_for_job)
    other = TestClient(client.app)
    other.post("/api/auth/register", json={"username": "second", "password": "long-password-1"})
    assert other.post(f"/api/runs/{run_id}/translations/english").status_code == 404
    assert other.get(f"/api/runs/{run_id}/transcript.pdf").status_code == 404
