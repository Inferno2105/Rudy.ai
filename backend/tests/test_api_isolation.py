"""Two accounts on one server never see or touch each other's data.

``client`` is signed in as the first account (``TEST_USER``); ``other`` is a
second browser, on the same app, that signs up as a second account.
"""

from __future__ import annotations

import io
import sqlite3

import numpy as np
import pytest
from conftest import TEST_USER

from meeting_assistant import accounts, config
from meeting_assistant.audio.wav_io import save_wav

OTHER = {"username": "second", "password": "another-long-password"}


@pytest.fixture
def other(client):
    """A second browser on the same server, signed up as a second account."""
    from fastapi.testclient import TestClient

    second = TestClient(client.app)  # no `with`: the app is already running
    response = second.post("/api/auth/register", json=OTHER)
    assert response.status_code == 201, response.text
    return second


def _wav(tmp_path, value=0) -> bytes:
    return save_wav(
        tmp_path / f"src{value}.wav", np.full(16000, value, dtype=np.int16), 16000
    ).read_bytes()


def _upload(client, name, data):
    return client.post("/api/uploads", files={"file": (name, io.BytesIO(data), "audio/wav")})


def _finished_run(client, wait_for_job, tmp_path) -> str:
    assert _upload(client, "standup.wav", _wav(tmp_path)).status_code == 201
    run_id = client.post("/api/runs/batch", json={"audio": "standup.wav"}).json()["run_id"]
    wait_for_job(run_id)
    return run_id


# --- sign-up -------------------------------------------------------------------
def test_signing_up_creates_a_separate_account_and_signs_in(other):
    status = other.get("/api/auth/status").json()
    assert status["user"]["username"] == "second"
    assert status["signup_allowed"] is True


def test_the_first_account_stays_signed_in_in_its_own_browser(client, other):
    assert client.get("/api/auth/status").json()["user"]["username"] == TEST_USER["username"]


def test_sign_up_refuses_a_taken_username_in_any_case(client):
    from fastapi.testclient import TestClient

    response = TestClient(client.app).post(
        "/api/auth/register", json={"username": "TESTER", "password": "whatever-long-pw"}
    )
    assert response.status_code == 422
    assert "already exists" in response.json()["detail"]


def test_sign_up_can_be_turned_off(client, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(config, "ALLOW_SIGNUP", False)
    browser = TestClient(client.app)
    assert browser.get("/api/auth/status").json()["signup_allowed"] is False
    assert browser.post("/api/auth/register", json=OTHER).status_code == 403


def test_sign_up_before_any_account_exists_points_to_setup(api_env, stub_pipeline):
    from fastapi.testclient import TestClient

    from meeting_assistant.api.app import create_app
    from meeting_assistant.api.jobs import JobManager

    jobs = JobManager(run_batch=stub_pipeline.run_batch, run_live=stub_pipeline.run_live)
    app = create_app(jobs=jobs, preload_models=False, frontend_dist=api_env / "no-ui")
    with TestClient(app) as fresh:
        assert fresh.post("/api/auth/register", json=OTHER).status_code == 409


def test_account_creation_from_one_address_is_throttled(client, monkeypatch):
    from fastapi.testclient import TestClient

    from meeting_assistant.api.auth import LoginThrottle
    from meeting_assistant.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "signup_throttle", LoginThrottle(free_attempts=2))
    codes = [
        TestClient(client.app)
        .post("/api/auth/register", json={"username": f"user{i}", "password": "long-password-1"})
        .status_code
        for i in range(4)
    ]
    assert codes[:2] == [201, 201]
    assert codes[-1] == 429


# --- runs ------------------------------------------------------------------------
def test_a_new_account_starts_with_no_meetings(client, other, wait_for_job, tmp_path):
    _finished_run(client, wait_for_job, tmp_path)
    assert len(client.get("/api/runs").json()) == 1
    assert other.get("/api/runs").json() == []


@pytest.mark.parametrize(
    "suffix",
    ["", "/transcript", "/summary", "/artifacts/tagged", "/audio", "/events"],
)
def test_another_accounts_run_answers_as_if_it_did_not_exist(
    client, other, wait_for_job, tmp_path, suffix
):
    run_id = _finished_run(client, wait_for_job, tmp_path)
    assert client.get(f"/api/runs/{run_id}{suffix}").status_code == 200

    # Exactly the answer for a run that does not exist, so ids cannot be probed.
    response = other.get(f"/api/runs/{run_id}{suffix}")
    assert response.status_code == 404
    assert response.json() == {"detail": f"No such run: {run_id}"}


def test_another_accounts_run_cannot_be_resumed(client, other, wait_for_job, tmp_path):
    run_id = _finished_run(client, wait_for_job, tmp_path)
    response = other.post(f"/api/runs/{run_id}/resume", json={"force_stage": "summary"})
    assert response.status_code == 404


def test_each_accounts_runs_are_listed_only_for_it(client, other, wait_for_job, tmp_path):
    mine = _finished_run(client, wait_for_job, tmp_path)
    theirs = _finished_run(other, _waiter(other), tmp_path)
    assert [r["run_id"] for r in client.get("/api/runs").json()] == [mine]
    assert [r["run_id"] for r in other.get("/api/runs").json()] == [theirs]


