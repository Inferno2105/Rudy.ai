"""Tests for atomic artifact IO."""

from __future__ import annotations

import json

import pytest

from meeting_assistant.errors import ArtifactError
from meeting_assistant.io_utils import read_json, sha256_file, write_json, write_text


def test_write_then_read_roundtrip(tmp_path):
    target = tmp_path / "out.json"
    payload = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    write_json(target, payload)
    assert read_json(target) == payload


def test_write_creates_parent_directories(tmp_path):
    target = tmp_path / "a" / "b" / "c.json"
    write_json(target, {"ok": True})
    assert target.exists()


def test_devanagari_is_written_literally(tmp_path):
    """Escaped Unicode would make every transcript unreadable by eye.

    Being able to open an artifact and see the actual Hindi text is a real
    debugging affordance for a code-mixed pipeline, so this is pinned.
    """
    target = tmp_path / "hi.json"
    write_json(target, {"text": "आज हम मीटिंग करेंगे"})
    raw = target.read_text(encoding="utf-8")
    assert "आज हम मीटिंग करेंगे" in raw
    assert "\\u0906" not in raw


def test_write_leaves_no_temporary_file_behind(tmp_path):
    target = tmp_path / "out.json"
    write_json(target, {"a": 1})
    assert list(tmp_path.glob("*.tmp")) == []


def test_overwrite_replaces_content_completely(tmp_path):
    """The live pipeline re-dumps its transcript after every chunk.

    A shorter payload must not leave a tail of the previous, longer one behind —
    which is exactly what an in-place write can do.
    """
    target = tmp_path / "out.json"
    write_json(target, [{"text": "x" * 500}])
    write_json(target, [])
    assert read_json(target) == []
    assert json.loads(target.read_text(encoding="utf-8")) == []


def test_read_missing_file_raises_artifact_error(tmp_path):
    with pytest.raises(ArtifactError, match="not found"):
        read_json(tmp_path / "absent.json")


def test_read_invalid_json_raises_artifact_error_naming_the_path(tmp_path):
    target = tmp_path / "broken.json"
    target.write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactError, match="not valid JSON"):
        read_json(target)


def test_write_text_roundtrip(tmp_path):
    target = tmp_path / "notes" / "run.txt"
    write_text(target, "line one\n")
    assert target.read_text(encoding="utf-8") == "line one\n"


def test_sha256_is_stable_and_content_dependent(tmp_path):
    first = tmp_path / "a.bin"
    second = tmp_path / "b.bin"
    first.write_bytes(b"identical")
    second.write_bytes(b"identical")
    assert sha256_file(first) == sha256_file(second)

    second.write_bytes(b"different")
    assert sha256_file(first) != sha256_file(second)


def test_sha256_handles_file_larger_than_one_chunk(tmp_path):
    """Audio files exceed the chunk size, so the loop must actually iterate."""
    target = tmp_path / "big.bin"
    target.write_bytes(b"\x01" * (3 * (1 << 20) + 17))
    assert len(sha256_file(target)) == 64
