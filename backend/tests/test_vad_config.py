"""Tests for VAD configuration.

Only the pure, deterministic parts of the audio module are unit-tested here —
the ring-buffer sizing and aggressiveness validation. Actual capture needs a
microphone and is covered by an integration test a human runs, not by this
suite (see docs/architecture.md for that policy).
"""

from __future__ import annotations

import dataclasses

import pytest

from meeting_assistant.audio.vad import VadConfig


def test_default_config_is_valid():
    VadConfig()  # must not raise


@pytest.mark.parametrize("rate", [8000, 16000, 32000, 48000])
def test_accepts_every_rate_webrtcvad_supports(rate):
    VadConfig(sample_rate=rate)


def test_rejects_unsupported_sample_rate():
    with pytest.raises(ValueError, match="8000/16000/32000/48000"):
        VadConfig(sample_rate=44100)


@pytest.mark.parametrize("duration", [10, 20, 30])
def test_accepts_every_frame_duration_webrtcvad_supports(duration):
    VadConfig(frame_duration_ms=duration)


def test_rejects_unsupported_frame_duration():
    with pytest.raises(ValueError, match="10/20/30"):
        VadConfig(frame_duration_ms=25)


@pytest.mark.parametrize("level", [0, 1, 2, 3])
def test_accepts_every_aggressiveness_level(level):
    VadConfig(aggressiveness=level)


@pytest.mark.parametrize("level", [-1, 4])
def test_rejects_aggressiveness_outside_zero_to_three(level):
    with pytest.raises(ValueError, match="aggressiveness"):
        VadConfig(aggressiveness=level)


def test_frame_size_matches_sample_rate_and_duration():
    config = VadConfig(sample_rate=16000, frame_duration_ms=30)
    assert config.frame_size == 480


def test_frame_size_at_a_different_rate():
    config = VadConfig(sample_rate=8000, frame_duration_ms=20)
    assert config.frame_size == 160


def test_ring_buffer_frames_matches_pause_duration():
    config = VadConfig(frame_duration_ms=30, pause_duration_sec=1.2)
    assert config.ring_buffer_frames == 40


def test_ring_buffer_frames_is_never_zero():
    """A zero-length ring buffer would make the trigger/pause ratios divide by zero."""
    config = VadConfig(frame_duration_ms=30, pause_duration_sec=0.001)
    assert config.ring_buffer_frames >= 1


def test_config_is_frozen():
    config = VadConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        config.aggressiveness = 3  # type: ignore[misc]
