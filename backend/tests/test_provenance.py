"""Tests for provenance capture."""

from __future__ import annotations


def test_git_state_falls_back_to_the_build_time_commit(monkeypatch):
    """Inside a Docker image there is no repository; the commit recorded at
    build time keeps the run traceable."""
    from meeting_assistant import provenance

    monkeypatch.setattr(provenance, "_git", lambda *args, **kwargs: None)
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


def test_a_clean_tree_is_recorded_as_clean_not_unknown(monkeypatch):
    """`git status --porcelain` prints nothing for a clean tree; that is an
    answer, and must not be mistaken for git failing (which records None)."""
    from meeting_assistant import provenance

    def fake_git(*args, allow_empty=False):
        if args[0] == "status":
            return "" if allow_empty else None
        return "abc123" if args[0] == "rev-parse" else None

    monkeypatch.setattr(provenance, "_git", fake_git)
    assert provenance.git_state()["dirty"] is False

    def dirty_git(*args, allow_empty=False):
        return " M file.py" if args[0] == "status" else "abc123"

    monkeypatch.setattr(provenance, "_git", dirty_git)
    assert provenance.git_state()["dirty"] is True


def test_the_real_repository_reports_a_definite_dirty_flag():
    from meeting_assistant import provenance

    assert provenance.git_state()["dirty"] in (True, False)
