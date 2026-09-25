"""Tests for SpeakerRegistry, with every vector injected -- plus one real-audio
integration check.

No model, no audio file, no FFmpeg for the bulk of this module. The registry's
own logic -- cosine matching, centroid drift, resolution strategy,
unresolved-window handling -- is pure once a vector exists, so it is
unit-tested against hand-built unit vectors and a spy embedder.

The one exception, marked ``integration`` like the diarizer's real-audio check,
answers the question none of that proves: does a real voice, diarized and
embedded from two genuinely independent audio files the way live capture's
chunks are, actually get recognized as the same speaker by the real embedding
model -- and a different speaker's voice not?
"""

from __future__ import annotations

import numpy as np
import pytest

from meeting_assistant.align.stitch import RESOLUTION_GLOBAL, RESOLUTION_UNRESOLVED
from meeting_assistant.diarize.speaker_registry import SpeakerRegistry

EX = np.array([1.0, 0.0, 0.0], dtype=np.float32)
EY = np.array([0.0, 1.0, 0.0], dtype=np.float32)


# ---------------------------------------------------------------------------
# register_or_match -- pure vector logic
# ---------------------------------------------------------------------------
def test_first_vector_is_registered_as_a_new_speaker():
    registry = SpeakerRegistry()
    speaker_id, similarity = registry.register_or_match(EX)
    assert speaker_id == "SPEAKER_G01"
    assert similarity == 1.0


def test_identical_vector_matches_the_same_speaker():
    registry = SpeakerRegistry()
    first_id, _ = registry.register_or_match(EX)
    second_id, similarity = registry.register_or_match(EX)
    assert second_id == first_id
    assert similarity == pytest.approx(1.0)


def test_orthogonal_vector_registers_a_new_speaker():
    registry = SpeakerRegistry()
    first_id, _ = registry.register_or_match(EX)
    second_id, _ = registry.register_or_match(EY)
    assert second_id != first_id


def test_vector_above_threshold_matches():
    # cos(theta) = 0.8 between EX and this vector.
    close = np.array([0.8, 0.6, 0.0], dtype=np.float32)
    registry = SpeakerRegistry(similarity_threshold=0.75)
    first_id, _ = registry.register_or_match(EX)
    second_id, similarity = registry.register_or_match(close)
    assert second_id == first_id
    assert similarity == pytest.approx(0.8, abs=1e-4)


def test_vector_below_threshold_registers_a_new_speaker():
    # cos(theta) = 0.7 between EX and this vector.
    far = np.array([0.7, np.sqrt(1 - 0.7**2), 0.0], dtype=np.float32)
    registry = SpeakerRegistry(similarity_threshold=0.75)
    first_id, _ = registry.register_or_match(EX)
    second_id, _ = registry.register_or_match(far)
    assert second_id != first_id


def test_a_match_moves_the_centroid_by_exactly_alpha():
    registry = SpeakerRegistry(similarity_threshold=0.5, ema_alpha=0.3)
    speaker_id, _ = registry.register_or_match(EX)
    observed = np.array([0.6, 0.8, 0.0], dtype=np.float32)  # cos(EX, observed) = 0.6 >= 0.5
    registry.register_or_match(observed)

    expected = 0.7 * EX + 0.3 * observed
    assert registry._centroids[speaker_id] == pytest.approx(expected)


def test_best_match_is_chosen_among_several_known_speakers():
    registry = SpeakerRegistry(similarity_threshold=0.9)
    registry.register_or_match(EX)
    registry.register_or_match(EY)
    ez = np.array([0.0, 0.0, 1.0], dtype=np.float32)
    registry.register_or_match(ez)

    # Slightly off EY -- must match SPEAKER_G02 (EY), not the others.
    near_ey = np.array([0.05, 0.999, 0.0], dtype=np.float32)
    matched_id, _ = registry.register_or_match(near_ey)
    assert matched_id == "SPEAKER_G02"


