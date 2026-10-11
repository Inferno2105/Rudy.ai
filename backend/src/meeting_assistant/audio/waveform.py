"""A compact loudness envelope of a recording, for drawing its waveform.

The web player shows the whole meeting as a few hundred bars. Computing them
here keeps the browser from downloading and decoding a full recording (an hour
of 16 kHz audio is over 100 MB) just to draw a picture: the response is a few
kilobytes. Results are cached per file and modification time.
"""

from __future__ import annotations

import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

MIN_BINS = 32
MAX_BINS = 2000
# Decoding rate for non-WAV input: plenty for an envelope, and 4x less data.
_DECODE_RATE = 8000


def _read_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as reader:
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        rate = reader.getframerate()
        raw = reader.readframes(reader.getnframes())
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"Unsupported WAV sample width: {width} bytes")
    samples = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if width == 1:
        samples -= 128.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def _decode_any(path: Path) -> tuple[np.ndarray, int]:
    """Any format FFmpeg reads (mp3, m4a, flac...), as mono at 8 kHz."""
    import av

    chunks: list[np.ndarray] = []
    with av.open(str(path)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=_DECODE_RATE)
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray().reshape(-1))
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray().reshape(-1))
    samples = np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)
    return samples, _DECODE_RATE


def envelope(samples: np.ndarray, bins: int) -> list[float]:
    """Per-bin RMS loudness, scaled so the loudest bin is 1.0 (0..1, 3 decimals)."""
    if samples.size == 0:
        return [0.0] * bins
    edges = np.linspace(0, samples.size, bins + 1).astype(np.int64)
    rms = np.zeros(bins, dtype=np.float64)
    for index in range(bins):
        part = samples[edges[index] : edges[index + 1]]
        if part.size:
            rms[index] = float(np.sqrt(np.mean(np.square(part, dtype=np.float64))))
    peak = rms.max()
    if peak <= 0:
        return [0.0] * bins
    return [round(float(v), 3) for v in rms / peak]


@lru_cache(maxsize=32)
def _cached(path: str, mtime_ns: int, bins: int) -> tuple[float, tuple[float, ...]]:  # noqa: ARG001 -- mtime_ns is the cache key
    source = Path(path)
    samples, rate = _read_wav(source) if source.suffix.lower() == ".wav" else _decode_any(source)
    duration = samples.size / rate if rate else 0.0
    return round(duration, 3), tuple(envelope(samples, bins))


def waveform(path: Path, bins: int) -> tuple[float, list[float]]:
    """``(duration_sec, peaks)`` for ``path`` with ``bins`` values in 0..1."""
    bins = max(MIN_BINS, min(MAX_BINS, bins))
    duration, peaks = _cached(str(path), path.stat().st_mtime_ns, bins)
    return duration, list(peaks)
