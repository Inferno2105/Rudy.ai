"""Tests for the run layout and artifact registry.

These exist because the failure they guard against is silent. The previous design
had every stage write to fixed shared paths, so a second run overwrote the first
run's intermediates and left a directory whose files described two different
recordings with nothing to indicate it. Everything below is a property that makes
that state unreachable.
"""

from __future__ import annotations

import pytest

from meeting_assistant import paths as paths_mod
from meeting_assistant.errors import ArtifactError
from meeting_assistant.paths import ARTIFACTS, PIPELINE_ORDER


def test_artifact_names_and_filenames_are_one_to_one():
    """A duplicated filename would silently alias two stages onto one file."""
    assert len(set(ARTIFACTS.values())) == len(ARTIFACTS)
    assert len(set(ARTIFACTS.keys())) == len(ARTIFACTS)


def test_every_artifact_filename_is_numbered_in_pipeline_order():
    """The numeric prefixes must match declaration order, or they mislead."""
    prefixes = [ARTIFACTS[name].split("_")[0] for name in PIPELINE_ORDER]
    assert prefixes == sorted(prefixes)
    assert prefixes == [f"{i:02d}" for i in range(1, len(PIPELINE_ORDER) + 1)]


def test_language_tagging_precedes_normalization():
    """The ordering constraint that fails silently if broken.

    Language detection classifies segments by Unicode script; normalization
    rewrites Devanagari into Roman script and destroys that signal. Swapping them
    raises no error — it just labels every segment "English". Pinning the order
    here means a future reordering breaks a test instead of quietly degrading
    every result.
    """
    assert PIPELINE_ORDER.index("tagged") < PIPELINE_ORDER.index("hinglish")


def test_intel_stages_come_after_normalization():
    """Summary, action items and stats must read normalized text, not raw."""
    normalize_index = PIPELINE_ORDER.index("hinglish")
    for downstream in ("summary", "action_items", "speaker_stats", "metadata"):
        assert PIPELINE_ORDER.index(downstream) > normalize_index


def test_new_run_creates_the_expected_tree(runs_dir):
    run = paths_mod.new_run("batch", "meeting_one.wav", runs_dir=runs_dir)
    assert run.root.is_dir()
    assert run.artifacts_dir.is_dir()
    assert run.chunks_dir.is_dir()
    assert run.root.parent == runs_dir


def test_run_id_contains_mode_and_source_stem(runs_dir):
    run = paths_mod.new_run("batch", "Some Meeting.wav", runs_dir=runs_dir)
    assert "batch" in run.run_id
    assert "some-meeting" in run.run_id


def test_consecutive_runs_get_distinct_directories(runs_dir):
    """Two runs inside the same second must not collide.

    Run ids are timestamped to the second, so this is reachable in practice —
    notably when a sweep launches runs back to back.
    """
    first = paths_mod.new_run("batch", "same.wav", runs_dir=runs_dir)
    second = paths_mod.new_run("batch", "same.wav", runs_dir=runs_dir)
    assert first.run_id != second.run_id
    assert first.root != second.root


def test_artifact_resolves_known_name(runs_dir):
    run = paths_mod.new_run("batch", "a.wav", runs_dir=runs_dir)
    assert run.artifact("transcript").name == "01_transcript.json"
    assert run.artifact("transcript").parent == run.artifacts_dir


def test_artifact_rejects_unknown_name(runs_dir):
    """A typo must fail loudly, not create a file nothing reads."""
    run = paths_mod.new_run("batch", "a.wav", runs_dir=runs_dir)
    with pytest.raises(ArtifactError, match="Unknown artifact"):
        run.artifact("trancsript")


def test_has_and_existing_artifacts_reflect_disk(runs_dir):
    run = paths_mod.new_run("batch", "a.wav", runs_dir=runs_dir)
    assert run.existing_artifacts() == []
    assert not run.has("transcript")

    run.artifact("transcript").write_text("[]", encoding="utf-8")
    run.artifact("summary").write_text("{}", encoding="utf-8")

    assert run.has("transcript")
    # Reported in pipeline order, not filesystem order.
    assert run.existing_artifacts() == ["transcript", "summary"]


def test_latest_run_follows_the_pointer(runs_dir):
    paths_mod.new_run("batch", "first.wav", runs_dir=runs_dir)
    second = paths_mod.new_run("batch", "second.wav", runs_dir=runs_dir)
    assert paths_mod.latest_run(runs_dir=runs_dir).run_id == second.run_id


def test_latest_run_falls_back_when_pointer_is_stale(runs_dir):
    """A pointer at a deleted run must not break inspection."""
    run = paths_mod.new_run("batch", "only.wav", runs_dir=runs_dir)
    (runs_dir / "latest.txt").write_text("20200101-000000_batch_gone\n", encoding="utf-8")
    assert paths_mod.latest_run(runs_dir=runs_dir).run_id == run.run_id


def test_latest_run_raises_when_no_runs_exist(runs_dir):
    with pytest.raises(ArtifactError, match="No runs found"):
        paths_mod.latest_run(runs_dir=runs_dir)


def test_open_run_raises_for_missing_run(runs_dir):
    with pytest.raises(ArtifactError, match="No such run"):
        paths_mod.open_run("20200101-000000_batch_nope", runs_dir=runs_dir)


def test_list_runs_is_newest_first(runs_dir):
    ids = [paths_mod.new_run("batch", f"m{i}.wav", runs_dir=runs_dir).run_id for i in range(3)]
    listed = [run.run_id for run in paths_mod.list_runs(runs_dir=runs_dir)]
    assert listed == sorted(ids, reverse=True)


def test_list_runs_on_missing_directory_returns_empty(tmp_path):
    assert paths_mod.list_runs(runs_dir=tmp_path / "absent") == []


def test_run_paths_is_immutable(runs_dir):
    """A run's identity must not be reassignable after creation."""
    run = paths_mod.new_run("batch", "a.wav", runs_dir=runs_dir)
    with pytest.raises(Exception):
        run.run_id = "something-else"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Team Sync", "team-sync"),
        ("meeting_01.wav", "meeting_01.wav"),
        ("a/b\\c", "a-b-c"),
        ("   ", "unnamed"),
        ("!!!", "unnamed"),
    ],
)
def test_slugify(raw, expected):
    assert paths_mod.slugify(raw) == expected


def test_slugify_truncates():
    assert len(paths_mod.slugify("x" * 200)) == 40