def test_zero_vector_never_matches_an_existing_speaker():
    # A zero vector has undefined cosine similarity to anything (0.0 by this
    # module's convention), so it can never clear a positive threshold and
    # always registers as its own new speaker rather than merging into one.
    registry = SpeakerRegistry(similarity_threshold=0.75)
    first_id, _ = registry.register_or_match(EX)
    zero = np.zeros(3, dtype=np.float32)
    second_id, similarity = registry.register_or_match(zero)
    assert second_id != first_id
    assert similarity == 1.0  # minted, not matched -- see register_or_match's docstring


# ---------------------------------------------------------------------------
# to_dict / from_dict
# ---------------------------------------------------------------------------
def test_round_trip_preserves_matching_behaviour():
    registry = SpeakerRegistry(similarity_threshold=0.75)
    registry.register_or_match(EX)
    data = registry.to_dict()

    reloaded = SpeakerRegistry.from_dict(data)
    matched_id, similarity = reloaded.register_or_match(EX)
    assert matched_id == "SPEAKER_G01"
    assert similarity == pytest.approx(1.0)


def test_round_trip_preserves_settings_and_next_id():
    registry = SpeakerRegistry(similarity_threshold=0.8, ema_alpha=0.4)
    registry.register_or_match(EX)
    registry.register_or_match(EY)  # sim=0 < 0.8 -> SPEAKER_G02

    reloaded = SpeakerRegistry.from_dict(registry.to_dict())
    assert reloaded.similarity_threshold == 0.8
    assert reloaded.ema_alpha == 0.4
    third_id, _ = reloaded.register_or_match(np.array([0.0, 0.0, 1.0], dtype=np.float32))
    assert third_id == "SPEAKER_G03"


# ---------------------------------------------------------------------------
# resolve_chunk
# ---------------------------------------------------------------------------
def _spy_embedder(vector=EX):
    calls = []

    def embedder(audio_path, start, end):
        calls.append((audio_path, start, end))
        return vector

    return embedder, calls


def test_resolve_chunk_embeds_the_whole_chunk_once():
    embedder, calls = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    segments = [
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "a"},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_01", "text": "b"},
    ]
    resolved = registry.resolve_chunk("chunk.wav", segments)

    assert len(calls) == 1
    assert calls[0] == ("chunk.wav", 0.0, 6.0)
    assert all(s["speaker_resolution"] == RESOLUTION_GLOBAL for s in resolved)
    assert all(s["speaker"] == "SPEAKER_G01" for s in resolved)
    assert resolved[0]["local_speaker"] == "SPEAKER_00"
    assert resolved[1]["local_speaker"] == "SPEAKER_01"


def test_resolve_chunk_leaves_a_short_chunk_unresolved_without_embedding():
    embedder, calls = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    segments = [{"start": 0.0, "end": 0.4, "speaker": "SPEAKER_00", "text": "hi"}]

    resolved = registry.resolve_chunk("chunk.wav", segments)

    assert calls == []
    assert resolved[0]["speaker_resolution"] == RESOLUTION_UNRESOLVED
    assert resolved[0]["speaker"] == "SPEAKER_00"  # untouched


def test_resolve_chunk_returns_empty_list_for_no_segments():
    embedder, calls = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    assert registry.resolve_chunk("chunk.wav", []) == []
    assert calls == []


def test_resolve_chunk_does_not_mutate_input():
    embedder, _ = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    original = [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "a"}]
    registry.resolve_chunk("chunk.wav", original)
    assert "speaker_resolution" not in original[0]


