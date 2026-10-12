"""The microphone level meter."""

from __future__ import annotations

import numpy as np
import pytest

from meeting_assistant.audio.level import LevelMeter, frame_level


def test_silence_reads_zero_and_full_scale_reads_one():
    assert frame_level(np.zeros(480, dtype=np.int16)) == 0.0
    assert frame_level(np.full(480, 32767, dtype=np.int16)) == pytest.approx(1.0, abs=0.01)


def test_minus_thirty_decibels_is_half_way():
    amplitude = int(32768 * 10 ** (-30 / 20))
    assert frame_level(np.full(480, amplitude, dtype=np.int16)) == pytest.approx(0.5, abs=0.01)


def test_the_meter_reports_the_loudest_recent_frame():
    meter = LevelMeter(window_sec=10)
    meter.update(np.full(480, 300, dtype=np.int16))
    meter.update(np.full(480, 30000, dtype=np.int16))
    meter.update(np.full(480, 300, dtype=np.int16))
    assert meter.read() == pytest.approx(frame_level(np.full(480, 30000, dtype=np.int16)))


def test_a_meter_with_no_frames_reads_zero():
    assert LevelMeter().read() == 0.0
