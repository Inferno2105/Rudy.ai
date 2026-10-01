"""Tests for atomic artifact IO."""

from __future__ import annotations

import json
import sys

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


# ---------------------------------------------------------------------------
# Atomic replace while the target is being read (the HTTP API's situation)
# ---------------------------------------------------------------------------
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows file semantics")


def test_replace_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """A reader that did not allow deletion blocks even a POSIX-semantics
    rename briefly; the write must wait it out rather than fail the stage."""
    from meeting_assistant import io_utils

    monkeypatch.setattr(io_utils.sys, "platform", "win32")
    monkeypatch.setattr(io_utils, "_REPLACE_FIRST_DELAY_SEC", 0.0)
    real_once = io_utils._replace_once
    failures = iter([PermissionError(13, "sharing violation")] * 2)

    def flaky_once(src, dst):
        error = next(failures, None)
        if error is not None:
            raise error
        real_once(src, dst)

    monkeypatch.setattr(io_utils, "_replace_once", flaky_once)
    write_json(tmp_path / "m.json", {"ok": True})
    assert read_json(tmp_path / "m.json") == {"ok": True}


def test_replace_gives_up_after_bounded_retries(tmp_path, monkeypatch):
    from meeting_assistant import io_utils

    monkeypatch.setattr(io_utils.sys, "platform", "win32")
    monkeypatch.setattr(io_utils, "_REPLACE_FIRST_DELAY_SEC", 0.0)
    calls = []

    def always_denied(src, dst):
        calls.append(1)
        raise PermissionError(13, "sharing violation")

    monkeypatch.setattr(io_utils, "_replace_once", always_denied)
    with pytest.raises(PermissionError):
        write_json(tmp_path / "m.json", {"ok": True})
    assert len(calls) == io_utils._REPLACE_ATTEMPTS


def test_replace_does_not_retry_off_windows(tmp_path, monkeypatch):
    """Elsewhere PermissionError means a real permissions problem, not a
    reader holding the file -- retrying would only delay the error."""
    from meeting_assistant import io_utils

    calls = []
    monkeypatch.setattr(io_utils.sys, "platform", "linux")

    def denied(src, dst):
        calls.append(1)
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(io_utils, "_replace_once", denied)
    with pytest.raises(PermissionError):
        write_json(tmp_path / "m.json", {"ok": True})
    assert calls == [1]


@windows_only
def test_replace_succeeds_while_a_shared_reader_holds_the_file_open(tmp_path):
    """The core property: a reader mid-read never blocks the writer, and keeps
    seeing the complete old version (never a mixture)."""
    from meeting_assistant.io_utils import _open_for_read

    target = tmp_path / "manifest.json"
    write_json(target, {"v": 0})
    with _open_for_read(target) as held:
        write_json(target, {"v": 1})
        assert json.load(held) == {"v": 0}
    assert read_json(target) == {"v": 1}


@windows_only
def test_falls_back_to_os_replace_on_a_filesystem_without_posix_rename(
    tmp_path, monkeypatch
):
    from meeting_assistant import _win_fileio, io_utils

    def unsupported(src, dst):
        raise OSError(None, "not supported", str(dst), 50)

    monkeypatch.setattr(_win_fileio, "posix_replace", unsupported)
    monkeypatch.setattr(io_utils, "_posix_replace_supported", True)

    write_json(tmp_path / "m.json", {"ok": True})

    assert read_json(tmp_path / "m.json") == {"ok": True}
    assert io_utils._posix_replace_supported is False  # remembered for the process


def test_concurrent_readers_never_break_writes(tmp_path):
    """The real scenario, made adversarial: three threads re-reading a
    manifest in a tight loop while it is rewritten 300 times. Every write must
    land, and no read may ever see a partial file."""
    import threading

    target = tmp_path / "manifest.json"
    write_json(target, {"n": 0})
    stop = threading.Event()
    bad_reads: list[object] = []

    def reader():
        while not stop.is_set():
            try:
                data = read_json(target)
            except ArtifactError as exc:
                bad_reads.append(exc)
            else:
                if set(data) != {"n"}:
                    bad_reads.append(data)

    threads = [threading.Thread(target=reader, daemon=True) for _ in range(3)]
    for thread in threads:
        thread.start()
    try:
        for n in range(1, 300):
            write_json(target, {"n": n})
    finally:
        stop.set()
        for thread in threads:
            thread.join()

    assert read_json(target) == {"n": 299}
    assert bad_reads == []
