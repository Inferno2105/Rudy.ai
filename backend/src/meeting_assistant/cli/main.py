"""Command-line entry point.

Subcommands are added as the pipeline is built; ``doctor`` comes first
deliberately. Every prerequisite this project has — a gated Hugging Face model,
a shared-build FFmpeg whose DLLs must be registered before an import, a local
LLM server with a specific model pulled, a pinned Python version — fails at a
different point in a run and with a different unhelpful message. Being able to
check all of them in two seconds is worth more than any other single command.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from meeting_assistant import __version__, config
from meeting_assistant.logging_setup import setup_logging

OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARK = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str | None = None


def _check_python() -> Check:
    major, minor = sys.version_info[:2]
    version = f"{major}.{minor}.{sys.version_info[2]}"
    if (major, minor) == (3, 12):
        return Check("Python", OK, version)
    return Check(
        "Python",
        WARN if (major, minor) > (3, 12) else FAIL,
        f"{version} (expected 3.12)",
        "Several packages in the torch/pyannote/webrtcvad stack have no "
        "prebuilt Windows wheels outside 3.12. Recreate the venv with "
        "Python 3.12.",
    )


def _check_env_file() -> Check:
    env_path = config.REPO_ROOT / ".env"
    if env_path.exists():
        return Check(".env file", OK, str(env_path))
    return Check(
        ".env file",
        FAIL,
        f"not found at {env_path}",
        "Copy-Item .env.example .env   and fill in HF_TOKEN",
    )


def _check_hf_token() -> Check:
    if not config.HF_TOKEN:
        return Check(
            "Hugging Face token",
            FAIL,
            "HF_TOKEN is not set",
            "Create one at https://huggingface.co/settings/tokens and add "
            "HF_TOKEN=hf_... to .env",
        )
    masked = f"{config.HF_TOKEN[:6]}...{config.HF_TOKEN[-4:]}"
    return Check("Hugging Face token", OK, f"set ({masked})")


def _check_ffmpeg() -> Check:
    from meeting_assistant.bootstrap import ffmpeg_dll

    info = ffmpeg_dll.describe()
    if not info["registration_required"]:
        return Check("FFmpeg", OK, f"not required on {info['platform']}")
    if info["directory"]:
        return Check("FFmpeg shared libraries", OK, str(info["directory"]))
    return Check(
        "FFmpeg shared libraries",
        FAIL,
        "no directory containing avcodec-*.dll was found",
        "A static ffmpeg.exe on PATH is NOT enough — TorchCodec loads the "
        "DLLs. Run: winget install Gyan.FFmpeg.Shared    then, if still "
        "undetected, set FFMPEG_BIN in .env to the folder holding "
        "avcodec-*.dll",
    )


def _check_ollama() -> Check:
    from meeting_assistant.llm.client import OllamaClient

    ok, detail = OllamaClient().health_check()
    if ok:
        return Check("Ollama", OK, detail)
    return Check(
        "Ollama",
        FAIL,
        detail,
        f"Start the Ollama server, then run: ollama pull {config.OLLAMA_MODEL}",
    )


def _check_imports() -> list[Check]:
    """Import the heavy dependencies, in an order that respects the DLL bootstrap.

    ``ensure_ffmpeg_dlls`` runs first and non-strictly: the point is to report
    every problem, so a missing FFmpeg should not abort the remaining checks. It
    must still run *before* pyannote is imported, or that import is exactly the
    failure this command exists to diagnose.
    """
    from meeting_assistant.bootstrap.ffmpeg_dll import ensure_ffmpeg_dlls

    ensure_ffmpeg_dlls(strict=False)

    checks: list[Check] = []
    for label, module in [
        ("faster-whisper", "faster_whisper"),
        ("pyannote.audio", "pyannote.audio"),
        ("webrtcvad", "webrtcvad"),
        ("sounddevice", "sounddevice"),
    ]:
        try:
            __import__(module)
        except Exception as exc:
            hint = None
            if module == "pyannote.audio" and "126" in str(exc):
                hint = (
                    "This is the FFmpeg DLL problem. Fix the FFmpeg check above "
                    "and re-run."
                )
            checks.append(Check(f"import {label}", FAIL, f"{type(exc).__name__}: {exc}", hint))
        else:
            checks.append(Check(f"import {label}", OK, "available"))
    return checks


def _check_data_dirs() -> Check:
    problems = []
    for label, path in [
        ("data", config.DATA_DIR),
        ("audio", config.AUDIO_DIR),
        ("runs", config.RUNS_DIR),
    ]:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write-probe"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            problems.append(f"{label} ({path}): {exc}")
    if problems:
        return Check("Data directories", FAIL, "; ".join(problems))
    return Check("Data directories", OK, f"writable under {config.DATA_DIR}")


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report on every prerequisite, then summarise."""
    print(f"meeting-assistant {__version__}")
    print(f"repo root: {config.REPO_ROOT}\n")

    checks = [
        _check_python(),
        _check_env_file(),
        _check_hf_token(),
        _check_ffmpeg(),
    ]
    if not args.quick:
        checks.extend(_check_imports())
        checks.append(_check_ollama())
    checks.append(_check_data_dirs())

    for check in checks:
        print(f"{_MARK[check.status]} {check.name}: {check.detail}")
        if check.fix and check.status != OK:
            for line in check.fix.split("\n"):
                print(f"         -> {line}")

    print("\nConfiguration")
    for key, value in config.output_affecting_settings().items():
        print(f"  {key:24} {value}")

    failures = [c for c in checks if c.status == FAIL]
    warnings_ = [c for c in checks if c.status == WARN]
    print()
    if failures:
        print(f"{len(failures)} problem(s) must be fixed before the pipeline will run.")
        return 1
    if warnings_:
        print(f"Ready, with {len(warnings_)} warning(s).")
        return 0
    print("All checks passed.")
    return 0


