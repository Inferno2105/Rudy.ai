"""User accounts and login sessions for the web UI and API.

Kept in their own SQLite file (``config.USERS_DB_PATH``), deliberately apart
from the run index: the index is rebuildable from the run directories on disk
and can be deleted at any time, while accounts are state that exists nowhere
else.

Security choices, each the standard one:

* Passwords are hashed with **scrypt** (Python's standard library), a
  memory-hard KDF, with a random 16-byte salt per password and parameters
  stored alongside the hash so they can be raised later without breaking
  existing accounts. Verification is constant-time.
* A session is a 256-bit random token held by the browser in an HttpOnly
  cookie. Only its SHA-256 is stored, so a copy of this database does not
  contain usable sessions.
* Logging in as a user that does not exist still runs a hash, so response
  time does not reveal which usernames exist.

Each account also has a ``uid``: a random identifier that never changes and is
never reused. Runs and uploads are owned by the uid, not the username, so an
account that is deleted and re-created under the same name does not inherit
the old account's meetings.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from meeting_assistant import config
from meeting_assistant.errors import MeetingAssistantError

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256

# scrypt cost: N=2^14, r=8, p=1 uses 16 MiB and ~50 ms per hash on a laptop.
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P, _SCRYPT_LEN = 2**14, 8, 1, 32

_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    uid           TEXT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


class AccountError(MeetingAssistantError):
    """An invalid username or password, a duplicate user, or a missing one."""


@dataclass(frozen=True)
class User:
    id: int
    uid: str
    username: str
    created_at: str


def _new_uid() -> str:
    return secrets.token_hex(16)


def _now() -> datetime:
    return datetime.now(UTC)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str) -> str:
    """``scrypt$N$r$p$salt$hash`` for storage."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_SCRYPT_LEN,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a ``hash_password`` value."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(expected)),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, base64.b64decode(expected))


# Used to spend the same time on unknown usernames as on known ones.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def validate_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        raise AccountError(
            "Usernames are 3-32 characters: letters, digits, dot, dash or underscore."
        )
    return username


def validate_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"Passwords need at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise AccountError(f"Passwords can be at most {MAX_PASSWORD_LENGTH} characters.")
    return password


@contextmanager
def open_accounts(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """A connection with the schema applied, committed on a clean exit.

    Opened with ``check_same_thread=False``: FastAPI may open and close a
    request's connection on different pool threads. It is never shared
    between requests.
    """
    path = Path(db_path) if db_path is not None else config.USERS_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        _migrate(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring a database from before uids existed up to date (idempotent)."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "uid" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN uid TEXT")
    for (user_id,) in conn.execute("SELECT id FROM users WHERE uid IS NULL").fetchall():
        conn.execute("UPDATE users SET uid = ? WHERE id = ?", (_new_uid(), user_id))
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_uid ON users(uid)")
    conn.commit()


def _user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"], uid=row["uid"], username=row["username"], created_at=row["created_at"]
    )


def user_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def list_users(conn: sqlite3.Connection) -> list[User]:
    return [_user(r) for r in conn.execute("SELECT * FROM users ORDER BY username")]


def get_user(conn: sqlite3.Connection, username: str) -> User | None:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    return _user(row) if row else None


def create_user(conn: sqlite3.Connection, username: str, password: str) -> User:
    username = validate_username(username)
    validate_password(password)
    if get_user(conn, username) is not None:
        raise AccountError(f"A user named {username!r} already exists.")
    created = _now().isoformat(timespec="seconds")
    uid = _new_uid()
    cursor = conn.execute(
        "INSERT INTO users (uid, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
        (uid, username, hash_password(password), created),
    )
    return User(id=cursor.lastrowid or 0, uid=uid, username=username, created_at=created)


def authenticate(conn: sqlite3.Connection, username: str, password: str) -> User | None:
    """The user, if the password matches; ``None`` otherwise (same timing either way)."""
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    return _user(row) if verify_password(password, row["password_hash"]) else None


def set_password(conn: sqlite3.Connection, username: str, password: str) -> None:
    """Change a password and sign the user out everywhere."""
    user = get_user(conn, username)
    if user is None:
        raise AccountError(f"No user named {username!r}.")
    validate_password(password)
    conn.execute(
        "UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user.id)
    )
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user.id,))


def delete_user(conn: sqlite3.Connection, username: str) -> None:
    user = get_user(conn, username)
    if user is None:
        raise AccountError(f"No user named {username!r}.")
    conn.execute("DELETE FROM users WHERE id = ?", (user.id,))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: sqlite3.Connection, user: User) -> str:
    """A new session token for ``user`` (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(days=config.SESSION_TTL_DAYS)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (_token_hash(token), user.id, now.isoformat(), expires.isoformat()),
    )
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now.isoformat(),))
    return token


def user_for_session(conn: sqlite3.Connection, token: str | None) -> User | None:
    """The signed-in user for a session token, or ``None`` if absent or expired."""
    if not token:
        return None
    row = conn.execute(
        "SELECT users.*, sessions.expires_at FROM sessions "
        "JOIN users ON users.id = sessions.user_id WHERE sessions.token_hash = ?",
        (_token_hash(token),),
    ).fetchone()
    if row is None:
        return None
    if datetime.fromisoformat(row["expires_at"]) < _now():
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
        return None
    return _user(row)


def delete_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))
