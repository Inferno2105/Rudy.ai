"""Background execution of pipeline runs for the API: one job at a time.

A batch run takes minutes and a live session runs until stopped, so neither
can execute inside a request. Jobs go on a FIFO queue drained by **exactly one
worker thread**, for the same reason the live pipeline has exactly one
processing worker: faster-whisper and pyannote are not documented as
thread-safe, and two runs on one CPU would only contend for the same cores.
Batch and resume requests queue behind whatever is running; a live start is
refused while anything is busy, because a recording that silently waits ten
minutes in a queue before the microphone opens is worse than a clear "busy".

Job state lives only in memory. The run directory is the durable record: if
the server restarts, queued jobs are lost but their runs survive with status
``partial``, and ``POST /api/runs/{id}/resume`` picks them up -- the same
recovery path as the CLI's ``--resume``.
"""

from __future__ import annotations

import itertools
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from meeting_assistant.api.schemas.jobs import Job, JobKind, JobState
from meeting_assistant.errors import ProvenanceError
from meeting_assistant.logging_setup import get_logger
from meeting_assistant.paths import RunPaths

log = get_logger(__name__)

_ACTIVE: frozenset[str] = frozenset({"queued", "running", "stopping"})
_HISTORY_LIMIT = 100
_STOP = object()


class BusyError(RuntimeError):
    """A job cannot start because another one is queued or running."""


class NoLiveJobError(RuntimeError):
    """A live stop was requested but no live session is active."""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class _JobRecord:
    job_id: str
    kind: JobKind
    run_id: str
    work: Callable[[], object]
    state: JobState = "queued"
    error: str | None = None
    submitted_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    stop_event: threading.Event | None = None

    def snapshot(self) -> Job:
        return Job(
            job_id=self.job_id,
            kind=self.kind,
            run_id=self.run_id,
            state=self.state,
            error=self.error,
            submitted_at=self.submitted_at,
            started_at=self.started_at,
            finished_at=self.finished_at,
        )


def _default_run_batch(audio_path, opts):
    from meeting_assistant.pipeline.batch import run_batch

    return run_batch(audio_path, opts)


def _default_run_live(opts, *, paths, stop_event):
    from meeting_assistant.pipeline.live import run_live

    return run_live(opts, paths=paths, stop_event=stop_event)


def _default_create_batch_run(audio_path: Path) -> RunPaths:
    from meeting_assistant.pipeline.batch import create_batch_run

    return create_batch_run(audio_path)


def _default_create_live_run() -> RunPaths:
    from meeting_assistant.pipeline.live import create_live_run

    return create_live_run()


def _default_on_finished(paths: RunPaths) -> None:
    """Re-index the run so the run list reflects it without a manual reindex."""
    from meeting_assistant.store.db import open_db
    from meeting_assistant.store.ingest import ingest_run

    with open_db() as conn:
        ingest_run(conn, paths)


def _mark_failed(paths: RunPaths, error: str) -> None:
    """Record an exception that escaped the pipeline entirely.

    Stage failures never reach here -- the orchestrators catch and record
    those themselves. This is for what escapes them (the audio file vanished
    before a queued job started, a model failed to load), which would
    otherwise leave the manifest at its initial ``partial`` and look
    resumable rather than broken.
    """
    from meeting_assistant.pipeline.manifest import STATUS_FAILED, RunManifest

    try:
        manifest = RunManifest.load(paths)
        if manifest.status != STATUS_FAILED:
            manifest.set_extra("error", error)
            manifest.set_status(STATUS_FAILED)
    except Exception:  # noqa: BLE001 -- best effort; the job record still carries the error
        log.exception("Could not record failure in the manifest of %s", paths.run_id)


