"""Per-run output layout and the artifact registry.

Every invocation of the pipeline gets its own directory under ``data/runs/``.
This exists because the previous design wrote all stages to fixed paths under a
single shared output folder, which meant a later run silently overwrote an
earlier one's intermediate files. That produced a state where, for example, the
tagged transcript held six segments from one recording while the aligned
transcript held three from a different one — artifacts that no longer described
the same meeting, with nothing to indicate it.

Two rules follow from that, and both are enforced by this module rather than by
convention:

1. Artifact filenames are *only* available through :data:`ARTIFACTS`, so a stage
   cannot invent its own output name. The writer and the reader of each artifact
   necessarily agree.
2. No function anywhere defaults an output path. A shared default output
   location is the clobbering bug written into a function signature, so there
   is deliberately no module-level path constant to default to.

Layout::

    data/runs/<run_id>/
    ├── manifest.json     provenance, per-stage status, timings, counts
    ├── run.log
    ├── chunks/           live mode only: chunk_0001.wav, ...
    └── artifacts/        01_transcript.json ... 10_meeting_metadata.json
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from meeting_assistant import config
from meeting_assistant.errors import ArtifactError

# Logical artifact name -> filename. The numeric prefixes make the pipeline order
# self-documenting when browsing a run directory, which matters more than it
# sounds: "why does the summary not mention what I said" is usually answered by
# reading the artifacts in order and finding where the content diverged.
ARTIFACTS: dict[str, str] = {
    "transcript": "01_transcript.json",
    "diarization": "02_diarization.json",
    "aligned": "03_aligned.json",
    "merged": "04_merged.json",
    "tagged": "05_tagged.json",
    "hinglish": "06_hinglish.json",
    "summary": "07_summary.json",
    "action_items": "08_action_items.json",
    "speaker_stats": "09_speaker_statistics.json",
    "metadata": "10_meeting_metadata.json",
}

# Stage order for the batch pipeline, expressed over artifact names. Language
# tagging MUST precede normalization: the tagger classifies segments by Unicode
# script (Devanagari vs Latin), and normalization rewrites Devanagari into Roman
# script, destroying that signal. Running them the other way round does not
# error — it silently labels every segment "English".
PIPELINE_ORDER: tuple[str, ...] = tuple(ARTIFACTS.keys())

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def slugify(text: str, *, max_length: int = 40) -> str:
    """Reduce arbitrary text to something safe for a directory name."""
    cleaned = _SLUG_RE.sub("-", text).strip("-")
    return (cleaned[:max_length] or "unnamed").lower()


@dataclass(frozen=True)
class RunPaths:
    """Resolved locations for one run. Frozen: a run's identity cannot change."""

    run_id: str
    root: Path

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def chunks_dir(self) -> Path:
        return self.root / "chunks"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def log_path(self) -> Path:
        return self.root / "run.log"

    def artifact(self, name: str) -> Path:
        """Resolve a logical artifact name to its path.

        Raises:
            ArtifactError: if ``name`` is not a known artifact. Failing loudly on
                a typo is the point — a silently-accepted unknown name would
                write a file nothing ever reads.
        """
        try:
            filename = ARTIFACTS[name]
        except KeyError:
            known = ", ".join(sorted(ARTIFACTS))
            raise ArtifactError(f"Unknown artifact {name!r}. Known: {known}") from None
        return self.artifacts_dir / filename

    def has(self, name: str) -> bool:
        """Whether the named artifact exists on disk."""
        return self.artifact(name).exists()

    def existing_artifacts(self) -> list[str]:
        """Logical names of the artifacts present, in pipeline order."""
        return [name for name in PIPELINE_ORDER if self.has(name)]


def make_run_id(mode: str, source: str | Path | None = None) -> str:
    """Build a run id of the form ``20260925-141203_batch_meeting-audio``.

    Timestamp first so directory listings sort chronologically; mode and source
    included so a run is recognisable without opening its manifest.
    """
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parts = [stamp, slugify(mode)]
    if source is not None:
        parts.append(slugify(Path(source).stem))
    return "_".join(parts)


def _runs_dir(runs_dir: Path | None = None) -> Path:
    return Path(runs_dir) if runs_dir is not None else config.RUNS_DIR


def new_run(
    mode: str,
    source: str | Path | None = None,
    *,
    runs_dir: Path | None = None,
) -> RunPaths:
    """Create and return a fresh run directory.

    Directories are created eagerly so a stage never has to think about whether
    its output location exists. The ``latest`` pointer is a text file rather than
    a symlink because creating symlinks on Windows needs Developer Mode or
    elevation.
    """
    base = _runs_dir(runs_dir)
    run_id = make_run_id(mode, source)

    root = base / run_id
    # Collisions need two runs inside the same second with the same source; a
    # suffix is cheaper than failing.
    suffix = 1
    while root.exists():
        suffix += 1
        root = base / f"{run_id}-{suffix}"
    run_id = root.name

    paths = RunPaths(run_id=run_id, root=root)
    paths.artifacts_dir.mkdir(parents=True, exist_ok=True)
    paths.chunks_dir.mkdir(parents=True, exist_ok=True)

    (base / "latest.txt").write_text(run_id + "\n", encoding="utf-8")
    return paths


def open_run(run_id: str, *, runs_dir: Path | None = None) -> RunPaths:
    """Open an existing run, for resuming or inspection.

    Raises:
        ArtifactError: if no such run directory exists.
    """
    root = _runs_dir(runs_dir) / run_id
    if not root.is_dir():
        raise ArtifactError(f"No such run: {run_id} (looked in {root.parent})")
    return RunPaths(run_id=run_id, root=root)


def latest_run(*, runs_dir: Path | None = None) -> RunPaths:
    """Open the most recent run.

    Prefers the ``latest.txt`` pointer, falling back to the newest directory name
    so the function still works if the pointer is missing or stale.
    """
    base = _runs_dir(runs_dir)
    pointer = base / "latest.txt"
    if pointer.exists():
        run_id = pointer.read_text(encoding="utf-8").strip()
        if run_id and (base / run_id).is_dir():
            return RunPaths(run_id=run_id, root=base / run_id)

    candidates = sorted((d for d in base.glob("*") if d.is_dir()), reverse=True)
    if not candidates:
        raise ArtifactError(f"No runs found in {base}")
    return RunPaths(run_id=candidates[0].name, root=candidates[0])


def list_runs(*, runs_dir: Path | None = None) -> list[RunPaths]:
    """All runs, newest first."""
    base = _runs_dir(runs_dir)
    if not base.is_dir():
        return []
    return [
        RunPaths(run_id=d.name, root=d)
        for d in sorted((d for d in base.glob("*") if d.is_dir()), reverse=True)
    ]
