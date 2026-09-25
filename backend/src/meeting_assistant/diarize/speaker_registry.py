"""Resolve chunk-local speaker labels to stable identities across chunks.

Live capture diarizes each chunk independently (see
:mod:`meeting_assistant.diarize.pyannote_diarizer`), so ``SPEAKER_00`` in chunk
two carries no relationship to ``SPEAKER_00`` in chunk one — diarization has no
memory between calls. :class:`SpeakerRegistry` gives voices that memory: it
embeds a sample of each chunk-local label's speech
(:mod:`meeting_assistant.diarize.embeddings`), compares that vector by cosine
similarity against every voice registered so far, and either attaches the
matching global id or mints a new one.

The output feeds directly into
:mod:`meeting_assistant.align.stitch`, which is what actually decides how a
segment's final label is written: segments this module marks
``speaker_resolution="global"`` are stitched with their global id unchanged;
everything else still gets the chunk-local ``C{n}_`` prefix that makes
unresolved ambiguity visible rather than implying a continuity the data does
not support. See that module's docstring for why the two mechanisms are
mutually exclusive rather than layered.

**Two resolution strategies, same output shape:**

:meth:`SpeakerRegistry.resolve_chunk` embeds the *entire chunk* as one vector —
one embedding call regardless of segment count, but only sound when a chunk
truly holds one speaker. A chunk containing two speakers produces one blended
vector and collapses every segment in it onto a single, confidently wrong
global id.

:meth:`SpeakerRegistry.resolve_segments` embeds each distinct local label's
single longest turn independently — one embedding call per label rather than
per chunk, correct regardless of how many speakers a chunk holds. This is the
default for batch mode and for any live chunk where local diarization reported
more than one label.

Either way, a window shorter than ``MIN_EMBED_SEC`` is left
``speaker_resolution="unresolved"`` rather than embedded: short windows give
unstable embeddings, and refusing to guess beats a confident, wrong merge.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

import numpy as np

from meeting_assistant import config
from meeting_assistant.align.alignment import UNKNOWN_SPEAKER
from meeting_assistant.align.stitch import RESOLUTION_GLOBAL, RESOLUTION_UNRESOLVED
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)

# Below this window duration (seconds), an embedding is considered unstable
# and the segment is left unresolved rather than matched or registered.
MIN_EMBED_SEC = config.SPEAKER_MIN_EMBED_SEC


class Embedder(Protocol):
    """``(audio_path, start, end) -> vector``. Matches :func:`embed_window`
    with its ``inference`` argument already bound, so tests can inject a
    trivial callable and never load a model."""

    def __call__(self, audio_path: str | Path, start: float, end: float) -> np.ndarray: ...


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity, ``0.0`` for a zero-norm vector rather than a NaN
    from dividing by zero. Real embeddings are never exactly zero; this only
    guards against a degenerate injected test vector."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def _span(segments: list[dict[str, Any]]) -> tuple[float, float] | None:
    """``(min start, max end)`` across ``segments``, or ``None`` if empty."""
    if not segments:
        return None
    starts = [s.get("start", 0.0) for s in segments]
    ends = [s.get("end", 0.0) for s in segments]
    return min(starts), max(ends)


def _longest_turn_per_label(segments: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """For each non-UNKNOWN speaker label, the ``(start, end)`` of its single
    longest segment — the window :meth:`SpeakerRegistry.resolve_segments`
    embeds to represent that label's voice."""
    longest: dict[str, tuple[float, float]] = {}
    best_duration: dict[str, float] = {}
    for segment in segments:
        label = segment.get("speaker")
        if not label or label == UNKNOWN_SPEAKER:
            continue
        duration = max(0.0, segment.get("end", 0.0) - segment.get("start", 0.0))
        if duration > best_duration.get(label, -1.0):
            best_duration[label] = duration
            longest[label] = (segment.get("start", 0.0), segment.get("end", 0.0))
    return longest