def _waiter(browser):
    import time

    def wait(run_id, *, states=("finished", "failed"), timeout=10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = browser.get(f"/api/runs/{run_id}").json().get("job")
            if job and job["state"] in states:
                return job
            time.sleep(0.02)
        raise AssertionError(f"job for {run_id} never reached {states}")

    return wait


# --- recordings ------------------------------------------------------------------
def test_uploads_are_private_to_their_account(client, other, tmp_path):
    _upload(client, "standup.wav", _wav(tmp_path))
    assert [f["name"] for f in client.get("/api/audio").json()] == ["standup.wav"]
    assert other.get("/api/audio").json() == []


def test_another_accounts_recording_cannot_be_processed_by_name(client, other, tmp_path):
    _upload(client, "standup.wav", _wav(tmp_path))
    response = other.post("/api/runs/batch", json={"audio": "standup.wav"})
    assert response.status_code == 404


def test_two_accounts_can_upload_different_files_under_one_name(client, other, tmp_path):
    """Each account has its own folder, so names never collide across accounts."""
    assert _upload(client, "standup.wav", _wav(tmp_path, value=0)).status_code == 201
    assert _upload(other, "standup.wav", _wav(tmp_path, value=5)).status_code == 201


# --- jobs ------------------------------------------------------------------------
def test_jobs_are_listed_only_for_their_account(client, other, wait_for_job, tmp_path):
    _finished_run(client, wait_for_job, tmp_path)
    assert len(client.get("/api/jobs").json()) == 1
    assert other.get("/api/jobs").json() == []


def test_another_accounts_live_session_is_neither_shown_nor_stoppable(client, other):
    run_id = client.post("/api/live/start", json={}).json()["run_id"]
    try:
        assert other.get("/api/jobs/current").json() is None
        assert other.post("/api/live/stop").status_code == 409

        busy = other.post("/api/live/start", json={})
        assert busy.status_code == 409
        assert run_id not in busy.json()["detail"]
        assert "another account" in busy.json()["detail"]
    finally:
        assert client.post("/api/live/stop").status_code == 202


# --- unclaimed runs ------------------------------------------------------------------
def _cli_run(api_env, owner=None):
    """A run made outside the API (e.g. by `meeting-assistant batch`)."""
    from meeting_assistant.paths import new_run
    from meeting_assistant.pipeline.manifest import RunManifest

    paths = new_run("batch", "cli.wav", runs_dir=api_env / "runs")
    RunManifest.start(paths, mode="batch", owner=owner).set_status("partial")
    return paths


def test_with_one_account_unclaimed_runs_are_its_own(client, api_env):
    paths = _cli_run(api_env)
    assert client.post("/api/index/rebuild").status_code == 200
    assert [r["run_id"] for r in client.get("/api/runs").json()] == [paths.run_id]


def test_a_second_account_never_receives_earlier_unclaimed_runs(client, api_env):
    """Runs made while one account existed go to that account before the
    second account is created, never to the newcomer."""
    paths = _cli_run(api_env)
    from fastapi.testclient import TestClient

    second = TestClient(client.app)
    assert second.post("/api/auth/register", json=OTHER).status_code == 201

    assert second.get("/api/runs").json() == []
    assert second.get(f"/api/runs/{paths.run_id}").status_code == 404
    assert client.get(f"/api/runs/{paths.run_id}").status_code == 200


def test_with_two_accounts_unclaimed_runs_stay_hidden(client, other, api_env):
    paths = _cli_run(api_env)
    client.post("/api/index/rebuild")
    for browser in (client, other):
        assert browser.get("/api/runs").json() == []
        assert browser.get(f"/api/runs/{paths.run_id}").status_code == 404


def test_a_recreated_username_does_not_inherit_the_old_accounts_runs(
    client, other, wait_for_job, tmp_path
):
    theirs = _finished_run(other, _waiter(other), tmp_path)
    with accounts.open_accounts() as conn:
        accounts.delete_user(conn, OTHER["username"])

    from fastapi.testclient import TestClient

    reborn = TestClient(client.app)
    assert reborn.post("/api/auth/register", json=OTHER).status_code == 201
    assert reborn.get("/api/runs").json() == []
    assert reborn.get(f"/api/runs/{theirs}").status_code == 404


# --- upgrading existing data ---------------------------------------------------------
def test_accounts_from_before_uids_get_one_each(api_env):
    path = config.USERS_DB_PATH
    conn = sqlite3.connect(path)
    conn.executescript(
        """CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE
           COLLATE NOCASE, password_hash TEXT NOT NULL, created_at TEXT NOT NULL);
           INSERT INTO users (username, password_hash, created_at) VALUES ('a', 'x', 'now');
           INSERT INTO users (username, password_hash, created_at) VALUES ('b', 'x', 'now');"""
    )
    conn.commit()
    conn.close()

    with accounts.open_accounts() as conn:
        uids = [user.uid for user in accounts.list_users(conn)]
    assert len(uids) == 2 and all(uids) and uids[0] != uids[1]
    with accounts.open_accounts() as conn:  # idempotent: uids never change
        assert [user.uid for user in accounts.list_users(conn)] == uids


def test_an_index_from_before_owners_is_upgraded_from_the_manifests(api_env):
    from meeting_assistant.store import queries
    from meeting_assistant.store.db import open_db

    paths = _cli_run(api_env, owner="abc123")
    conn = sqlite3.connect(config.INDEX_DB_PATH)
    conn.executescript(
        """CREATE TABLE runs (run_id TEXT PRIMARY KEY, mode TEXT NOT NULL,
           status TEXT NOT NULL, data_origin TEXT NOT NULL, created_at TEXT,
           finished_at TEXT, git_commit TEXT, config_hash TEXT, audio_path TEXT,
           audio_sha256 TEXT, ingested_at TEXT NOT NULL);"""
    )
    conn.execute(
        "INSERT INTO runs VALUES (?, 'batch', 'partial', 'real_audio', NULL, NULL, NULL, "
        "NULL, NULL, NULL, 'now')",
        (paths.run_id,),
    )
    conn.commit()
    conn.close()

    with open_db() as conn:
        assert [r["run_id"] for r in queries.list_runs(conn, owner="abc123")] == [paths.run_id]
        assert queries.list_runs(conn, owner="someone-else") == []
