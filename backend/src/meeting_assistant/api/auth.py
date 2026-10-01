"""Bearer-token authentication.

One shared token from ``.env`` (``API_TOKEN``), required on every route except
``/api/health``. The API is reachable on the LAN, and it can start the
server's microphone and read every meeting transcript on disk, so "only
people who should" has to be enforced rather than assumed.

The token is accepted from the ``Authorization`` header only, never a query
parameter: query strings end up in access logs and browser history, which
would quietly turn the token into something written to disk in plain text.

One exception is designed rather than allowed by accident: an ``<audio>``
element cannot send headers, so playback uses a **media ticket** -- a URL
parameter that is an HMAC over one run's id and an expiry, keyed by the API
token. It grants exactly one thing (that run's audio) for a few minutes, so a
ticket that lands in a log is worth almost nothing, and the token itself never
appears in a URL.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException, status

from meeting_assistant import config


def token_is_valid(authorization: str | None) -> bool:
    """True if an ``Authorization`` header value carries the configured token."""
    expected = config.API_TOKEN
    scheme, _, supplied = (authorization or "").partition(" ")

    # compare_digest, not ==: a plain comparison returns faster the earlier
    # the first wrong character is, which leaks the token one character at a
    # time to anyone who can time enough requests.
    return bool(
        expected
        and scheme.lower() == "bearer"
        and secrets.compare_digest(supplied.encode(), expected.encode())
    )


def _ticket_signature(run_id: str, expires: int) -> str:
    assert config.API_TOKEN  # callers only reach here with a configured token
    message = f"audio:{run_id}:{expires}".encode()
    return hmac.new(config.API_TOKEN.encode(), message, hashlib.sha256).hexdigest()


def issue_media_ticket(run_id: str, *, now: float | None = None) -> tuple[str, int]:
    """A ticket for ``run_id``'s audio, and its expiry as a Unix timestamp."""
    expires = int((now if now is not None else time.time()) + config.API_MEDIA_TICKET_SEC)
    return f"{expires}.{_ticket_signature(run_id, expires)}", expires


def media_ticket_is_valid(run_id: str, ticket: str | None, *, now: float | None = None) -> bool:
    """True if ``ticket`` was issued for this run and has not expired."""
    if not ticket or not config.API_TOKEN:
        return False
    expires_text, _, signature = ticket.partition(".")
    if not expires_text.isdigit():
        return False
    expires = int(expires_text)
    if expires < (now if now is not None else time.time()):
        return False
    return secrets.compare_digest(signature, _ticket_signature(run_id, expires))


def require_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: 401 unless the request carries the right token."""
    if not token_is_valid(authorization):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
