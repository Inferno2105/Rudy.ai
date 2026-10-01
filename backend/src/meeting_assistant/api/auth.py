"""Bearer-token authentication.

One shared token from ``.env`` (``API_TOKEN``), required on every route except
``/api/health``. The API is reachable on the LAN, and it can start the
server's microphone and read every meeting transcript on disk, so "only
people who should" has to be enforced rather than assumed.

The token is accepted from the ``Authorization`` header only, never a query
parameter: query strings end up in access logs and browser history, which
would quietly turn the token into something written to disk in plain text.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from meeting_assistant import config


def require_token(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency: 401 unless the request carries the right token."""
    expected = config.API_TOKEN
    scheme, _, supplied = (authorization or "").partition(" ")

    # compare_digest, not ==: a plain comparison returns faster the earlier
    # the first wrong character is, which leaks the token one character at a
    # time to anyone who can time enough requests.
    if (
        not expected
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(supplied.encode(), expected.encode())
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API token",
            headers={"WWW-Authenticate": "Bearer"},
        )