class JobManager:
    """Owns the job queue and its single worker thread.

    The pipeline entry points are constructor arguments so tests can replace
    them with stubs that write a few artifacts instead of loading models.
    """

    def __init__(
        self,
        *,
        run_batch: Callable = _default_run_batch,
        run_live: Callable = _default_run_live,
        create_batch_run: Callable[[Path], RunPaths] = _default_create_batch_run,
        create_live_run: Callable[[], RunPaths] = _default_create_live_run,
        on_finished: Callable[[RunPaths], None] = _default_on_finished,
    ) -> None:
        self._run_batch = run_batch
        self._run_live = run_live
        self._create_batch_run = create_batch_run
        self._create_live_run = create_live_run
        self._on_finished = on_finished

        self._lock = threading.Lock()
        self._jobs: dict[str, _JobRecord] = {}
        self._paths: dict[str, RunPaths] = {}
        self._queue: queue.Queue = queue.Queue()
        self._ids = itertools.count(1)
        self._worker: threading.Thread | None = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._loop, name="api-jobs", daemon=True)
            self._worker.start()

    def shutdown(self, timeout: float = 2.0) -> None:
        """Stop accepting work and ask a live session to stop. Does not wait
        for a batch run to finish: it is a daemon thread, and an interrupted
        run is recoverable via resume."""
        with self._lock:
            for record in self._jobs.values():
                if record.stop_event is not None and record.state in _ACTIVE:
                    record.stop_event.set()
        self._queue.put(_STOP)
        if self._worker is not None:
            self._worker.join(timeout=timeout)

    # -- submission ----------------------------------------------------------
    def submit_batch(self, audio_path: Path, opts) -> Job:
        """Create the run now (so its id can be returned) and queue its execution."""
        from meeting_assistant.pipeline.batch import BatchOptions

        paths = self._create_batch_run(audio_path)
        run_opts = BatchOptions(num_speakers=opts.num_speakers, resume_run_id=paths.run_id)
        return self._enqueue("batch", paths, lambda: self._run_batch(None, run_opts))

    def submit_resume(
        self,
        paths: RunPaths,
        *,
        force_stage: str | None = None,
        allow_mixed_config: bool = False,
    ) -> Job:
        from meeting_assistant.pipeline.batch import BatchOptions

        with self._lock:
            if any(
                r.run_id == paths.run_id and r.state in _ACTIVE for r in self._jobs.values()
            ):
                raise BusyError(f"Run {paths.run_id} already has a queued or running job")
        run_opts = BatchOptions(
            resume_run_id=paths.run_id,
            force_stage=force_stage,
            allow_mixed_config=allow_mixed_config,
        )
        return self._enqueue("resume", paths, lambda: self._run_batch(None, run_opts))

    def start_live(self, opts) -> Job:
        with self._lock:
            busy = next((r for r in self._jobs.values() if r.state in _ACTIVE), None)
            if busy is not None:
                raise BusyError(f"Busy with {busy.kind} job {busy.job_id} (run {busy.run_id})")
            stop_event = threading.Event()
            paths = self._create_live_run()
            record = self._new_record(
                "live",
                paths,
                lambda: self._run_live(opts, paths=paths, stop_event=stop_event),
            )
            record.stop_event = stop_event
        self._queue.put(record)
        return record.snapshot()

    def stop_live(self) -> Job:
        with self._lock:
            record = next(
                (
                    r
                    for r in self._jobs.values()
                    if r.kind == "live" and r.state in ("queued", "running")
                ),
                None,
            )
            if record is None or record.stop_event is None:
                raise NoLiveJobError("No live session is running")
            record.stop_event.set()
            record.state = "stopping"
            return record.snapshot()

    # -- queries ---------------------------------------------------------------
    def list_jobs(self) -> list[Job]:
        with self._lock:
            return [r.snapshot() for r in reversed(self._jobs.values())]

    def current(self) -> Job | None:
        with self._lock:
            record = next(
                (r for r in self._jobs.values() if r.state in ("running", "stopping")), None
            )
            return record.snapshot() if record else None

    def latest_for_run(self, run_id: str) -> Job | None:
        with self._lock:
            matching = [r for r in self._jobs.values() if r.run_id == run_id]
            return matching[-1].snapshot() if matching else None

    def is_active(self, run_id: str) -> bool:
        job = self.latest_for_run(run_id)
        return job is not None and job.state in _ACTIVE

    # -- internals -------------------------------------------------------------
    def _new_record(self, kind: JobKind, paths: RunPaths, work: Callable[[], object]):
        """Caller holds the lock."""
        job_id = f"job-{next(self._ids)}"
        record = _JobRecord(job_id=job_id, kind=kind, run_id=paths.run_id, work=work)
        self._jobs[job_id] = record
        self._paths[job_id] = paths
        self._trim_history()
        return record

    def _enqueue(self, kind: JobKind, paths: RunPaths, work: Callable[[], object]) -> Job:
        with self._lock:
            record = self._new_record(kind, paths, work)
        self._queue.put(record)
        return record.snapshot()

    def _trim_history(self) -> None:
        finished = [jid for jid, r in self._jobs.items() if r.state not in _ACTIVE]
        for job_id in finished[: max(0, len(self._jobs) - _HISTORY_LIMIT)]:
            del self._jobs[job_id]
            self._paths.pop(job_id, None)

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            self._execute(item)

    def _execute(self, record: _JobRecord) -> None:
        with self._lock:
            if record.state == "queued":
                record.state = "running"
            record.started_at = _now()
            paths = self._paths[record.job_id]

        log.info("Starting %s job %s for run %s", record.kind, record.job_id, record.run_id)
        error: str | None = None
        try:
            record.work()
        except ProvenanceError as exc:
            # A refusal raised before the run was touched (the configuration
            # changed while the job waited in the queue): the run is still a
            # valid partial run, so it must not be marked failed.
            error = f"{type(exc).__name__}: {exc}"
            log.warning("Job %s refused: %s", record.job_id, exc)
        except Exception as exc:  # noqa: BLE001 -- one failed job must not kill the worker
            error = f"{type(exc).__name__}: {exc}"
            log.exception("Job %s failed", record.job_id)
            _mark_failed(paths, error)

        # Indexed before the state flips, so a client that sees "finished" and
        # immediately lists runs finds this one there.
        try:
            self._on_finished(paths)
        except Exception:  # noqa: BLE001 -- indexing is a convenience; the run is on disk
            log.exception("Could not index run %s", record.run_id)

        with self._lock:
            record.state = "failed" if error else "finished"
            record.error = error
            record.finished_at = _now()
