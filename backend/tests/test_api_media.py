"""Tests for audio playback URLs (media tickets).

An ``<audio>`` element cannot send an Authorization header, so playback uses a
short-lived, run-scoped signed ticket instead of ever putting the API token in
a URL. These tests pin down exactly what a ticket can and cannot unlock.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

import pytest

from meeting_assistant.api.auth import issue_media_ticket, media_ticket_is_valid


@pytest.fixture
def finished_run(client, audio_file, wait_for_job):
    run_id = client.post("/api/runs/batch", json={"audio": audio_file.name}).json()["run_id"]
    wait_for_job(run_id)
    return run_id


@contextmanager
def without_token(client):
    """Requests made inside carry no Authorization header, like an <audio> element's."""
    token = client.headers.pop("Authorization")
    try:
        yield client
    finally:
        client.headers["Authorization"] = token


def _issue(client, run_id):
    response = client.post(f"/api/runs/{run_id}/audio-url")
    assert response.status_code == 200
    return response.json()


def test_a_ticket_url_streams_the_recording_without_a_header(client, finished_run, audio_file):
    url = _issue(client, finished_run)["url"]
    with without_token(client):
        response = client.get(url)
    assert response.status_code == 200
    assert response.content == audio_file.read_bytes()


def test_the_url_never_contains_the_api_token(client, finished_run):
    from conftest import API_TOKEN

    issued = _issue(client, finished_run)
    assert API_TOKEN not in issued["url"]
    assert issued["expires_at"] > time.time()


def test_range_requests_work_so_the_player_can_seek(client, finished_run):
    url = _issue(client, finished_run)["url"]
    with without_token(client):
        response = client.get(url, headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert len(response.content) == 10


def test_audio_still_accepts_the_bearer_token(client, finished_run):
    assert client.get(f"/api/runs/{finished_run}/audio").status_code == 200


def test_audio_without_token_or_ticket_is_rejected(client, finished_run):
    with without_token(client):
        assert client.get(f"/api/runs/{finished_run}/audio").status_code == 401


def test_a_tampered_ticket_is_rejected(client, finished_run):
    ticket, _ = issue_media_ticket(finished_run)
    expires, _, signature = ticket.partition(".")
    forged = f"{int(expires) + 3600}.{signature}"
    with without_token(client):
        response = client.get(f"/api/runs/{finished_run}/audio?ticket={forged}")
    assert response.status_code == 401


def test_a_ticket_for_one_run_does_not_unlock_another(api_env):
    ticket, _ = issue_media_ticket("run-a")
    assert media_ticket_is_valid("run-a", ticket)
    assert not media_ticket_is_valid("run-b", ticket)


def test_an_expired_ticket_is_rejected(api_env):
    ticket, expires = issue_media_ticket("run-a", now=1_000_000)
    assert media_ticket_is_valid("run-a", ticket, now=expires - 1)
    assert not media_ticket_is_valid("run-a", ticket, now=expires + 1)


@pytest.mark.parametrize("ticket", [None, "", "garbage", "abc.def", "123", ".sig"])
def test_malformed_tickets_are_rejected(api_env, ticket):
    assert not media_ticket_is_valid("run-a", ticket)


def test_tickets_stop_working_when_the_server_token_changes(api_env, monkeypatch):
    from meeting_assistant import config

    ticket, _ = issue_media_ticket("run-a")
    monkeypatch.setattr(config, "API_TOKEN", "a-completely-different-token-of-sufficient-length")
    assert not media_ticket_is_valid("run-a", ticket)


def test_issuing_a_ticket_requires_the_token(client, finished_run):
    with without_token(client):
        assert client.post(f"/api/runs/{finished_run}/audio-url").status_code == 401


def test_no_ticket_is_issued_for_a_run_without_playable_audio(client, api_env):
    from meeting_assistant.paths import new_run
    from meeting_assistant.pipeline.manifest import RunManifest

    paths = new_run("live", "mic", runs_dir=api_env / "runs")
    RunManifest.start(paths, mode="live")
    assert client.post(f"/api/runs/{paths.run_id}/audio-url").status_code == 404
