"""Tests for the run endpoints: listing, detail, artifact views and path safety."""

from __future__ import annotations

import pytest

from meeting_assistant.io_utils import read_json, write_json


@pytest.fixture
def finished_run(client, audio_file, wait_for_job):
    response = client.post("/api/runs/batch", json={"audio": audio_file.name})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    wait_for_job(run_id)
    return run_id


def test_run_list_starts_empty(client):
    assert client.get("/api/runs").json() == []


def test_a_finished_job_appears_in_the_run_list_without_a_manual_reindex(client, finished_run):
    runs = client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == [finished_run]
    assert runs[0]["status"] == "completed"


def test_run_list_filters_by_status(client, finished_run):
    assert len(client.get("/api/runs", params={"status": "completed"}).json()) == 1
    assert client.get("/api/runs", params={"status": "failed"}).json() == []


def test_run_list_rejects_an_out_of_range_limit(client):
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422


def test_run_detail_is_read_from_the_manifest(client, finished_run):
    detail = client.get(f"/api/runs/{finished_run}").json()
    assert detail["status"] == "completed"
    assert detail["mode"] == "batch"
    assert detail["data_origin"] == "real_audio"
    assert [s["name"] for s in detail["stages"]] == ["tagged", "summary"]
    assert detail["artifacts"] == ["tagged", "summary"]
    assert detail["job"]["state"] == "finished"
    assert detail["provenance"]["input"]["name"] == "meeting.wav"


def test_transcript_reports_which_artifact_it_came_from(client, finished_run):
    body = client.get(f"/api/runs/{finished_run}/transcript").json()
    assert body["source_artifact"] == "tagged"
    assert [s["text"] for s in body["segments"]] == ["namaste", "hello"]
    assert body["segments"][0]["language"] == "Hindi"


def test_summary_view(client, finished_run):
    body = client.get(f"/api/runs/{finished_run}/summary").json()
    assert body == {"summary": "A greeting.", "highlights": ["hello"], "key_decisions": []}


@pytest.mark.parametrize("view", ["action-items", "speakers", "metadata"])
def test_a_stage_that_has_not_run_is_404_not_empty(client, finished_run, view):
    """An absent artifact must read as "not produced", never as an empty result."""
    assert client.get(f"/api/runs/{finished_run}/{view}").status_code == 404


def test_raw_artifact_by_name(client, finished_run):
    response = client.get(f"/api/runs/{finished_run}/artifacts/tagged")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_raw_artifact_rejects_unknown_names(client, finished_run):
    response = client.get(f"/api/runs/{finished_run}/artifacts/manifest")
    assert response.status_code == 422


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/20200101-000000_batch_nope").status_code == 404


@pytest.mark.parametrize(
    "run_id",
    ["..", "..%2F..%2Fetc", "%2E%2E", "a..b", ".hidden", "C%3A%5CWindows", "a%5C..%5Cb"],
)
def test_run_ids_that_could_escape_the_runs_directory_are_refused(client, run_id):
    response = client.get(f"/api/runs/{run_id}")
    assert response.status_code in (400, 404)
    assert response.status_code != 200


def test_source_audio_is_served_for_a_batch_run(client, finished_run, audio_file):
    response = client.get(f"/api/runs/{finished_run}/audio")
    assert response.status_code == 200
    assert response.content == audio_file.read_bytes()


def test_source_audio_supports_range_requests_so_the_player_can_seek(client, finished_run):
    response = client.get(f"/api/runs/{finished_run}/audio", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert len(response.content) == 10


def test_source_audio_outside_the_audio_directory_is_never_served(
    client, finished_run, api_env, tmp_path
):
    """The path comes from a manifest on disk; edited, it must not become a
    way to read arbitrary files."""
    secret = tmp_path / "secret.wav"
    secret.write_bytes(b"not for you")
    manifest_path = api_env / "runs" / finished_run / "manifest.json"
    manifest = read_json(manifest_path)
    manifest["provenance"]["input"]["path"] = str(secret)
    write_json(manifest_path, manifest)

    assert client.get(f"/api/runs/{finished_run}/audio").status_code == 404


def test_index_rebuild_picks_up_runs_made_outside_the_api(client, api_env):
    from meeting_assistant.paths import new_run
    from meeting_assistant.pipeline.manifest import RunManifest

    paths = new_run("batch", "cli.wav", runs_dir=api_env / "runs")
    RunManifest.start(paths, mode="batch").set_status("completed")

    assert client.get("/api/runs").json() == []
    result = client.post("/api/index/rebuild").json()
    assert result == {"indexed": 1, "total": 1}
    assert len(client.get("/api/runs").json()) == 1


def test_eval_report_is_404_until_one_exists(client):
    assert client.get("/api/eval/report").status_code == 404


def test_eval_report_is_served_typed(client, api_env):
    report = {
        "generated_at": "2026-10-01T12:00:00",
        "git": {"commit": "abc", "dirty": False},
        "config_hashes": ["108acd72e0ed"],
        "clips": [
            {
                "clip_id": "clip01",
                "source": {"run_id": "r1", "git_commit": "abc", "config_hash": "108acd72e0ed"},
                "asr": {"wer_raw": {"wer": 0.21}, "cer_raw": {"cer": 0.08}},
                "diarization": {"der": 0.18, "confusion": 1.2},
                "a_future_family": {"x": 1},
            }
        ],
        "aggregate": {"num_clips": 1, "asr": {"wer_raw": {"wer": 0.21}}},
    }
    write_json(api_env / "eval" / "reports" / "latest.json", report)

    body = client.get("/api/eval/report").json()
    assert body["clips"][0]["source"]["run_id"] == "r1"
    assert body["clips"][0]["asr"]["wer_raw"]["wer"] == 0.21
    assert body["clips"][0]["a_future_family"] == {"x": 1}
    assert body["aggregate"]["num_clips"] == 1
