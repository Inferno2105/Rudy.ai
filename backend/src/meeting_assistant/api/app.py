"""FastAPI application factory.

Run with ``meeting-assistant serve``, which refuses to start without an
``API_TOKEN``; ``create_app`` itself does not check, so tests can build an app
with a token patched in.

**Startup order matters here for the same reason it does in the CLI.** The
lifespan registers FFmpeg's DLL directory and then imports the diarization
module on the main thread, before the job worker thread exists -- the
guarantee :mod:`meeting_assistant.bootstrap.ffmpeg_dll` and the live
pipeline's "load before threading" rule both depend on. It also means the
multi-second pyannote import is paid once at startup instead of by whichever
request first needs it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from meeting_assistant import __version__, config
from meeting_assistant.api.jobs import JobManager
from meeting_assistant.api.routers import jobs as jobs_router
from meeting_assistant.api.routers import runs as runs_router
from meeting_assistant.api.routers import system as system_router
from meeting_assistant.errors import ArtifactError, ConfigError
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)


def _preload_models() -> None:
    from meeting_assistant.bootstrap.ffmpeg_dll import ensure_ffmpeg_dlls

    # Non-strict: browsing finished runs must keep working on a machine whose
    # FFmpeg is broken; diarization will then fail as its own (soft) stage.
    ensure_ffmpeg_dlls(strict=False)
    try:
        import meeting_assistant.diarize.pyannote_diarizer  # noqa: F401
    except Exception:  # noqa: BLE001 -- reported, not fatal; see above
        log.exception("Could not import the diarization module at startup")


def create_app(*, jobs: JobManager | None = None, preload_models: bool = True) -> FastAPI:
    """Build the app.

    Args:
        jobs: inject a ``JobManager`` with stubbed pipeline functions (tests).
        preload_models: skip the pyannote import (tests, which must stay fast).
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
        "action items, live recording and evaluation. All routes except /api/health need "
        "`Authorization: Bearer <API_TOKEN>`.",
        lifespan=lifespan,
    )
    app.state.jobs = jobs or JobManager()

    # Bearer tokens travel in a header, not a cookie, so credentials stay off.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.API_CORS_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(ArtifactError)
    async def _artifact_error(_: Request, exc: ArtifactError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConfigError)
    async def _config_error(_: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    app.include_router(system_router.public, prefix="/api")
    app.include_router(system_router.router, prefix="/api")
    app.include_router(runs_router.router, prefix="/api")
    app.include_router(jobs_router.router, prefix="/api")
    return app
