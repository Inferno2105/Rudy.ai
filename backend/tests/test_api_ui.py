"""Tests for serving the built web UI, and for the OpenAPI contract the UI is
generated from."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def ui_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>ui</title>", encoding="utf-8")
    (dist / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    return dist


@pytest.fixture
def ui_client(api_env, stub_pipeline, ui_dist):
    from fastapi.testclient import TestClient

    from meeting_assistant.api.app import create_app
    from meeting_assistant.api.jobs import JobManager

    jobs = JobManager(run_batch=stub_pipeline.run_batch, run_live=stub_pipeline.run_live)
    app = create_app(jobs=jobs, preload_models=False, frontend_dist=ui_dist)
    with TestClient(app) as test_client:
        yield test_client


def test_index_is_served_at_the_root(ui_client):
    response = ui_client.get("/")
    assert response.status_code == 200
    assert "<title>ui</title>" in response.text


def test_client_side_routes_fall_back_to_index(ui_client):
    """Reloading /runs/<id> in the browser must load the app, not 404."""
    response = ui_client.get("/runs/20261001-120000_batch_x")
    assert response.status_code == 200
    assert "<title>ui</title>" in response.text


def test_static_files_are_served_as_themselves(ui_client):
    assert ui_client.get("/assets/app-abc123.js").text == "console.log(1)"
    assert ui_client.get("/favicon.svg").text == "<svg/>"


def test_unknown_api_paths_are_json_404s_not_the_ui(ui_client):
    response = ui_client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_api_routes_still_win_over_the_fallback(ui_client):
    assert ui_client.get("/api/health").json()["ok"] in (True, False)
    response = ui_client.get("/api/runs")
    assert response.status_code == 401  # an API route (not the UI), needing sign-in
    assert response.headers["content-type"].startswith("application/json")


def test_the_ui_page_carries_a_restrictive_csp(ui_client):
    csp = ui_client.get("/").headers["content-security-policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_every_response_carries_nosniff(ui_client):
    for path in ("/", "/api/health", "/assets/app-abc123.js"):
        assert ui_client.get(path).headers["x-content-type-options"] == "nosniff"


def test_the_fallback_cannot_read_outside_the_build(ui_client, tmp_path):
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    response = ui_client.get("/..%2Fsecret.txt")
    assert "nope" not in response.text


def test_without_a_build_the_root_is_not_found(client):
    assert client.get("/").status_code == 404
    assert client.app.state.ui_served is False


# ---------------------------------------------------------------------------
# OpenAPI contract
# ---------------------------------------------------------------------------
def test_sse_payload_models_are_in_the_schema(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    for name in ("ManifestEvent", "SegmentsEvent", "EndEvent", "Job", "EvalReport"):
        assert name in schemas


def test_the_committed_schema_matches_the_app(client):
    """The frontend's types are generated from the committed openapi.json; if
    the API changes without regenerating it, the UI would compile against a
    contract the server no longer honours. Fix: `meeting-assistant openapi`."""
    from meeting_assistant import config

    committed = config.REPO_ROOT / "frontend" / "src" / "api" / "openapi.json"
    live = client.get("/openapi.json").json()
    assert json.loads(committed.read_text(encoding="utf-8")) == live


def test_ui_routes_are_not_part_of_the_api_schema(ui_client):
    paths = ui_client.get("/openapi.json").json()["paths"]
    assert all(path.startswith("/api/") for path in paths)


def test_the_ui_and_sign_in_are_public_but_data_is_not(ui_client):
    assert ui_client.get("/").status_code == 200
    assert ui_client.get("/login").status_code == 200  # client-side route
    assert ui_client.get("/api/health").status_code == 200
    assert ui_client.get("/api/auth/status").status_code == 200
    for path in ("/api/runs", "/api/audio", "/api/jobs", "/api/jobs/current", "/api/devices"):
        assert ui_client.get(path).status_code == 401, path
