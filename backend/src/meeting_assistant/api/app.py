"""FastAPI application factory.

Run with ``meeting-assistant serve``. Every route except ``/api/health`` and
``/api/auth/*`` needs a signed-in user (:mod:`meeting_assistant.api.auth`); the
session is an HttpOnly cookie, and cross-site POSTs are refused.

**Startup order matters here for the same reason it does in the CLI.** The
lifespan registers FFmpeg's DLL directory and then imports the diarization
module on the main thread, before the job worker thread exists -- the
guarantee :mod:`meeting_assistant.bootstrap.ffmpeg_dll` and the live
pipeline's "load before threading" rule both depend on. It also means the
multi-second pyannote import is paid once at startup instead of by whichever
request first needs it.

**The web UI** is served from ``config.FRONTEND_DIST`` (``npm run build``) when
it exists: static files as they are, every other non-API path answered with
``index.html`` so client-side routes survive a reload. API paths are never
answered with the UI -- an unknown ``/api/...`` path is a JSON 404, not a page.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from meeting_assistant import __version__, config
from meeting_assistant.api.auth import same_origin_only
from meeting_assistant.api.jobs import JobManager
from meeting_assistant.api.routers import auth as auth_router
from meeting_assistant.api.routers import jobs as jobs_router
from meeting_assistant.api.routers import runs as runs_router
from meeting_assistant.api.routers import system as system_router
from meeting_assistant.errors import ArtifactError, ConfigError, ProvenanceError
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)

# The UI is fully self-contained (bundled fonts, no CDN), so its page can be
# locked to its own origin. Inline *styles* are allowed because Radix and
# Recharts position elements with style attributes; inline *scripts* are not.
UI_CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self'; media-src 'self'; connect-src 'self'; "
    "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
)
_COMMON_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _preload_models() -> None:
    from meeting_assistant.bootstrap.ffmpeg_dll import ensure_ffmpeg_dlls

    # Non-strict: browsing finished runs must keep working on a machine whose
    # FFmpeg is broken; diarization will then fail as its own (soft) stage.
    ensure_ffmpeg_dlls(strict=False)
    try:
        import meeting_assistant.diarize.pyannote_diarizer  # noqa: F401
    except Exception:  # noqa: BLE001 -- reported, not fatal; see above
        log.exception("Could not import the diarization module at startup")


def _mount_ui(app: FastAPI, dist: Path) -> bool:
    """Serve the built UI from ``dist``; returns False if it has not been built."""
    index = dist / "index.html"
    if not index.is_file():
        return False
    root = dist.resolve()
    assets = dist / "assets"
    if assets.is_dir():
        # Hashed filenames: safe to cache forever.
        app.mount("/assets", StaticFiles(directory=assets), name="ui-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(
            index,
            headers={
                "Content-Security-Policy": UI_CONTENT_SECURITY_POLICY,
                "Cache-Control": "no-cache",
            },
        )

    return True


def _install_openapi(app: FastAPI) -> None:
    """Add models that no route returns directly (the SSE payloads) to the schema."""
    from pydantic.json_schema import models_json_schema

    from meeting_assistant.api.schemas.events import EVENT_MODELS

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        _, extra = models_json_schema(
            [(model, "serialization") for model in EVENT_MODELS],
            ref_template="#/components/schemas/{model}",
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in extra.get("$defs", {}).items():
            components.setdefault(name, definition)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def create_app(
    *,
    jobs: JobManager | None = None,
    preload_models: bool = True,
    frontend_dist: Path | None = None,
) -> FastAPI:
    """Build the app.

    Args:
        jobs: inject a ``JobManager`` with stubbed pipeline functions (tests).
        preload_models: skip the pyannote import (tests, which must stay fast).
        frontend_dist: built UI to serve; defaults to ``config.FRONTEND_DIST``.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if preload_models:
            _preload_models()
        app.state.jobs.start()
        log.info("API ready (version %s)", __version__)
        try:
            yield
        finally:
            app.state.jobs.shutdown()

    app = FastAPI(
        title="Meeting Assistant API",
        version=__version__,
        description="Local Hindi-English meeting assistant: runs, transcripts, summaries, "
        "action items, live recording and evaluation. No authentication: run it on a "
        "trusted machine or network.",
        lifespan=lifespan,
    )
    app.state.jobs = jobs or JobManager()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.API_CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    app.middleware("http")(same_origin_only)

    @app.middleware("http")
    async def _security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in _COMMON_SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    @app.exception_handler(ArtifactError)
    async def _artifact_error(_: Request, exc: ArtifactError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ProvenanceError)
    async def _provenance_error(_: Request, exc: ProvenanceError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ConfigError)
    async def _config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    app.include_router(system_router.public, prefix="/api")
    app.include_router(auth_router.router, prefix="/api")
    app.include_router(system_router.router, prefix="/api")
    app.include_router(runs_router.router, prefix="/api")
    app.include_router(jobs_router.router, prefix="/api")
    _install_openapi(app)

    # Registered last: its catch-all route must never shadow an API route.
    app.state.ui_served = _mount_ui(app, frontend_dist or config.FRONTEND_DIST)
    return app
