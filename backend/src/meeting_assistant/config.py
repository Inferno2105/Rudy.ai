r"""Configuration: models, credentials, hosts and the data root.

This module holds *settings* only. Where artifacts get written is
:mod:`meeting_assistant.paths`, and that split is deliberate — the previous
iteration of this project kept nine module-level output-path constants here, all
stages read and wrote those same paths, and runs silently overwrote each other's
intermediate files. Keeping "what models to use" apart from "where this run
writes" means there is no shared output location for a stage to default to.

Values come from the environment, via a ``.env`` file at the repository root.
Nothing here is validated on import: importing this module has to stay safe for
tests and for ``--help``, so the checks live in :func:`validate_config` and run
explicitly at the start of a real invocation.

The docstring is raw (``r\"\"\"``) because the Windows paths mentioned below
contain backslash sequences that Python would otherwise read as escapes — the
earlier version of this file emitted a ``SyntaxWarning: invalid escape sequence
'\p'`` on every import for exactly that reason.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

from meeting_assistant.errors import ConfigError


def find_repo_root(start: Path | None = None) -> Path:
    """Walk upwards looking for the repository root.

    Identified by a ``.git`` directory, falling back to a directory containing
    both ``backend`` and ``data``. This is what lets ``data/`` live at the
    repository root and be shared between the backend, the frontend and the
    paper, while the package itself is installed from ``backend/src``.
    """
    start = start or Path(__file__).resolve()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists():
            return candidate
        if (candidate / "backend").is_dir() and (candidate / "data").is_dir():
            return candidate
    # Last resort: the current working directory. Only reached if the package is
    # installed non-editably outside a checkout.
    return Path.cwd()


REPO_ROOT = find_repo_root()

# Load .env from the repo root explicitly rather than relying on the current
# working directory, so the CLI behaves the same wherever it is invoked from.
load_dotenv(REPO_ROOT / ".env")


# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------
# No default. A placeholder string would be sent to Hugging Face and produce a
# confusing 401 rather than a clear "you have not configured a token" message.
HF_TOKEN: str | None = os.environ.get("HF_TOKEN") or None


# ---------------------------------------------------------------------------
# ASR (faster-whisper)
# ---------------------------------------------------------------------------
# large-v3 rather than medium: on Hindi and code-mixed audio, medium produced
# genuine word-level errors during testing (confusing "kaun"/"kyun", mangling
# "hopefully"), which no amount of downstream processing can repair. The
# comparison is retained as an evaluation ablation rather than a guess.
WHISPER_MODEL_SIZE: str = os.environ.get("WHISPER_MODEL_SIZE", "large-v3")
WHISPER_DEVICE: str = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE: str = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")


# ---------------------------------------------------------------------------
# Diarization and speaker embeddings (pyannote.audio 4.x)
# ---------------------------------------------------------------------------
DIARIZATION_MODEL: str = os.environ.get("DIARIZATION_MODEL", "pyannote/speaker-diarization-3.1")
# wespeaker-voxceleb-resnet34-LM, not the older pyannote/embedding repo: it is
# what pyannote/speaker-diarization-3.1 itself uses internally (see that
# pipeline's config.yaml), so the speaker registry compares voices in the same
# embedding space the diarizer already trusts, and in testing pyannote/embedding
# returned a 403 (gated separately) for a token that this model accepted fine.
EMBEDDING_MODEL: str = os.environ.get("EMBEDDING_MODEL", "pyannote/wespeaker-voxceleb-resnet34-LM")
# Where pyannote (diarization and speaker embeddings) runs: "cpu" or "cuda".
DIARIZATION_DEVICE: str = os.environ.get("DIARIZATION_DEVICE", "cpu")

# Cross-chunk speaker identity (diarize.speaker_registry). Exposed as settings
# rather than constants because the similarity threshold in particular is a
# planned evaluation ablation (swept 0.60-0.90) — the default below is a
# starting point, not a tuned value.
SPEAKER_SIMILARITY_THRESHOLD: float = float(os.environ.get("SPEAKER_SIMILARITY_THRESHOLD", "0.75"))
SPEAKER_EMA_ALPHA: float = float(os.environ.get("SPEAKER_EMA_ALPHA", "0.3"))
SPEAKER_MIN_EMBED_SEC: float = float(os.environ.get("SPEAKER_MIN_EMBED_SEC", "1.0"))


# ---------------------------------------------------------------------------
# Local LLM (Ollama)
# ---------------------------------------------------------------------------
# qwen2.5:7b over llama3.1:8b: markedly better at Hindi and Devanagari in
# testing. Also an evaluation ablation.
OLLAMA_MODEL: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_HOST: str = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


# ---------------------------------------------------------------------------
# Data locations
# ---------------------------------------------------------------------------
def _resolve_data_dir() -> Path:
    configured = os.environ.get("DATA_DIR", "data")
    path = Path(configured)
    return path if path.is_absolute() else REPO_ROOT / path


DATA_DIR: Path = _resolve_data_dir()
AUDIO_DIR: Path = DATA_DIR / "audio"
RUNS_DIR: Path = DATA_DIR / "runs"
EVAL_DIR: Path = DATA_DIR / "eval"
EXPERIMENTS_DIR: Path = DATA_DIR / "experiments"
INDEX_DB_PATH: Path = DATA_DIR / "index.sqlite"
# User accounts and login sessions. Not rebuildable from disk (unlike the
# index), so it lives in its own file; see meeting_assistant.accounts.
USERS_DB_PATH: Path = DATA_DIR / "users.sqlite"


# ---------------------------------------------------------------------------
# HTTP API
# ---------------------------------------------------------------------------
# Every route except health and login needs a signed-in user (see
# meeting_assistant.accounts). 127.0.0.1 keeps the server on this machine.
SESSION_COOKIE = "ma_session"
SESSION_TTL_DAYS: int = int(os.environ.get("SESSION_TTL_DAYS", "14"))
API_HOST: str = os.environ.get("API_HOST", "127.0.0.1")
API_PORT: int = int(os.environ.get("API_PORT", "8000"))
API_CORS_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.environ.get("API_CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
API_MAX_UPLOAD_MB: int = int(os.environ.get("API_MAX_UPLOAD_MB", "500"))
# The built web UI (`npm run build` in frontend/). Served at / when present.
FRONTEND_DIST: Path = REPO_ROOT / Path(  # a relative value is taken from the repo root
    os.environ.get("FRONTEND_DIST") or "frontend/dist"
)


# ---------------------------------------------------------------------------
# FFmpeg discovery (Windows / TorchCodec)
# ---------------------------------------------------------------------------
def _dir_has_ffmpeg_dlls(directory: str | Path) -> bool:
    """True if ``directory`` contains the FFmpeg shared libraries.

    This check is the whole point of the function. ``shutil.which("ffmpeg")``
    finding an executable does **not** imply the DLLs are available: a static
    FFmpeg build is a single self-contained ``ffmpeg.exe`` with no
    ``avcodec-*.dll`` beside it. TorchCodec needs the shared build, so accepting
    a directory purely because ffmpeg lives there leads to diarization failing
    with an opaque ``WinError 126`` while every diagnostic says ffmpeg was found.
    """
    return bool(glob.glob(str(Path(directory) / "avcodec-*.dll")))


def resolve_ffmpeg_bin_dir() -> Path | None:
    """Locate a directory containing FFmpeg's shared libraries, or ``None``.

    Resolution order: an explicit ``FFMPEG_BIN`` first, since someone who set it
    did so because auto-detection failed; then the directory of whatever
    ``ffmpeg`` is on PATH, but only if the DLLs are actually there.
    """
    configured = os.environ.get("FFMPEG_BIN")
    if configured:
        candidate = Path(configured)
        if candidate.is_dir() and _dir_has_ffmpeg_dlls(candidate):
            return candidate

    on_path = shutil.which("ffmpeg")
    if on_path:
        candidate = Path(on_path).parent
        if _dir_has_ffmpeg_dlls(candidate):
            return candidate

    return None


FFMPEG_BIN: Path | None = resolve_ffmpeg_bin_dir()


# ---------------------------------------------------------------------------
# Settings that affect output, for provenance hashing
# ---------------------------------------------------------------------------
def output_affecting_settings() -> dict[str, str]:
    """The settings that change a run's results.

    Hashed into each run's manifest so two runs can be compared meaningfully:
    if this dict differs, the runs are not the same experiment. Deliberately
    excludes paths and the token, which change nothing about the output.
    """
    return {
        "whisper_model_size": WHISPER_MODEL_SIZE,
        "whisper_device": WHISPER_DEVICE,
        "whisper_compute_type": WHISPER_COMPUTE_TYPE,
        "diarization_model": DIARIZATION_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "speaker_similarity_threshold": str(SPEAKER_SIMILARITY_THRESHOLD),
        "speaker_ema_alpha": str(SPEAKER_EMA_ALPHA),
        "ollama_model": OLLAMA_MODEL,
        # Only recorded when it differs from the default: GPU and CPU pyannote
        # are not bit-identical, so a GPU run must hash differently, but adding
        # the key unconditionally would change the hash of every existing
        # (CPU) run and break comparisons with them.
        **({"diarization_device": DIARIZATION_DEVICE} if DIARIZATION_DEVICE != "cpu" else {}),
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def list_problems(
    *,
    require_hf_token: bool = True,
    require_ffmpeg: bool = True,
    require_ollama: bool = False,
) -> list[str]:
    """Check prerequisites and return every problem found, without raising.

    This is the non-raising half of :func:`validate_config`, split out so a
    caller can use it for two different purposes with two different failure
    policies:

    1. A courtesy warning before a multi-stage run starts — reporting what is
       likely to fail without aborting the stages that do not actually need
       it. A batch run must not be destroyed by a missing Ollama server just
       because *some* of its later stages depend on one; the hard,
       Ollama-independent stages (transcription, alignment) should still run.
    2. A narrowly-scoped, raising check inside an individual pipeline stage —
       see :func:`validate_config` — so that stage's own failure is caught and
       recorded by the orchestrator exactly like any other stage failure,
       with a message that explains the remediation rather than a raw
       exception from deep inside a client library.
    """
    problems: list[str] = []

    if require_hf_token and not HF_TOKEN:
        problems.append(
            "HF_TOKEN is not set. Create a token at "
            "https://huggingface.co/settings/tokens and put it in .env as "
            "HF_TOKEN=hf_...  You must also accept the terms for the gated repos "
            f"{DIARIZATION_MODEL} and {EMBEDDING_MODEL}."
        )

    if require_ffmpeg and FFMPEG_BIN is None:
        if sys.platform == "win32":
            problems.append(
                "FFmpeg's shared libraries (avcodec-*.dll) were not found. "
                "A static ffmpeg.exe on PATH is not sufficient — TorchCodec "
                "loads the DLLs. Install the shared build "
                "(winget install Gyan.FFmpeg.Shared) and, if it is still not "
                "detected, set FFMPEG_BIN in .env to the folder containing "
                "avcodec-*.dll."
            )
        elif shutil.which("ffmpeg") is None:
            problems.append("ffmpeg was not found on PATH. Install it via your package manager.")

    if require_ollama:
        from meeting_assistant.llm.client import OllamaClient

        client = OllamaClient()
        ok, detail = client.health_check()
        if not ok:
            problems.append(
                f"Ollama is not usable at {OLLAMA_HOST}: {detail}. Start the "
                f"server and run `ollama pull {OLLAMA_MODEL}`."
            )

    return problems


def validate_config(
    *,
    require_hf_token: bool = True,
    require_ffmpeg: bool = True,
    require_ollama: bool = False,
) -> None:
    """Check prerequisites and raise one aggregated error listing every problem.

    Aggregating matters: fixing prerequisites one error message at a time, each
    needing another slow model load to discover the next, is a miserable setup
    experience. The flags scope the check to what the caller is actually about
    to do — a stage that does not touch Ollama must not be blocked by a
    missing Ollama server, which is why every pipeline stage that needs a
    credential or a server calls this scoped to only what *it* needs, rather
    than the orchestrator validating everything every stage might ever need
    before the run even starts.

    Raises:
        ConfigError: if anything required is missing.
    """
    problems = list_problems(
        require_hf_token=require_hf_token,
        require_ffmpeg=require_ffmpeg,
        require_ollama=require_ollama,
    )
    if problems:
        raise ConfigError(
            "Configuration problem(s) found:\n  - " + "\n  - ".join(problems)
        )