# ---------------------------------------------------------------------------
# resolve_segments
# ---------------------------------------------------------------------------
def test_resolve_segments_embeds_each_labels_longest_turn_once():
    calls = []

    def embedder(audio_path, start, end):
        calls.append((start, end))
        return EX if start == 0.0 else EY

    registry = SpeakerRegistry(embedder=embedder, similarity_threshold=0.9)
    segments = [
        {"start": 0.0, "end": 1.5, "speaker": "SPEAKER_00", "text": "a"},
        {"start": 1.5, "end": 2.0, "speaker": "SPEAKER_01", "text": "b"},
        {"start": 2.0, "end": 3.5, "speaker": "SPEAKER_00", "text": "c"},  # not the longest turn
        {"start": 3.5, "end": 5.5, "speaker": "SPEAKER_01", "text": "d"},  # SPEAKER_01's longest
    ]

    resolved = registry.resolve_segments("chunk.wav", segments)

    # One embedding call per distinct label, at that label's single longest turn.
    assert sorted(calls) == [(0.0, 1.5), (3.5, 5.5)]
    global_ids = {s["speaker"] for s in resolved}
    assert len(global_ids) == 2  # two distinct global speakers
    # Both SPEAKER_00 segments share the same resolved global id.
    speaker_00_ids = {s["speaker"] for s in resolved if s["local_speaker"] == "SPEAKER_00"}
    assert len(speaker_00_ids) == 1


def test_resolve_segments_leaves_unknown_unresolved_and_never_embeds_it():
    calls = []

    def embedder(audio_path, start, end):
        calls.append((start, end))
        return EX

    registry = SpeakerRegistry(embedder=embedder)
    segments = [
        {"start": 0.0, "end": 3.0, "speaker": "UNKNOWN", "text": "a"},
        {"start": 3.0, "end": 6.0, "speaker": "SPEAKER_00", "text": "b"},
    ]

    resolved = registry.resolve_segments("chunk.wav", segments)

    assert calls == [(3.0, 6.0)]
    assert resolved[0]["speaker_resolution"] == RESOLUTION_UNRESOLVED
    assert resolved[0]["speaker"] == "UNKNOWN"
    assert resolved[1]["speaker_resolution"] == RESOLUTION_GLOBAL


def test_resolve_segments_leaves_a_short_labels_turn_unresolved():
    embedder, calls = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    segments = [{"start": 0.0, "end": 0.5, "speaker": "SPEAKER_00", "text": "hi"}]

    resolved = registry.resolve_segments("chunk.wav", segments)

    assert calls == []
    assert resolved[0]["speaker_resolution"] == RESOLUTION_UNRESOLVED


def test_resolve_segments_returns_empty_list_for_no_segments():
    embedder, calls = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    assert registry.resolve_segments("chunk.wav", []) == []
    assert calls == []


def test_resolve_segments_does_not_mutate_input():
    embedder, _ = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    original = [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "a"}]
    registry.resolve_segments("chunk.wav", original)
    assert "speaker_resolution" not in original[0]


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------
def test_summary_reports_global_speaker_count_and_match_counts():
    registry = SpeakerRegistry(similarity_threshold=0.5)
    registry.register_or_match(EX)
    registry.register_or_match(EX)  # matches -> match_count 2
    registry.register_or_match(EY)  # sim 0 < 0.5 -> new speaker

    summary = registry.summary()
    assert summary["global_speakers"] == 2
    assert summary["match_counts"] == {"SPEAKER_G01": 2, "SPEAKER_G02": 1}


