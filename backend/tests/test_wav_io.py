"""Tests for WAV file writing and probing."""

from __future__ import annotations

import numpy as np

from meeting_assistant.audio.wav_io import probe_wav, save_wav


def _tone(seconds: float, sample_rate: int = 16000) -> np.ndarray:
    n = int(seconds * sample_rate)
    return np.zeros(n, dtype=np.int16)


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "chunk.wav"
    save_wav(path, _tone(1.0), sample_rate=16000)
    assert path.exists()


def test_probe_reports_duration_matching_what_was_written(tmp_path):
    path = tmp_path / "chunk.wav"
    save_wav(path, _tone(2.5, sample_rate=16000), sample_rate=16000)
    info = probe_wav(path)
    assert info["duration_sec"] == 2.5
    assert info["sample_rate"] == 16000


def test_probe_reports_channel_and_width(tmp_path):
    path = tmp_path / "chunk.wav"
    save_wav(path, _tone(1.0), sample_rate=8000)
    info = probe_wav(path)
    assert info["channels"] == 1
    assert info["sample_width_bytes"] == 2


def test_probe_at_a_different_sample_rate(tmp_path):
    path = tmp_path / "chunk.wav"
    save_wav(path, _tone(1.0, sample_rate=48000), sample_rate=48000)
    info = probe_wav(path)
    assert info["sample_rate"] == 48000
    assert info["duration_sec"] == 1.0


def test_roundtrip_preserves_frame_count(tmp_path):
    audio = _tone(0.333, sample_rate=16000)
    path = tmp_path / "chunk.wav"
    save_wav(path, audio, sample_rate=16000)
    info = probe_wav(path)
    assert info["frames"] == len(audio)
