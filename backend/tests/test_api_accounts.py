"""Tests for user accounts, sign-in sessions and the protections around them."""

from __future__ import annotations

import pytest
from conftest import TEST_USER

from meeting_assistant import accounts, config
from meeting_assistant.api.auth import LoginThrottle


@pytest.fixture
def anon(api_env, stub_pipeline):
    """A client over a fresh app with no account and no session."""
    from fastapi.testclient import TestClient

    from meeting_assistant.api.app import create_app
    from meeting_assistant.api.jobs import JobManager

    jobs = JobManager(run_batch=stub_pipeline.run_batch, run_live=stub_pipeline.run_live)
    app = create_app(jobs=jobs, preload_models=False, frontend_dist=api_env / "no-ui")
    with TestClient(app) as test_client:
        yield test_client


# --- password hashing ------------------------------------------------------
def test_passwords_are_hashed_with_a_salt():
    first = accounts.hash_password("same password")
    second = accounts.hash_password("same password")
    assert first != second and first.startswith("scrypt$")
    assert "same password" not in first
    assert accounts.verify_password("same password", first)
    assert not accounts.verify_password("other password", first)


def test_a_malformed_stored_hash_never_verifies():
    assert not accounts.verify_password("x", "not-a-hash")
    assert not accounts.verify_password("x", "bcrypt$1$2$3$4$5")


# --- first-account setup -----------------------------------------------------
def test_status_asks_for_setup_until_an_account_exists(anon):
    assert anon.get("/api/auth/status").json() == {
        "setup_required": True,
        "user": None,
        "signup_allowed": True,
    }
    response = anon.post("/api/auth/setup", json=TEST_USER)
    assert response.status_code == 201
    status = anon.get("/api/auth/status").json()
    assert status["setup_required"] is False
    assert status["user"]["username"] == "tester"


def test_setup_only_works_once(anon):
    assert anon.post("/api/auth/setup", json=TEST_USER).status_code == 201
    again = anon.post("/api/auth/setup", json={"username": "intruder", "password": "x" * 12})
    assert again.status_code == 409


@pytest.mark.parametrize(
    ("username", "password"),
    [("ab", "long-enough-pw"), ("has space", "long-enough-pw"), ("okname", "short")],
)
def test_setup_validates_username_and_password(anon, username, password):
    response = anon.post("/api/auth/setup", json={"username": username, "password": password})
    assert response.status_code == 422


# --- sessions ------------------------------------------------------------------
def test_the_session_cookie_is_httponly_and_samesite(anon):
    response = anon.post("/api/auth/setup", json=TEST_USER)
    cookie = response.headers["set-cookie"].lower()
    assert f"{config.SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_data_needs_a_session(anon):
    anon.post("/api/auth/setup", json=TEST_USER)
    assert anon.get("/api/runs").status_code == 200
    anon.cookies.clear()
    assert anon.get("/api/runs").status_code == 401


def test_login_and_logout(anon):
    anon.post("/api/auth/setup", json=TEST_USER)
    anon.post("/api/auth/logout")
    anon.cookies.clear()
    assert anon.get("/api/runs").status_code == 401

    assert anon.post("/api/auth/login", json=TEST_USER).status_code == 200
    assert anon.get("/api/runs").status_code == 200
    assert anon.post("/api/auth/logout").status_code == 204
    assert anon.get("/api/runs").status_code == 401


def test_usernames_are_case_insensitive(anon):
    anon.post("/api/auth/setup", json=TEST_USER)
    response = anon.post(
        "/api/auth/login", json={"username": "TESTER", "password": TEST_USER["password"]}
    )
    assert response.status_code == 200


def test_wrong_password_and_unknown_user_get_the_same_answer(anon):
    anon.post("/api/auth/setup", json=TEST_USER)
    wrong = anon.post("/api/auth/login", json={"username": "tester", "password": "nope-nope"})
    unknown = anon.post("/api/auth/login", json={"username": "ghost", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_an_expired_session_is_refused(anon, monkeypatch):
    monkeypatch.setattr(config, "SESSION_TTL_DAYS", -1)
    anon.post("/api/auth/setup", json=TEST_USER)
    assert anon.get("/api/runs").status_code == 401


def test_only_a_hash_of_the_session_token_is_stored(anon):
    anon.post("/api/auth/setup", json=TEST_USER)
    token = anon.cookies.get(config.SESSION_COOKIE)
    with accounts.open_accounts() as conn:
        stored = [row[0] for row in conn.execute("SELECT token_hash FROM sessions")]
    assert token and token not in stored


# --- password change ---------------------------------------------------------
def test_changing_the_password_needs_the_current_one(client):
    bad = client.post(
        "/api/auth/password",
        json={"current_password": "wrong-wrong", "new_password": "a-new-password"},
    )
    assert bad.status_code == 403
    good = client.post(
        "/api/auth/password",
        json={"current_password": TEST_USER["password"], "new_password": "a-new-password"},
    )
    assert good.status_code == 204
    assert client.get("/api/runs").status_code == 200  # this session survives
    client.post("/api/auth/logout")
    old = client.post("/api/auth/login", json=TEST_USER)
    assert old.status_code == 401


# --- protections ---------------------------------------------------------------
def test_repeated_wrong_passwords_are_slowed_down(anon):
    anon.post("/api/auth/setup", json=TEST_USER)
    anon.cookies.clear()
    bad = {"username": "tester", "password": "wrong-wrong"}
    codes = [anon.post("/api/auth/login", json=bad).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    blocked = anon.post("/api/auth/login", json=TEST_USER)
    assert blocked.status_code == 429  # even the right password waits
    assert int(blocked.headers["retry-after"]) > 0


def test_the_throttle_waits_longer_after_each_extra_failure():
    throttle = LoginThrottle(free_attempts=2, window_sec=100, max_wait_sec=1000)
    key = "u|ip"
    for t in (0, 1):
        throttle.failed(key, now=t)
    assert throttle.retry_after(key, now=1) == 15
    throttle.failed(key, now=20)
    assert throttle.retry_after(key, now=20) == 30
    throttle.succeeded(key)
    assert throttle.retry_after(key, now=21) == 0


def test_cross_site_posts_are_refused(client):
    response = client.post("/api/index/rebuild", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_same_site_posts_are_allowed(client):
    response = client.post("/api/index/rebuild", headers={"Origin": "http://testserver"})
    assert response.status_code == 200


def test_health_and_sign_in_need_no_session(anon):
    assert anon.get("/api/health").status_code == 200
    assert anon.get("/api/auth/status").status_code == 200
