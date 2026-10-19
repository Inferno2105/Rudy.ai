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

**Executions.** A batch run can be resumed, so its stages may be produced by
more than one process, possibly under different code or settings. The
``provenance`` block describes *execution 0*, the one that created the run;
each resume that continues earlier work appends its own provenance record to
``resumes`` (execution 1, 2, ...), and every stage entry records the
``execution`` that produced it. ``consistency`` then states whether the stages
on disk share one configuration and one clean commit -- the condition for a
run's numbers to be attributable to a single, regenerable setup. A resume that
would change the output-affecting configuration is refused unless explicitly
allowed (see :meth:`RunManifest.check_resumable`), and resuming against a
different recording is always refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from meeting_assistant import config, provenance
from meeting_assistant.errors import ArtifactError, ProvenanceError
from meeting_assistant.io_utils import read_json, sha256_file, write_json
from meeting_assistant.paths import ARTIFACTS, RunPaths

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"

STAGE_OK = "ok"
STAGE_FAILED = "failed"
STAGE_SKIPPED = "skipped"

# Where a run's audio came from. "synthetic" covers generated speech
# (text-to-speech clips) and hand-written transcripts: it is scored only as
# its own set, never mixed into the results for real recordings.
DATA_ORIGINS = ("real_audio", "synthetic")


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
    resumes: list[dict[str, Any]] = field(default_factory=list)
    # The account that owns the run (``accounts.User.uid``), or ``None`` for a
    # run nobody has claimed yet. Decides who can see the run in the web UI;
    # not part of provenance, because it does not affect any output.
    owner: str | None = None
    # Which execution new stage entries are attributed to. Not serialized: it
    # belongs to the process holding this object, not to the run.
    current_execution: int = 0

    @classmethod
    def start(
        cls,
        paths: RunPaths,
        *,
        mode: str,
        audio_path: str | None = None,
        data_origin: str = "real_audio",
        owner: str | None = None,
    ) -> RunManifest:
        """Begin a new run: capture provenance and write the initial manifest.

        Called at the very start of a run, before any stage executes, so that
        even a run that crashes immediately still leaves a manifest recording
        what was about to happen and under what configuration.
        """
        if data_origin not in DATA_ORIGINS:
            raise ValueError(f"data_origin must be one of {DATA_ORIGINS}, not {data_origin!r}")
        manifest = cls(
            run_id=paths.run_id,
            mode=mode,
            paths=paths,
            data_origin=data_origin,
            provenance_block=provenance.capture(audio_path=audio_path),
            owner=owner,
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
            resumes=data.get("resumes", []),
            owner=data.get("owner"),
        )

    def _execution_record(self, index: int) -> dict[str, Any]:
        """Provenance of execution ``index`` (0 is the run's own block)."""
        if index == 0:
            return self.provenance_block
        return self.resumes[index - 1] if 0 < index <= len(self.resumes) else {}

    def _surviving_stages(self, force_stage: str | None) -> list[dict[str, Any]]:
        """Stage entries that will still exist after an optional ``--force``."""
        if force_stage is None or force_stage not in ARTIFACTS:
            return list(self.stages)
        names = list(ARTIFACTS)
        dropped = set(names[names.index(force_stage) :])
        return [entry for entry in self.stages if entry["name"] not in dropped]

    def check_resumable(
        self,
        *,
        audio_path: str | Path | None = None,
        force_stage: str | None = None,
        allow_mixed_config: bool = False,
    ) -> None:
        """Refuse a resume that would make this run's provenance untrue.

        Read-only, so a caller (the API) can check before queueing anything.

        Args:
            audio_path: the recording the resume would read; defaults to the
                one recorded at creation.
            force_stage: the resume's ``--force`` stage, if any. Stages it will
                delete are not earlier work the resume must stay consistent with.
            allow_mixed_config: continue even though the configuration
                differs. The run is then marked inconsistent and excluded from
                evaluation, so this is for debugging, never for results.

        Raises:
            ProvenanceError: the recording's content differs from the one the
                run was created from (never overridable: it would be a
                different meeting), or the output-affecting configuration
                differs from that of the stages that will be kept.
        """
        recorded_input = self.provenance_block.get("input") or {}
        candidate = Path(audio_path) if audio_path is not None else None
        if candidate is None and recorded_input.get("path"):
            candidate = Path(recorded_input["path"])
        recorded_sha = recorded_input.get("sha256")
        if candidate is not None and candidate.exists() and recorded_sha:
            if sha256_file(candidate) != recorded_sha:
                raise ProvenanceError(
                    f"{candidate} is not the recording run {self.run_id} was created "
                    "from (its sha256 differs). Start a new run for it instead."
                )

        surviving = self._surviving_stages(force_stage)
        if not surviving or allow_mixed_config:
            return
        current = provenance.config_hash()
        owners = sorted({entry.get("execution", 0) for entry in surviving})
        recorded = {self._execution_record(i).get("config_hash") for i in owners}
        if recorded != {current}:
            changed = _changed_settings(
                self._execution_record(owners[-1]).get("settings") or {},
                config.output_affecting_settings(),
            )
            detail = f" (changed: {'; '.join(changed)})" if changed else ""
            raise ProvenanceError(
                f"Run {self.run_id} was produced under config "
                f"{', '.join(sorted(map(str, recorded)))}, but the current config is "
                f"{current}{detail}. Resuming would mix outputs of different "
                "configurations in one run. Start a new run, re-run every stage with "
                "--force transcript, or pass --allow-mixed-config for a debugging-only "
                "run that is excluded from evaluation."
            )

    def begin_execution(self, *, allow_mixed_config: bool = False) -> None:
        """Record the provenance of the process about to run stages.

        Call after :meth:`check_resumable` and after any ``--force``
        invalidation. If no stage output survives (a run created but never
        executed, as the API does, or ``--force`` from the first stage), the
        run's own provenance block is re-captured: it should describe the
        execution that produces every artifact, not the moment the directory
        was made. Otherwise a resume record is appended and new stage entries
        are attributed to it.
        """
        snapshot = provenance.capture()
        if not self.stages:
            if "input" in self.provenance_block:
                snapshot["input"] = self.provenance_block["input"]
            self.provenance_block = snapshot
            self.current_execution = 0
        else:
            snapshot["execution"] = len(self.resumes) + 1
            snapshot["allow_mixed_config"] = allow_mixed_config
            self.resumes.append(snapshot)
            self.current_execution = snapshot["execution"]
        self.save()

    def consistency(self) -> dict[str, Any]:
        """Whether the recorded stages share one configuration and one commit.

        ``code`` is only asserted across executions: a single execution is
        consistent with itself (a dirty tree is recorded in its provenance
        either way), but two executions are known to have run the same code
        only if they share a commit and neither tree was dirty. Manifests
        written before executions were recorded attribute every stage to
        execution 0 and so report as consistent; that is all that can be known
        about them.
        """
        owners = sorted({entry.get("execution", 0) for entry in self.stages}) or [0]
        records = [self._execution_record(i) for i in owners]
        same_config = len({r.get("config_hash") for r in records}) == 1
        commits = {(r.get("git") or {}).get("commit") for r in records}
        any_dirty = any((r.get("git") or {}).get("dirty") for r in records)
        same_code = len(owners) == 1 or (len(commits) == 1 and not any_dirty)
        return {"executions": owners, "config": same_config, "code": same_code}

    def evaluation_ineligibility(self, *, allow_synthetic: bool = False) -> str | None:
        """Why this run must not feed a reported number, or ``None`` if it may.

        ``allow_synthetic`` lets a synthetic run through for scoring in its own
        set (``meeting-assistant eval`` reports it apart from real recordings);
        the configuration and code checks apply to both sets alike.
        """
        if self.data_origin != "real_audio" and not allow_synthetic:
            return f"data_origin is {self.data_origin!r}, not 'real_audio'"
        state = self.consistency()
        if not state["config"]:
            return (
                "its stages were produced under different configurations "
                f"(executions {state['executions']})"
            )
        if not state["code"]:
            return (
                "its stages were produced by different or uncommitted code "
                f"(executions {state['executions']})"
            )
        return None

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
                "execution": self.current_execution,
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
            "owner": self.owner,
            "status": self.status,
            "data_origin": self.data_origin,
            "provenance": self.provenance_block,
            "resumes": self.resumes,
            "consistency": self.consistency(),
            "stages": self.stages,
            "extra": self.extra,
        }

    def save(self) -> None:
        write_json(self.paths.manifest_path, self.as_dict())


def _changed_settings(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [
        f"{k} {before.get(k)!r} -> {after.get(k)!r}"
        for k in keys
        if before.get(k) != after.get(k)
    ]
