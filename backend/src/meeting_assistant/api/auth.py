"""Signed-in users for the HTTP API: the session dependency, login throttling,
and a cross-site request check.

Sessions travel in an HttpOnly, SameSite=Lax cookie (see
:mod:`meeting_assistant.accounts`), so the browser sends them with every
same-origin request -- including ``<audio>`` and the event stream -- and page
scripts can never read them. Because cookies are sent automatically, state-
changing requests must also come from this site: :func:`same_origin_only`
rejects a POST whose ``Origin`` is another site.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from meeting_assistant import accounts, config

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def session_token(request: Request) -> str | None:
    return request.cookies.get(config.SESSION_COOKIE)


def current_user(request: Request) -> accounts.User | None:
    with accounts.open_accounts() as conn:
        return accounts.user_for_session(conn, session_token(request))


def require_user(request: Request) -> accounts.User:
    """FastAPI dependency: the signed-in user, or 401."""
    user = current_user(request)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


def set_session_cookie(response: Response, request: Request, token: str) -> None:
    response.set_cookie(
        config.SESSION_COOKIE,
        token,
        max_age=config.SESSION_TTL_DAYS * 86_400,
        httponly=True,
        samesite="lax",
        # Secure only over HTTPS: on plain-HTTP LAN use the browser would
        # otherwise drop the cookie and nobody could sign in.
        secure=request.url.scheme == "https",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(config.SESSION_COOKIE, path="/", samesite="lax", httponly=True)


async def same_origin_only(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Middleware: refuse state-changing API requests sent from another site.

    SameSite=Lax already keeps the cookie off cross-site POSTs in current
    browsers; this is the second, explicit layer. Requests with no ``Origin``
    (curl, scripts) are allowed -- they cannot carry the browser's cookie.
    """
    if request.method in _UNSAFE_METHODS and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        host = request.headers.get("host", "")
        if origin and urlsplit(origin).netloc.lower() != host.lower():
            return JSONResponse(status_code=403, content={"detail": "Cross-site request refused."})
    return await call_next(request)


class LoginThrottle:
    """Slows down password guessing for one username from one address.

    After ``free_attempts`` failures within ``window_sec``, each further
    attempt must wait an exponentially growing delay (capped). A success
    clears the record. In memory: it resets when the server restarts, which is
    acceptable for a single-machine tool.
    """

    def __init__(self, free_attempts: int = 5, window_sec: float = 900, max_wait_sec: float = 900):
        self.free_attempts = free_attempts
        self.window_sec = window_sec
        self.max_wait_sec = max_wait_sec
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(username: str, client: str) -> str:
        return f"{username.strip().lower()}|{client}"

    def _recent(self, key: str, now: float) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        while failures and now - failures[0] > self.window_sec:
            failures.popleft()
        return failures

    def retry_after(self, key: str, now: float | None = None) -> float:
        """Seconds to wait before another attempt is allowed (0 if allowed now)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            failures = self._recent(key, now)
            extra = len(failures) - self.free_attempts
            if extra < 0:
                return 0.0
            wait = min(self.max_wait_sec, 15 * 2**extra)
            return max(0.0, failures[-1] + wait - now)

    def failed(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._recent(key, now).append(now)

    def succeeded(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
