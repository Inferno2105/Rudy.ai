"""Tests for bearer-token authentication on the HTTP API."""

from __future__ import annotations

import pytest
from conftest import API_TOKEN


@pytest.fixture
def anon(client):
    """Same app, but requests carry no Authorization header unless given one."""
    client.headers.pop("Authorization")
    return client


def test_health_is_public(anon):
    response = anon.get("/api/health")
    assert response.status_code == 200
    assert "version" in response.json()


def test_health_reveals_no_secrets(anon):
    body = anon.get("/api/health").text
    assert API_TOKEN not in body


def test_missing_token_is_rejected(anon):
    response = anon.get("/api/runs")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_wrong_token_is_rejected(anon):
    response = anon.get("/api/runs", headers={"Authorization": "Bearer not-the-token"})
    assert response.status_code == 401


def test_correct_token_is_accepted(anon):
    response = anon.get("/api/runs", headers={"Authorization": f"Bearer {API_TOKEN}"})
    assert response.status_code == 200


def test_scheme_is_case_insensitive(anon):
    response = anon.get("/api/runs", headers={"Authorization": f"bearer {API_TOKEN}"})
    assert response.status_code == 200


def test_wrong_scheme_is_rejected(anon):
    response = anon.get("/api/runs", headers={"Authorization": f"Basic {API_TOKEN}"})
    assert response.status_code == 401


def test_token_in_query_string_is_not_accepted(anon):
    """Query strings end up in access logs; the token must never work there."""
    response = anon.get(f"/api/runs?token={API_TOKEN}&access_token={API_TOKEN}")
    assert response.status_code == 401


def test_server_without_a_configured_token_rejects_everything(anon, monkeypatch):
    """A blank server token must never mean "auth disabled"."""
    from meeting_assistant import config

    monkeypatch.setattr(config, "API_TOKEN", None)
    response = anon.get("/api/runs", headers={"Authorization": "Bearer "})
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/audio"),
        ("get", "/api/devices"),
        ("get", "/api/jobs"),
        ("post", "/api/live/stop"),
        ("post", "/api/index/rebuild"),
        ("get", "/api/eval/report"),
        ("get", "/api/runs/anything"),
        ("get", "/api/runs/anything/events"),
    ],
)
def test_every_non_health_route_requires_the_token(anon, method, path):
    response = getattr(anon, method)(path)
    assert response.status_code == 401