def cmd_runs(args: argparse.Namespace) -> int:
    """List previous runs, or show one in detail."""
    from meeting_assistant import paths as paths_mod
    from meeting_assistant.io_utils import read_json

    if args.show:
        run = paths_mod.open_run(args.show)
        if not run.manifest_path.exists():
            print(f"{run.run_id}: no manifest (run may have been interrupted early)")
            return 1
        manifest = read_json(run.manifest_path)
        print(f"run_id      {manifest.get('run_id')}")
        print(f"mode        {manifest.get('mode')}")
        print(f"status      {manifest.get('status')}")
        print(f"data_origin {manifest.get('data_origin')}")
        prov = manifest.get("provenance", {})
        print(f"commit      {(prov.get('git') or {}).get('commit')}")
        print(f"config_hash {prov.get('config_hash')}")

        stages = manifest.get("stages", [])
        if stages:
            print("\nstages:")
            for stage in stages:
                marker = {"ok": "[ ok ]", "failed": "[FAIL]", "skipped": "[skip]"}.get(
                    stage.get("status"), "[ ?? ]"
                )
                print(f"  {marker} {stage['name']:<16} {stage.get('seconds', 0):>6.1f}s", end="")
                if stage.get("error"):
                    print(f"  -- {stage['error'][:80]}")
                else:
                    print()

        print("\nartifacts present:")
        for name in run.existing_artifacts():
            print(f"  {name}")
        return 0

    runs = paths_mod.list_runs()
    if not runs:
        print(f"No runs yet under {config.RUNS_DIR}")
        return 0
    print(f"{'run_id':<44} {'status':<10} artifacts")
    for run in runs:
        status = "?"
        if run.manifest_path.exists():
            try:
                status = read_json(run.manifest_path).get("status", "?")
            except Exception:
                status = "unreadable"
        print(f"{run.run_id:<44} {status:<10} {len(run.existing_artifacts())}/10")
    return 0


def _cli_owner(username: str | None) -> str | None:
    """The uid that should own a run started from the CLI.

    ``--user NAME`` picks an account. Without it, the only account owns the
    run; with several accounts the run is left unclaimed (no account sees it
    in the web UI until ``users claim-runs``), and a note says so.
    """
    from meeting_assistant import accounts
    from meeting_assistant.ownership import sole_user

    if username:
        with accounts.open_accounts() as conn:
            user = accounts.get_user(conn, username)
        if user is None:
            raise SystemExit(f"No account named {username!r} (see: meeting-assistant users list)")
        return user.uid
    user = sole_user()
    if user is not None:
        return user.uid
    with accounts.open_accounts() as conn:
        several = accounts.user_count(conn) > 1
    if several:
        print(
            "Note: several accounts exist and --user was not given, so no account "
            "will see this run in the web UI until `meeting-assistant users "
            "claim-runs <name>`.",
            file=sys.stderr,
        )
    return None


