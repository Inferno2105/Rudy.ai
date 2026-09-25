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

    checks = [_check_python(), _check_env_file(), _check_hf_token(), _check_ffmpeg()]
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


def cmd_batch(args: argparse.Namespace) -> int:
    """Run (or resume) the batch pipeline over one audio file."""
    from meeting_assistant.errors import MeetingAssistantError
    from meeting_assistant.pipeline.batch import BatchOptions, run_batch

    opts = BatchOptions(
        num_speakers=args.num_speakers,
        resume_run_id=args.resume,
        force_stage=args.force,
        only_stage=args.only,
        skip_stages=tuple(args.skip or ()),
    )

    try:
        paths = run_batch(args.audio, opts)
    except MeetingAssistantError as exc:
        print(f"Batch run failed: {exc}", file=sys.stderr)
        return 1

    from meeting_assistant.io_utils import read_json

    manifest = read_json(paths.manifest_path)
    status = manifest.get("status")
    print(f"\nRun {paths.run_id}: {status}")
    print(f"  {paths.root}")

    return 0 if status == "completed" else 1


def cmd_live(args: argparse.Namespace) -> int:
    """Record from the microphone and process it incrementally until stopped."""
    from meeting_assistant.errors import MeetingAssistantError
    from meeting_assistant.pipeline.live import LiveOptions, run_live

    opts = LiveOptions(
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
        "--no-registry",
        action="store_true",
        help="disable cross-chunk speaker identity resolution",
    )
    live.set_defaults(func=cmd_live)

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
