"""Sign-in: first-account setup, login, logout, password change, status."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from meeting_assistant import accounts
from meeting_assistant.api.auth import (
    LoginThrottle,
    clear_session_cookie,
    current_user,
    require_user,
    session_token,
    set_session_cookie,
)
from meeting_assistant.api.schemas.auth import AuthStatus, Credentials, PasswordChange, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

throttle = LoginThrottle()

# One message for unknown user and wrong password, so the response does not
# reveal which usernames exist.
_BAD_LOGIN = "Incorrect username or password."


def _out(user: accounts.User) -> UserOut:
    return UserOut(username=user.username, created_at=user.created_at)


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request) -> AuthStatus:
    """Whether an account must be created first, and who is signed in."""
    with accounts.open_accounts() as conn:
        setup_required = accounts.user_count(conn) == 0
    user = None if setup_required else current_user(request)
    return AuthStatus(setup_required=setup_required, user=_out(user) if user else None)


@router.post("/setup", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_first_account(body: Credentials, request: Request, response: Response) -> UserOut:
    """Create the first account and sign in. Refused once any account exists:
    further accounts are added with ``meeting-assistant users add``."""
    with accounts.open_accounts() as conn:
        if accounts.user_count(conn) > 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "An account already exists. Sign in instead."
            )
        try:
            user = accounts.create_user(conn, body.username, body.password)
        except accounts.AccountError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        token = accounts.create_session(conn, user)
    set_session_cookie(response, request, token)
    return _out(user)


@router.post(
    "/login",
    response_model=UserOut,
    responses={
        401: {"description": "Wrong username or password"},
        429: {"description": "Too many attempts; see Retry-After"},
    },
)
def login(body: Credentials, request: Request, response: Response) -> UserOut:
    key = LoginThrottle.key(body.username, _client(request))
    wait = throttle.retry_after(key)
    if wait > 0:
        seconds = math.ceil(wait)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many attempts. Try again in {seconds} seconds.",
            headers={"Retry-After": str(seconds)},
        )
    with accounts.open_accounts() as conn:
        user = accounts.authenticate(conn, body.username, body.password)
        if user is None:
            throttle.failed(key)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, _BAD_LOGIN)
        throttle.succeeded(key)
        token = accounts.create_session(conn, user)
    set_session_cookie(response, request, token)
    return _out(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response) -> None:
    with accounts.open_accounts() as conn:
        accounts.delete_session(conn, session_token(request))
    clear_session_cookie(response)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    user: accounts.User = Depends(require_user),
) -> None:
    """Change your own password. Signs out every other session."""
    with accounts.open_accounts() as conn:
        if accounts.authenticate(conn, user.username, body.current_password) is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Your current password is incorrect.")
        try:
            accounts.set_password(conn, user.username, body.new_password)
        except accounts.AccountError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        token = accounts.create_session(conn, user)
    set_session_cookie(response, request, token)