def cmd_batch(args: argparse.Namespace) -> int:
    """Run (or resume) the batch pipeline over one audio file."""
    from meeting_assistant.errors import MeetingAssistantError, ProvenanceError
    from meeting_assistant.pipeline.batch import BatchOptions, run_batch

    opts = BatchOptions(
        owner=None if args.resume else _cli_owner(args.user),
        num_speakers=args.num_speakers,
        resume_run_id=args.resume,
        force_stage=args.force,
        only_stage=args.only,
        skip_stages=tuple(args.skip or ()),
        allow_mixed_config=args.allow_mixed_config,
    )

    try:
        paths = run_batch(args.audio, opts)
    except ProvenanceError as exc:
        print(f"Resume refused: {exc}", file=sys.stderr)
        return 1
    except MeetingAssistantError as exc:
        print(f"Batch run failed: {exc}", file=sys.stderr)
        return 1

    from meeting_assistant.io_utils import read_json

    manifest = read_json(paths.manifest_path)
    status = manifest.get("status")
    print(f"\nRun {paths.run_id}: {status}")
    print(f"  {paths.root}")

    return 0 if status == "completed" else 1


def _clip_source(manifest) -> dict:
    """Which run a clip was scored against, stored with its numbers.

    Without this the report holds metrics with no record of which run, commit
    or configuration produced them -- the console output said, but the file
    that tables and the dashboard are built from did not.
    """
    git = manifest.provenance_block.get("git") or {}
    return {
        "run_id": manifest.run_id,
        "git_commit": git.get("commit"),
        "git_dirty": git.get("dirty"),
        "config_hash": manifest.provenance_block.get("config_hash"),
    }


def _load_clip_reference(clip_dir):
    """Read one clip's reference bundle from ``data/eval/references/<clip_id>/``.

    Every file is optional (see ``docs/evaluation.md`` for the full contract):
    a clip need only carry references for the metric families it is meant to
    exercise, and :func:`~meeting_assistant.evaluation.report.generate_clip_report`
    already skips a family cleanly when either side is missing.
    """
    from meeting_assistant.evaluation.report import ClipReference
    from meeting_assistant.evaluation.rttm import read_rttm
    from meeting_assistant.io_utils import read_json

    def text(name: str) -> str | None:
        path = clip_dir / name
        return path.read_text(encoding="utf-8").strip() if path.exists() else None

    def data(name: str):
        path = clip_dir / name
        return read_json(path) if path.exists() else None

    turns = read_rttm(clip_dir / "turns.rttm") if (clip_dir / "turns.rttm").exists() else None
    meta = data("meta.json") or {}

    return ClipReference(
        transcript_text=text("transcript.txt"),
        turns=turns,
        languages=data("languages.json"),
        summary=text("summary.txt"),
        action_items=data("action_items.json"),
        true_speakers=data("true_speakers.json"),
        true_speaker_count=meta.get("true_speaker_count"),
    )


def _load_clip_hypothesis(run):
    """Build a :class:`~meeting_assistant.evaluation.report.ClipHypothesis`
    from a completed run's artifacts."""
    from meeting_assistant.errors import ArtifactError
    from meeting_assistant.evaluation.report import ClipHypothesis
    from meeting_assistant.io_utils import read_json
    from meeting_assistant.pipeline.stages import resolve_intel_input

    transcript_text = None
    languages = None
    resolved_segments = None
    try:
        _, segments = resolve_intel_input(run)
        transcript_text = " ".join(s.get("text", "") for s in segments)
        languages = [s.get("language") for s in segments]
        resolved_segments = segments
    except ArtifactError:
        pass

    turns = read_json(run.artifact("diarization")) if run.has("diarization") else None
    summary = read_json(run.artifact("summary"))["summary"] if run.has("summary") else None
    action_items = (
        read_json(run.artifact("action_items"))["action_items"]
        if run.has("action_items")
        else None
    )

    system_metrics = None
    if run.manifest_path.exists():
        manifest = read_json(run.manifest_path)
        transcript_stage = next(
            (s for s in manifest.get("stages", []) if s["name"] == "transcript"), None
        )
        if transcript_stage:
            system_metrics = {
                "realtime_factor": transcript_stage.get("counts", {}).get("realtime_factor"),
                "transcribe_seconds": transcript_stage.get("seconds"),
            }

    return ClipHypothesis(
        transcript_text=transcript_text,
        turns=turns,
        languages=languages,
        summary=summary,
        action_items=action_items,
        resolved_segments=resolved_segments,
        system_metrics=system_metrics,
    )