# ---------------------------------------------------------------------------
# Composition with align.stitch -- the actual point of speaker_resolution
# ---------------------------------------------------------------------------
def test_resolved_output_composes_correctly_with_stitch_offsetting():
    from meeting_assistant.align.stitch import offset_segments

    embedder, _ = _spy_embedder()
    registry = SpeakerRegistry(embedder=embedder)
    local_segments = [
        {"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "a"},
        {"start": 3.0, "end": 3.3, "speaker": "SPEAKER_01", "text": "b"},  # too short -> unresolved
    ]

    resolved = registry.resolve_segments("chunk.wav", local_segments)
    shifted = offset_segments(resolved, offset_sec=100.0, chunk_index=2)

    globally_resolved = next(s for s in shifted if s.get("local_speaker") == "SPEAKER_00")
    unresolved = next(s for s in shifted if s["speaker_resolution"] == RESOLUTION_UNRESOLVED)

    # Global id is kept exactly as resolved -- no C2_ prefix.
    assert globally_resolved["speaker"] == "SPEAKER_G01"
    assert not globally_resolved["speaker"].startswith("C2_")
    # Unresolved segment still gets the chunk-local prefix, making the
    # ambiguity visible rather than silently dropped.
    assert unresolved["speaker"] == "C2_SPEAKER_01"


# ---------------------------------------------------------------------------
# Real audio, real embedding model -- the one thing injected vectors cannot prove
# ---------------------------------------------------------------------------
@pytest.mark.integration
def test_registry_recognizes_a_recurring_speaker_across_independent_chunks(tmp_path):
    """The scenario the registry exists for: two chunks diarized and embedded
    completely independently, exactly as live capture's chunks are -- their
    diarization labels (``SPEAKER_00``/``SPEAKER_01``) carry no relationship to
    each other at all, since each diarization call starts from nothing.

    Measured on ``data/audio/test.wav`` split at 16s (2 known real speakers
    with alternating turns spanning both halves, per the diarizer's own
    real-audio check): at the default 0.75 threshold, one of the two real
    speakers is correctly recognized across the split (a cosine match a naive
    per-chunk label could never produce) and the other registers as a new
    speaker. That partial-recognition result -- not perfect, not useless -- is
    reported here as a real, current measurement rather than asserted away;
    tuning ``similarity_threshold`` against a labelled set is exactly the
    planned Phase 10 ablation, not something this phase claims to have solved.
    """
    import wave
    from pathlib import Path

    from meeting_assistant import config
    from meeting_assistant.diarize.embeddings import (
        build_inference,
        embed_window,
        load_embedding_model,
    )
    from meeting_assistant.diarize.pyannote_diarizer import diarize_audio, load_pipeline

    source = Path(config.AUDIO_DIR) / "test.wav"
    if not source.exists():
        pytest.skip(f"integration fixture not present: {source}")

    def slice_wav(dst_path: Path, start_sec: float, end_sec: float) -> Path:
        with wave.open(str(source), "rb") as src:
            channels = src.getnchannels()
            sampwidth = src.getsampwidth()
            rate = src.getframerate()
            src.setpos(int(start_sec * rate))
            frames = src.readframes(int((end_sec - start_sec) * rate))
        with wave.open(str(dst_path), "wb") as out:
            out.setnchannels(channels)
            out.setsampwidth(sampwidth)
            out.setframerate(rate)
            out.writeframes(frames)
        return dst_path

    chunk1 = slice_wav(tmp_path / "chunk1.wav", 0.0, 16.0)
    chunk2 = slice_wav(tmp_path / "chunk2.wav", 16.0, 32.0)

    pipeline = load_pipeline(config.HF_TOKEN)
    local1 = diarize_audio(pipeline, chunk1, num_speakers=2).segments
    local2 = diarize_audio(pipeline, chunk2, num_speakers=2).segments
    assert local1 and local2

    embedding_model = load_embedding_model()
    inference = build_inference(embedding_model)

    def embedder(audio_path, start, end):
        return embed_window(inference, audio_path, start, end)

    registry = SpeakerRegistry(embedder=embedder)
    resolved1 = registry.resolve_segments(chunk1, local1)
    resolved2 = registry.resolve_segments(chunk2, local2)

    ids1 = {s["speaker"] for s in resolved1 if s["speaker_resolution"] == RESOLUTION_GLOBAL}
    ids2 = {s["speaker"] for s in resolved2 if s["speaker_resolution"] == RESOLUTION_GLOBAL}

    # Chunk-local labels alone could never produce this: SPEAKER_00 in chunk2
    # has no necessary relationship to SPEAKER_00 in chunk1. Voice matching
    # must recognize at least one of the two real speakers across the split.
    assert ids1 & ids2, "no global speaker recurred across the two independent chunks"
    # And it must not fragment two real speakers into more global identities
    # than there are distinct (chunk, local label) pairs to begin with -- 2
    # labels per chunk, 2 chunks, so 4 is the ceiling a registry that resolved
    # nothing at all would produce.
    assert len(registry._centroids) <= 4
