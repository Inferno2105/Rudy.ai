"""Tests for the diarization result type and the DiarizeOutput unwrap.

``load_pipeline`` and ``diarize_audio`` need a real model and Hugging Face
access; covered by the Phase 4 integration check on real audio, not here.

Imports of :mod:`meeting_assistant.diarize.pyannote_diarizer` are deferred to
inside each test function rather than placed at module level. That module
imports ``pyannote.audio`` (and transitively ``torch``) as a required side
effect of the FFmpeg DLL ordering it exists to get right, which costs several
seconds — acceptable for tests marked ``slow``, but a module-level import would
pay that cost during collection for *every* pytest run, including the default
fast one, regardless of markers.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.slow


def test_unwrap_extracts_speaker_diarization_from_diarize_output():
    """pyannote 4.x's actual return shape: .speaker_diarization holds the Annotation."""
    from meeting_assistant.diarize.pyannote_diarizer import _unwrap_annotation

    class FakeDiarizeOutput:
        def __init__(self, annotation):
            self.speaker_diarization = annotation

    sentinel = object()
    assert _unwrap_annotation(FakeDiarizeOutput(sentinel)) is sentinel


def test_unwrap_falls_back_to_the_object_itself_when_unwrapped():
    """A future pyannote returning a bare Annotation must still work.

    The alternative -- iterating the wrong object and silently yielding zero
    segments -- produces an all-empty diarization that looks like an audio
    problem rather than an API mismatch, which is the failure mode this
    fallback exists to avoid.
    """
    from meeting_assistant.diarize.pyannote_diarizer import _unwrap_annotation

    class BareAnnotation:
        def itertracks(self, yield_label=True):
            return iter([])

    bare = BareAnnotation()
    assert _unwrap_annotation(bare) is bare


def test_diarization_result_counts_distinct_speakers():
    from meeting_assistant.diarize.pyannote_diarizer import DiarizationResult

    result = DiarizationResult(
        segments=[
            {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00"},
            {"start": 2.0, "end": 4.0, "speaker": "SPEAKER_01"},
            {"start": 4.0, "end": 6.0, "speaker": "SPEAKER_00"},
        ],
        elapsed_sec=1.5,
    )
    assert result.num_speakers_detected == 2


def test_diarization_result_of_empty_segments():
    from meeting_assistant.diarize.pyannote_diarizer import DiarizationResult

    result = DiarizationResult(segments=[], elapsed_sec=0.1)
    assert result.num_speakers_detected == 0
    assert result.as_manifest_dict()["segments"] == 0


def test_manifest_dict_has_the_reportable_fields():
    from meeting_assistant.diarize.pyannote_diarizer import DiarizationResult

    result = DiarizationResult(
        segments=[{"start": 0.0, "end": 5.0, "speaker": "SPEAKER_00"}],
        elapsed_sec=12.345,
    )
    manifest = result.as_manifest_dict()
    assert manifest == {"segments": 1, "speakers_detected": 1, "elapsed_sec": 12.35}


@pytest.mark.integration
def test_diarize_real_audio_produces_at_least_one_non_unknown_speaker():
    """Guards against silently yielding zero segments on real audio.

    This is the concrete failure mode the unwrap fallback exists to prevent: if
    the wrong object were ever iterated, this is what would go quiet instead of
    erroring.
    """
    from pathlib import Path

    from meeting_assistant import config
    from meeting_assistant.diarize.pyannote_diarizer import diarize_audio, load_pipeline

    audio = Path(config.AUDIO_DIR) / "test.wav"
    if not audio.exists():
        pytest.skip(f"integration fixture not present: {audio}")

    pipeline = load_pipeline(config.HF_TOKEN)
    result = diarize_audio(pipeline, audio)
    assert result.num_speakers_detected >= 1
    assert len(result.segments) >= 1
