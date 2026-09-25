"""Speaker voice embeddings via pyannote.audio.

Does the same kind of job as :mod:`meeting_assistant.diarize.pyannote_diarizer`
but answers a different question: not *when did someone speak* but *what does
that voice sound like*, as one fixed-length vector. Diarization has no memory
between independent runs — chunk two's ``SPEAKER_00`` is not known to be the
same person as chunk one's — so
:mod:`meeting_assistant.diarize.speaker_registry` uses vectors from this module
to recognize a recurring voice across those chunks and give it one stable
identity.

Deliberately isolated from ``speaker_registry`` the same way
``pyannote_diarizer`` is isolated from ``alignment``: this module owns model
loading and raw vector extraction, nothing else, so the registry's matching
logic can be unit-tested against injected vectors without ever loading a model.

**Import order is load-bearing here, exactly as in ``pyannote_diarizer``.**
``ensure_ffmpeg_dlls()`` must run before ``pyannote.audio`` is imported, because
pyannote decodes audio through TorchCodec, which resolves FFmpeg's DLLs at
C-extension load time on Windows. See
:mod:`meeting_assistant.bootstrap.ffmpeg_dll` for the full explanation.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from meeting_assistant.bootstrap.ffmpeg_dll import ensure_ffmpeg_dlls

ensure_ffmpeg_dlls()  # side effect REQUIRED before the next import

from pyannote.audio import Inference, Model  # noqa: E402
from pyannote.core import Segment  # noqa: E402

from meeting_assistant import config  # noqa: E402
from meeting_assistant.logging_setup import get_logger  # noqa: E402

log = get_logger(__name__)


def load_embedding_model(hf_token: str | None = None, model: str | None = None) -> Model:
    """Load the pretrained speaker embedding model.

    Defaults to ``config.EMBEDDING_MODEL``
    (``pyannote/wespeaker-voxceleb-resnet34-LM``), the same embedding model
    ``pyannote/speaker-diarization-3.1`` uses internally — comparing voices in
    the space the diarizer already trusts, rather than a second, unrelated
    embedding space.
    """
    hf_token = hf_token if hf_token is not None else config.HF_TOKEN
    model_id = model or config.EMBEDDING_MODEL

    log.info("Loading speaker embedding model: %s", model_id)
    started = time.perf_counter()
    loaded = Model.from_pretrained(model_id, token=hf_token)
    log.info("Embedding model loaded in %.1fs", time.perf_counter() - started)
    return loaded


def build_inference(model: Model) -> Inference:
    """A whole-window inference engine over ``model``.

    ``window="whole"`` makes both :func:`embed_file` and :func:`embed_window`
    return one fixed-length vector rather than a sliding-window sequence — the
    single vector per voice sample that
    :class:`~meeting_assistant.diarize.speaker_registry.SpeakerRegistry`
    compares by cosine similarity. A sliding-window sequence would need its own
    aggregation step before it could be compared at all.
    """
    return Inference(model, window="whole")


def embed_file(inference: Inference, audio_path: str | Path) -> np.ndarray:
    """Embed an entire audio file as one vector."""
    vector = inference(str(audio_path))
    return np.asarray(vector, dtype=np.float32)


def embed_window(
    inference: Inference, audio_path: str | Path, start: float, end: float
) -> np.ndarray:
    """Embed the ``[start, end]`` slice (seconds) of ``audio_path`` as one vector."""
    vector = inference.crop(str(audio_path), Segment(start, end))
    return np.asarray(vector, dtype=np.float32)
