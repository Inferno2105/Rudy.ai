"""Tests for provenance capture."""

from __future__ import annotations


def test_git_state_falls_back_to_the_build_time_commit(monkeypatch):
    """Inside a Docker image there is no repository; the commit recorded at
    build time keeps the run traceable."""
    from meeting_assistant import provenance

    monkeypatch.setattr(provenance, "_git", lambda *args: None)
    monkeypatch.setenv("MEETING_ASSISTANT_GIT_COMMIT", "abc123")
    monkeypatch.setenv("MEETING_ASSISTANT_GIT_DIRTY", "false")
    state = provenance.git_state()
    assert state["commit"] == "abc123"
    assert state["dirty"] is False
    assert state["source"] == "build"


def test_pyannote_device_only_enters_the_hash_when_not_cpu(monkeypatch):
    from meeting_assistant import config, provenance

    baseline = provenance.config_hash()
    assert "diarization_device" not in config.output_affecting_settings()
    monkeypatch.setattr(config, "DIARIZATION_DEVICE", "cuda")
    assert config.output_affecting_settings()["diarization_device"] == "cuda"
    assert provenance.config_hash() != baseline