def cmd_eval(args: argparse.Namespace) -> int:
    """Score one or more runs against their labelled references and report."""
    from meeting_assistant import paths as paths_mod
    from meeting_assistant.evaluation.report import aggregate_reports, generate_clip_report
    from meeting_assistant.io_utils import write_json

    references_dir = config.EVAL_DIR / "references"
    clip_dirs = []
    if references_dir.is_dir():
        clip_dirs = sorted(d for d in references_dir.glob("*") if d.is_dir())

    if not clip_dirs:
        print(f"No labelled clips found under {references_dir}")
        print("See docs/evaluation.md for the dataset and labelling protocol.")
        return 1

    from meeting_assistant.pipeline.manifest import RunManifest

    # The newest *eligible* run per recording. A run whose stages came from
    # mixed configurations or code, or that is not real audio, must never feed
    # a reported number; why each one was passed over is printed, so a clip
    # silently scored against an older run cannot go unnoticed.
    runs_by_source = {}
    passed_over: dict[str, list[str]] = {}
    for run in paths_mod.list_runs():  # newest first
        if not run.manifest_path.exists():
            continue
        manifest = RunManifest.load(run)
        input_name = (manifest.provenance_block.get("input") or {}).get("name")
        if not input_name or input_name in runs_by_source:
            continue
        reason = manifest.evaluation_ineligibility()
        if reason is not None:
            passed_over.setdefault(input_name, []).append(f"{run.run_id}: {reason}")
            continue
        runs_by_source[input_name] = run

    reports = []
    for clip_dir in clip_dirs:
        clip_id = clip_dir.name
        run = runs_by_source.get(f"{clip_id}.wav")
        for note in passed_over.get(f"{clip_id}.wav", []):
            print(f"  [note] {clip_id}: passed over {note}")
        if run is None:
            print(f"  [skip] {clip_id}: no eligible run found for data/audio/{clip_id}.wav")
            continue
        hypothesis = _load_clip_hypothesis(run)
        reference = _load_clip_reference(clip_dir)
        report = generate_clip_report(clip_id, hypothesis, reference)
        report["source"] = _clip_source(RunManifest.load(run))
        reports.append(report)
        print(f"  [ ok ] {clip_id}: scored against run {run.run_id}")

    if not reports:
        print("\nNo clip had both a labelled reference and a matching run.")
        return 1

    from datetime import datetime

    from meeting_assistant.provenance import git_state

    config_hashes = sorted({r["source"]["config_hash"] for r in reports} - {None})
    if len(config_hashes) > 1:
        print(f"\n[warn] the scored runs span {len(config_hashes)} configurations: {config_hashes}")
    aggregated = aggregate_reports(reports)
    output_path = config.EVAL_DIR / "reports" / "latest.json"
    write_json(
        output_path,
        {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "git": git_state(),
            "config_hashes": config_hashes,
            "clips": reports,
            "aggregate": aggregated,
        },
    )

    print(f"\nScored {len(reports)}/{len(clip_dirs)} clip(s). Report written to {output_path}")
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    """Record from the microphone and process it incrementally until stopped."""
    from meeting_assistant.errors import MeetingAssistantError
    from meeting_assistant.pipeline.live import LiveOptions, run_live

    opts = LiveOptions(
        owner=_cli_owner(args.user),
        num_speakers=args.num_speakers,
        device=args.device,
        use_registry=not args.no_registry,
    )

    try:
        paths = run_live(opts)
    except MeetingAssistantError as exc:
        print(f"Live run failed: {exc}", file=sys.stderr)
        return 1

    from meeting_assistant.io_utils import read_json

    manifest = read_json(paths.manifest_path)
    status = manifest.get("status")
    print(f"\nRun {paths.run_id}: {status}")
    print(f"  {paths.root}")

    return 0 if status in ("completed", "partial") else 1


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the HTTP API and web UI (accounts: see ``meeting-assistant users``)."""
    import uvicorn

    host = args.host or config.API_HOST
    port = args.port or config.API_PORT
    print(f"Serving on http://{host}:{port}  (docs at /docs)")
    if (config.FRONTEND_DIST / "index.html").is_file():
        print(f"Web UI at http://{host}:{port}/")
    else:
        print(f"Web UI not built ({config.FRONTEND_DIST}); run `npm run build` in frontend/")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "Reachable from other machines on this network. Everything except "
            "the sign-in page needs an account; sessions travel over plain HTTP "
            "here, so use it on a network you trust."
        )
    uvicorn.run(
        "meeting_assistant.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="warning" if args.quiet else "info",
    )
    return 0


def _read_new_password() -> str:
    """A new password: prompted twice at a terminal, or one line from stdin."""
    if not sys.stdin.isatty():
        return sys.stdin.readline().rstrip("\r\n")
    import getpass

    first = getpass.getpass("New password: ")
    if getpass.getpass("Repeat password: ") != first:
        raise SystemExit("Passwords did not match; nothing changed.")
    return first


def cmd_users(args: argparse.Namespace) -> int:
    """Manage web UI accounts (stored in data/users.sqlite)."""
    from meeting_assistant import accounts
    from meeting_assistant.ownership import claim_if_single_user, claim_unowned

    if args.users_cmd == "add":
        # Runs made while one account existed are that account's; settle it
        # before a second account makes the owner ambiguous.
        claim_if_single_user()
    try:
        with accounts.open_accounts() as conn:
            if args.users_cmd == "list":
                users = accounts.list_users(conn)
                if not users:
                    print("No accounts yet. The first one is created on the sign-in page,")
                    print("or with: meeting-assistant users add <name>")
                for user in users:
                    print(f"{user.username:<32} created {user.created_at}")
            elif args.users_cmd == "add":
                accounts.create_user(conn, args.username, _read_new_password())
                print(f"Created {args.username}.")
            elif args.users_cmd == "reset-password":
                accounts.set_password(conn, args.username, _read_new_password())
                print(f"Password changed for {args.username}; their sessions were signed out.")
            elif args.users_cmd == "remove":
                accounts.delete_user(conn, args.username)
                print(
                    f"Removed {args.username}. Their meetings stay on disk under "
                    f"{config.RUNS_DIR}, visible to no account."
                )
            elif args.users_cmd == "claim-runs":
                user = accounts.get_user(conn, args.username)
                if user is None:
                    raise accounts.AccountError(f"No user named {args.username!r}.")
                claimed = claim_unowned(user.uid)
                print(f"Gave {len(claimed)} unclaimed run(s) to {user.username}.")
                for run_id in claimed:
                    print(f"  {run_id}")
    except accounts.AccountError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_openapi(args: argparse.Namespace) -> int:
    """Write the OpenAPI schema, from which the frontend's typed client is generated."""
    import json
    from pathlib import Path

    from meeting_assistant.api.app import create_app
    from meeting_assistant.io_utils import write_text

    default = config.REPO_ROOT / "frontend" / "src" / "api" / "openapi.json"
    out = Path(args.out) if args.out else default
    schema = create_app(preload_models=False).openapi()
    write_text(out, json.dumps(schema, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote OpenAPI schema ({len(schema['paths'])} paths) to {out}")
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:  # noqa: ARG001 -- argparse namespace, currently no flags used
    """Rebuild the SQLite index from every run directory on disk."""
    from meeting_assistant import paths as paths_mod
    from meeting_assistant.store.db import open_db
    from meeting_assistant.store.ingest import reindex_all

    runs = paths_mod.list_runs()
    with open_db() as conn:
        count = reindex_all(conn, runs)

    print(f"Indexed {count} of {len(runs)} run(s) into {config.INDEX_DB_PATH}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meeting-assistant",
        description="Local multilingual (Hindi-English) meeting assistant.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="warnings and errors only")

    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check every prerequisite")
    doctor.add_argument(
        "--quick",
        action="store_true",
        help="skip the checks that import models or contact Ollama",
    )
    doctor.set_defaults(func=cmd_doctor)

    runs = subparsers.add_parser("runs", help="list or inspect previous runs")
    runs.add_argument("--show", metavar="RUN_ID", help="show one run in detail")
    runs.set_defaults(func=cmd_runs)

    batch = subparsers.add_parser("batch", help="run the pipeline over one audio file")
    batch.add_argument(
        "audio",
        nargs="?",
        help="path to the audio file (omit only when using --resume)",
    )
    batch.add_argument(
        "--num-speakers",
        type=int,
        metavar="N",
        help="true speaker count, if known -- improves diarization accuracy",
    )
    batch.add_argument("--resume", metavar="RUN_ID", help="continue a previous run")
    batch.add_argument(
        "--force",
        metavar="STAGE",
        help="re-run from this stage onward, deleting its artifact and every later one",
    )
    batch.add_argument("--only", metavar="STAGE", help="run only this one stage")
    batch.add_argument(
        "--skip",
        action="append",
        metavar="STAGE",
        help="exclude a stage from this run (repeatable)",
    )
    batch.add_argument(
        "--user",
        metavar="NAME",
        help="account that owns the new run in the web UI (default: the only account)",
    )
    batch.add_argument(
        "--allow-mixed-config",
        action="store_true",
        help="with --resume: continue even if the configuration changed since the run's "
        "earlier stages (debugging only; the run is excluded from evaluation)",
    )
    batch.set_defaults(func=cmd_batch)

    live = subparsers.add_parser(
        "live", help="record from the microphone and process it incrementally"
    )
    live.add_argument("--device", type=int, metavar="N", help="sounddevice input device index")
    live.add_argument(
        "--num-speakers",
        type=int,
        metavar="N",
        help="true speaker count, if known -- improves diarization accuracy",
    )
    live.add_argument(
        "--user",
        metavar="NAME",
        help="account that owns the run in the web UI (default: the only account)",
    )
    live.add_argument(
        "--no-registry",
        action="store_true",
        help="disable cross-chunk speaker identity resolution",
    )
    live.set_defaults(func=cmd_live)

    eval_parser = subparsers.add_parser(
        "eval", help="score labelled clips under data/eval/references/ against their runs"
    )
    eval_parser.set_defaults(func=cmd_eval)

    serve = subparsers.add_parser("serve", help="run the HTTP API and web UI")
    serve.add_argument("--host", help=f"bind address (default {config.API_HOST})")
    serve.add_argument("--port", type=int, help=f"port (default {config.API_PORT})")
    serve.set_defaults(func=cmd_serve)

    users = subparsers.add_parser("users", help="manage web UI accounts")
    users_sub = users.add_subparsers(dest="users_cmd", required=True)
    users_sub.add_parser("list", help="list accounts")
    for name, text in (
        ("add", "create an account (prompts for the password)"),
        ("reset-password", "set a new password and sign the user out everywhere"),
        ("remove", "delete an account"),
        ("claim-runs", "give every run that has no owner to this account"),
    ):
        sub = users_sub.add_parser(name, help=text)
        sub.add_argument("username")
    users.set_defaults(func=cmd_users)

    openapi = subparsers.add_parser("openapi", help="write the API's OpenAPI schema")
    openapi.add_argument(
        "--out", metavar="PATH", help="output file (default frontend/src/api/openapi.json)"
    )
    openapi.set_defaults(func=cmd_openapi)

    reindex = subparsers.add_parser("reindex", help="rebuild the SQLite index from disk")
    reindex.set_defaults(func=cmd_reindex)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    # Defence in depth: registering the FFmpeg DLL directory here, before any
    # subcommand runs, means no command can be the one that imports
    # pyannote.audio too early. Non-strict so `doctor` can still report a
    # missing FFmpeg rather than dying on it.
    from meeting_assistant.bootstrap.ffmpeg_dll import ensure_ffmpeg_dlls

    ensure_ffmpeg_dlls(strict=False)

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
