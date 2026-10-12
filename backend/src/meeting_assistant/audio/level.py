"""Microphone loudness for a live level meter.

The capture loop writes one reading per 30 ms frame; the API reads the
loudest one of the last tenth of a second, a few times a second, for the
meter in the Live page. Writing must cost next to nothing, because it runs
inside the frame loop that :mod:`meeting_assistant.audio.live_capture` must
never stall.

Levels are on a 0..1 scale that maps -60 dBFS (silence, a quiet room's hiss)
to 0 and full scale to 1, which is roughly how loud a level reads to the eye.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

import numpy as np

FLOOR_DB = -60.0
_KEEP_SEC = 1.0


def frame_level(frame: np.ndarray) -> float:
    """Loudness of one int16 frame, 0..1."""
    if frame.size == 0:
        return 0.0
    samples = frame.astype(np.float32)
    rms = float(np.sqrt(np.mean(samples * samples)))
    if rms < 1.0:
        return 0.0
    db = 20 * math.log10(rms / 32768.0)
    return min(1.0, max(0.0, (db - FLOOR_DB) / -FLOOR_DB))


class LevelMeter:
    """The recent loudness of a microphone, shared between threads."""

    def __init__(self, *, window_sec: float = 0.1) -> None:
        self.window_sec = window_sec
        self._readings: deque[tuple[float, float]] = deque()
        self._lock = threading.Lock()

    def update(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        level = frame_level(frame)
        with self._lock:
            self._readings.append((now, level))
            while self._readings and now - self._readings[0][0] > _KEEP_SEC:
                self._readings.popleft()

    def read(self) -> float:
        """The loudest reading of the last ``window_sec``; 0 when nothing is arriving."""
        now = time.monotonic()
        with self._lock:
            recent = [level for t, level in self._readings if now - t <= self.window_sec]
        return max(recent, default=0.0)
