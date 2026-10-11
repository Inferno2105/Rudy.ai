"""Which account owns which runs and recordings.

Every run's manifest names its owner (``accounts.User.uid``), and every web
upload lands in that account's own folder, ``data/audio/users/<uid>/``. The
API shows an account only what it owns, so two accounts on one server never
see each other's meetings, transcripts or recordings.

A run with no owner -- one made before accounts existed, or by the CLI without
``--user`` -- is *unclaimed* and visible to nobody in the web UI. While the
server has exactly one account, unclaimed runs are simply that account's: they
are claimed automatically (:func:`claim_if_single_user`) at start-up, when the
index is rebuilt, and just before a second account is created. Once two
accounts exist nothing is assigned automatically, because there is no longer
a safe guess; ``meeting-assistant users claim-runs <name>`` does it by hand.
"""

from __future__ import annotations

from pathlib import Path

from meeting_assistant import accounts, config
from meeting_assistant.io_utils import read_json, write_json
from meeting_assistant.logging_setup import get_logger
from meeting_assistant.paths import RunPaths, list_runs

log = get_logger(__name__)


def run_owner(paths: RunPaths) -> str | None:
    """The run's owner uid, or ``None`` if unclaimed or it has no manifest yet."""
    if not paths.manifest_path.is_file():
        return None
    return read_json(paths.manifest_path).get("owner")


def user_audio_dir(uid: str) -> Path:
    """Where an account's uploads are stored (not created here)."""
    return config.AUDIO_DIR / "users" / uid


def claim_unowned(uid: str, runs: list[RunPaths] | None = None) -> list[str]:
    """Make ``uid`` the owner of every unclaimed run; return their ids.

    Edits only the ``owner`` field of each manifest (provenance is untouched),
    then re-indexes those runs so the run list shows them at once.
    """
    claimed: list[RunPaths] = []
    for paths in list_runs() if runs is None else runs:
        if not paths.manifest_path.is_file():
            continue
        manifest = read_json(paths.manifest_path)
        if manifest.get("owner"):
            continue
        manifest["owner"] = uid
        write_json(paths.manifest_path, manifest)
        claimed.append(paths)

    if claimed:
        from meeting_assistant.store.db import open_db
        from meeting_assistant.store.ingest import ingest_run

        with open_db() as conn:
            for paths in claimed:
                ingest_run(conn, paths)
        log.info("Assigned %d unclaimed run(s) to account %s", len(claimed), uid)
    return [paths.run_id for paths in claimed]


def sole_user() -> accounts.User | None:
    """The only account, if exactly one exists."""
    with accounts.open_accounts() as conn:
        users = accounts.list_users(conn)
    return users[0] if len(users) == 1 else None


def claim_if_single_user() -> list[str]:
    """Give unclaimed runs to the only account, if there is exactly one."""
    user = sole_user()
    return claim_unowned(user.uid) if user is not None else []
