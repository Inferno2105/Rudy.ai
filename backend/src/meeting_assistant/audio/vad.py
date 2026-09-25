"""Voice activity detection configuration.

Uses ``webrtcvad`` — a small trained speech/non-speech classifier shipped as
part of the WebRTC project — rather than an energy/RMS-threshold heuristic.

That choice was contested once during exploration and is worth recording,
because the reasoning generalises beyond this one decision. ``webrtcvad`` is a
compiled C extension, and getting a prebuilt wheel for it on Windows briefly
looked like the harder path — Python 3.14 (the interpreter in use at the time)
had no such wheel, only a source build requiring a C++ toolchain. The
expedient fix was to swap in a pure-Python RMS-threshold check instead, and an
early version of this project did exactly that.

That swap was wrong, and the reason is specific to this project rather than
general advice: an RMS threshold is measurably worse at telling speech from
silence under real conditions — a fan, a keyboard, a quiet or distant
speaker — and this project's subject matter *is* ASR and diarization quality
under exactly those conditions. Trading signal-processing quality to sidestep a
packaging inconvenience would have quietly degraded the thing being measured.
The actual fix was to pin the interpreter to Python 3.12, where prebuilt wheels
exist for the whole audio/ML stack, and keep the trained classifier. That
Python pin is why ``pyproject.toml`` declares ``requires-python = ">=3.12,<3.13"``
rather than accepting whatever is newest.

``VAD_AGGRESSIVENESS`` (0 least aggressive, 3 most) and ``PAUSE_DURATION_SEC``
are both parameters of :class:`VadConfig` rather than hardcoded constants
specifically so they can be swept as evaluation ablations — the tradeoff between
chunk-boundary cleanliness and latency is an empirical question, not a fixed
choice.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VadConfig:
    """Parameters governing chunk-boundary detection.

    Args:
        sample_rate: webrtcvad accepts only 8000, 16000, 32000 or 48000 Hz.
        frame_duration_ms: webrtcvad accepts only 10, 20 or 30 ms frames.
        aggressiveness: 0-3. Higher filters more non-speech but is more likely
            to clip the start/end of quiet speech.
        pause_duration_sec: how much continuous silence ends a chunk. Sized to
            the ring buffer, so this also controls how much recent audio buffers
            before a chunk is confirmed to have started.
        min_chunk_duration_sec: chunks shorter than this are discarded as
            probable false triggers (a cough, a click) rather than passed
            through the expensive ASR/diarization pipeline.
        max_chunk_duration_sec: a hard cap so one long monologue with no pause
            does not become a single unbounded chunk — both because a very long
            chunk delays the first result and because diarization embeddings
            degrade on very long, heterogeneous audio.
    """

    sample_rate: int = 16000
    frame_duration_ms: int = 30
    aggressiveness: int = 2
    pause_duration_sec: float = 1.2
    min_chunk_duration_sec: float = 1.0
    max_chunk_duration_sec: float = 45.0

    def __post_init__(self) -> None:
        if self.sample_rate not in (8000, 16000, 32000, 48000):
            raise ValueError(
                f"webrtcvad requires 8000/16000/32000/48000 Hz, got {self.sample_rate}"
            )
        if self.frame_duration_ms not in (10, 20, 30):
            raise ValueError(
                f"webrtcvad requires 10/20/30 ms frames, got {self.frame_duration_ms}"
            )
        if not 0 <= self.aggressiveness <= 3:
            raise ValueError(f"aggressiveness must be 0-3, got {self.aggressiveness}")

    @property
    def frame_size(self) -> int:
        """Samples per frame."""
        return int(self.sample_rate * self.frame_duration_ms / 1000)

    @property
    def ring_buffer_frames(self) -> int:
        """How many frames of history to keep buffered before triggering a chunk."""
        return max(1, int(self.pause_duration_sec * 1000 / self.frame_duration_ms))


DEFAULT_VAD_CONFIG = VadConfig()


def create_vad(config: VadConfig = DEFAULT_VAD_CONFIG):
    """Construct a ``webrtcvad.Vad`` instance.

    Imported lazily so importing this module (and therefore
    :mod:`meeting_assistant.audio.live_capture`) does not require the compiled
    extension to be present just to inspect configuration or run unrelated
    tests.
    """
    import webrtcvad

    return webrtcvad.Vad(config.aggressiveness)


def is_speech(vad, frame_bytes: bytes, config: VadConfig = DEFAULT_VAD_CONFIG) -> bool:
    """Classify one frame as speech or not."""
    return vad.is_speech(frame_bytes, config.sample_rate)
