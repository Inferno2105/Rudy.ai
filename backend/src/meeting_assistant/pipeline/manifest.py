"""The run manifest: the authoritative record of what happened during a run.

Every figure this project ever reports has to trace back to a specific run, and
the manifest is where that trace lives — provenance (git commit, config hash,
model versions, input audio hash), and a per-stage record of what ran, how long
it took, what it produced, and whether it succeeded. It is rewritten to disk
after every single stage, deliberately, so a crash mid-run never loses the
record of what already completed.

Stage status is one of three values, and the distinction matters for
interpreting a run:

``ok`` — the stage ran and produced its artifact.

``failed`` — the stage was attempted and raised. Recorded with its error so the
failure is diagnosable without re-running, but does not necessarily mean the
whole run failed — see ``HARD_STAGES`` in :mod:`meeting_assistant.pipeline.stages`.

``skipped`` — the stage was never attempted because an artifact it depends on
is missing (typically because an earlier *soft* stage failed). This is
distinct from ``failed`` on purpose: a skipped stage is a consequence, not an
independent problem, and collapsing the two would make it harder to see which
stage actually broke.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from meeting_assistant import provenance
from meeting_assistant.errors import ArtifactError
from meeting_assistant.io_utils import read_json, write_json
from meeting_assistant.paths import RunPaths

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

STAGE_OK = "ok"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"


@dataclass
class RunManifest:
    """In-memory manifest, backed by ``manifest.json`` in the run directory."""

    run_id: str
    mode: str
    paths: RunPaths
    data_origin: str
    provenance_block: dict[str, Any]
    stages: list[dict[str, Any]] = field(default_factory=list)
    status: str = STATUS_PARTIAL
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def start(
        cls,
        paths: RunPaths,
        *,
        mode: str,
        audio_path: str | None = None,
        data_origin: str = "real_audio",
    ) -> RunManifest:
        """Begin a new run: capture provenance and write the initial manifest.

        Called at the very start of a run, before any stage executes, so that
        even a run that crashes immediately still leaves a manifest recording
        what was about to happen and under what configuration.
        """
        manifest = cls(
            run_id=paths.run_id,
            mode=mode,
            paths=paths,
            data_origin=data_origin,
            provenance_block=provenance.capture(audio_path=audio_path),
        )
        manifest.save()
        return manifest

    @classmethod
    def load(cls, paths: RunPaths) -> RunManifest:
        """Reopen an existing run's manifest, for ``--resume``.

        Raises:
            ArtifactError: if the run has no manifest yet — it was never
                started, or died before the very first write.
        """
        if not paths.manifest_path.exists():
            raise ArtifactError(
                f"Run {paths.run_id} has no manifest yet; it cannot be resumed."
            )
        data = read_json(paths.manifest_path)
        return cls(
            run_id=data["run_id"],
            mode=data["mode"],
            paths=paths,
            data_origin=data.get("data_origin", "real_audio"),
            provenance_block=data.get("provenance", {}),
            stages=data.get("stages", []),
            status=data.get("status", STATUS_PARTIAL),
            extra=data.get("extra", {}),
        )

    def stage_status(self, name: str) -> str | None:
        """The most recently recorded status for a stage, or ``None`` if never run."""
        for entry in reversed(self.stages):
            if entry["name"] == name:
                return entry["status"]
        return None

    def record_stage(
        self,
        name: str,
        status: str,
        *,
        seconds: float = 0.0,
        outputs: list[str] | None = None,
        counts: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        """Record a stage's outcome and save immediately.

        A prior entry for the same stage name is replaced rather than
        duplicated — relevant when ``--force`` re-runs a stage that already
        has a (now stale) entry from an earlier attempt.
        """
        self.stages = [entry for entry in self.stages if entry["name"] != name]
        self.stages.append(
            {
                "name": name,
                "status": status,
                "seconds": round(seconds, 2),
                "outputs": outputs or [],
                "counts": counts or {},
                "error": error,
            }
        )
        self.save()

    def drop_stage(self, name: str) -> None:
        """Remove a stage's recorded outcome entirely, without saving.

        Used by ``--force``, alongside deleting the stage's artifact file, so a
        forced re-run has no trace of the invalidated attempt left behind —
        the alternative would let a stale "ok" entry coexist with a deleted
        artifact, which is exactly the kind of state that let two different
        recordings' artifacts drift apart in the previous design.
        """
        self.stages = [entry for entry in self.stages if entry["name"] != name]

    def set_status(self, status: str) -> None:
        self.status = status
        self.provenance_block["finished_at"] = datetime.now().isoformat(timespec="seconds")
        self.save()

    def set_extra(self, key: str, value: Any) -> None:
        """Attach run-kind-specific data (e.g. live capture's backlog stats)."""
        self.extra[key] = value
        self.save()

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "status": self.status,
            "data_origin": self.data_origin,
            "provenance": self.provenance_block,
            "stages": self.stages,
            "extra": self.extra,
        }

    def save(self) -> None:
        write_json(self.paths.manifest_path, self.as_dict())
