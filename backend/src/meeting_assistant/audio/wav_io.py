"""Reading and writing WAV files.

Split out from live capture because both the recorder and anything that later
probes an existing recording (evaluation, provenance) need this, and neither
needs the VAD state machine that used to sit alongside it.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


def save_wav(path: str | Path, audio: np.ndarray, sample_rate: int) -> Path:
    """Write mono 16-bit PCM audio to ``path``, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())
    return path


def probe_wav(path: str | Path) -> dict[str, float | int]:
    """Read a WAV file's header without decoding its audio.

    Used for provenance (recording duration in the manifest) and for validating
    an uploaded file's sample rate before it reaches a model that assumes one.
    """
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()

    return {
        "duration_sec": round(frames / rate, 3) if rate else 0.0,
        "sample_rate": rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frames": frames,
    }