class SpeakerRegistry:
    """Tracks known voices as centroid vectors and matches new ones against them.

    Args:
        embedder: ``(audio_path, start, end) -> vector``. Left ``None`` to lazily
            build a real one (:mod:`meeting_assistant.diarize.embeddings`) on
            first use — so constructing a registry never loads a model, and
            tests can inject a trivial callable to exercise the matching logic
            in isolation.
        similarity_threshold: minimum cosine similarity to count as the same
            speaker. A planned evaluation ablation (see
            ``config.SPEAKER_SIMILARITY_THRESHOLD``); the default is a starting
            point, not a tuned value.
        ema_alpha: how much a new match moves a speaker's centroid:
            ``new = (1 - alpha) * old + alpha * observed``. Low values make
            identity stable against one noisy sample; high values adapt faster
            to a voice that drifts (different mic distance, background noise).
    """

    def __init__(
        self,
        embedder: Embedder | None = None,
        similarity_threshold: float = config.SPEAKER_SIMILARITY_THRESHOLD,
        ema_alpha: float = config.SPEAKER_EMA_ALPHA,
    ) -> None:
        self._embedder = embedder
        self.similarity_threshold = similarity_threshold
        self.ema_alpha = ema_alpha
        self._centroids: dict[str, np.ndarray] = {}
        self._match_counts: dict[str, int] = {}
        self._next_id = 1

    # -- pure matching logic, independent of audio or file I/O -------------
    def register_or_match(self, vector: np.ndarray) -> tuple[str, float]:
        """Match ``vector`` against known speakers, or register it as a new one.

        Returns:
            ``(global_id, similarity)``. ``similarity`` is the cosine
            similarity to the matched speaker's centroid, or ``1.0`` for a
            newly minted speaker (matched only to itself).
        """
        vector = np.asarray(vector, dtype=np.float32)

        best_id: str | None = None
        best_similarity = -1.0
        for speaker_id, centroid in self._centroids.items():
            similarity = _cosine_similarity(vector, centroid)
            if similarity > best_similarity:
                best_id, best_similarity = speaker_id, similarity

        if best_id is not None and best_similarity >= self.similarity_threshold:
            self._centroids[best_id] = (
                1 - self.ema_alpha
            ) * self._centroids[best_id] + self.ema_alpha * vector
            self._match_counts[best_id] += 1
            return best_id, round(best_similarity, 4)

        new_id = f"SPEAKER_G{self._next_id:02d}"
        self._next_id += 1
        self._centroids[new_id] = vector
        self._match_counts[new_id] = 1
        log.debug("Registered new global speaker %s", new_id)
        return new_id, 1.0

    # -- segment-level resolution --------------------------------------
    def resolve_chunk(
        self, audio_path: str | Path, local_segments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Resolve every segment in one chunk with a single whole-chunk embedding.

        See the module docstring for when this is (and is not) sound — prefer
        :meth:`resolve_segments` whenever a chunk may hold more than one
        speaker.
        """
        if not local_segments:
            return []

        span = _span(local_segments)
        if span is None or (span[1] - span[0]) < MIN_EMBED_SEC:
            return [self._mark_unresolved(s) for s in local_segments]

        start, end = span
        vector = self._embed(audio_path, start, end)
        global_id, similarity = self.register_or_match(vector)
        return [self._mark_global(s, global_id, similarity) for s in local_segments]

    def resolve_segments(
        self, audio_path: str | Path, local_segments: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Resolve each distinct local speaker label independently.

        One embedding call per distinct label (cached across that label's
        segments within this call), not one per segment. UNKNOWN segments are
        left unresolved without ever being embedded — there is no speaker
        voice to sample.
        """
        if not local_segments:
            return []

        longest_turn = _longest_turn_per_label(local_segments)
        resolved: list[dict[str, Any]] = []
        label_result: dict[str, tuple[str, float] | None] = {}

        for segment in local_segments:
            label = segment.get("speaker")
            if not label or label == UNKNOWN_SPEAKER:
                resolved.append(self._mark_unresolved(segment))
                continue

            if label not in label_result:
                turn_start, turn_end = longest_turn[label]
                if (turn_end - turn_start) < MIN_EMBED_SEC:
                    label_result[label] = None
                else:
                    vector = self._embed(audio_path, turn_start, turn_end)
                    label_result[label] = self.register_or_match(vector)

            result = label_result[label]
            if result is None:
                resolved.append(self._mark_unresolved(segment))
            else:
                global_id, similarity = result
                resolved.append(self._mark_global(segment, global_id, similarity))

        return resolved

    # -- persistence, for the manifest and mid-run debugging -----------
    def to_dict(self) -> dict[str, Any]:
        return {
            "similarity_threshold": self.similarity_threshold,
            "ema_alpha": self.ema_alpha,
            "next_id": self._next_id,
            "speakers": {
                speaker_id: {
                    "centroid": centroid.tolist(),
                    "match_count": self._match_counts[speaker_id],
                }
                for speaker_id, centroid in self._centroids.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], embedder: Embedder | None = None) -> SpeakerRegistry:
        registry = cls(
            embedder=embedder,
            similarity_threshold=data["similarity_threshold"],
            ema_alpha=data["ema_alpha"],
        )
        registry._next_id = data["next_id"]
        for speaker_id, info in data["speakers"].items():
            registry._centroids[speaker_id] = np.asarray(info["centroid"], dtype=np.float32)
            registry._match_counts[speaker_id] = info["match_count"]
        return registry

    def summary(self) -> dict[str, Any]:
        """Counts for the run manifest."""
        return {
            "global_speakers": len(self._centroids),
            "match_counts": dict(self._match_counts),
            "similarity_threshold": self.similarity_threshold,
        }

    # -- internals -------------------------------------------------------
    def _embed(self, audio_path: str | Path, start: float, end: float) -> np.ndarray:
        if self._embedder is None:
            self._embedder = self._build_default_embedder()
        return self._embedder(audio_path, start, end)

    @staticmethod
    def _build_default_embedder() -> Embedder:
        from meeting_assistant.diarize.embeddings import (
            build_inference,
            embed_window,
            load_embedding_model,
        )

        model = load_embedding_model()
        inference = build_inference(model)

        def embedder(audio_path: str | Path, start: float, end: float) -> np.ndarray:
            return embed_window(inference, audio_path, start, end)

        return embedder

    @staticmethod
    def _mark_global(segment: dict[str, Any], global_id: str, similarity: float) -> dict[str, Any]:
        resolved = dict(segment)
        resolved["local_speaker"] = segment.get("speaker")
        resolved["speaker"] = global_id
        resolved["speaker_confidence"] = similarity
        resolved["speaker_resolution"] = RESOLUTION_GLOBAL
        return resolved

    @staticmethod
    def _mark_unresolved(segment: dict[str, Any]) -> dict[str, Any]:
        resolved = dict(segment)
        resolved["speaker_resolution"] = RESOLUTION_UNRESOLVED
        return resolved
