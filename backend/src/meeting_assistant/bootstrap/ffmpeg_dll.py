"""Register FFmpeg's DLL directory with the Windows loader.

**This module's function must be called before the first import of
``pyannote.audio`` or ``torchcodec`` anywhere in the process.**

Why it exists. ``pyannote.audio`` decodes audio through TorchCodec, which links
against FFmpeg's shared libraries and resolves them when its C extension loads —
that is, at import time, not at first use. On Windows, Python 3.8+ no longer
searches ``PATH`` for dependent DLLs of extension modules, so an FFmpeg
installation that works perfectly from a terminal is invisible to TorchCodec
unless its directory is registered explicitly via ``os.add_dll_directory()``.

Why the ordering is fragile enough to need enforcing. The failure is
``OSError: [WinError 126] The specified module could not be found``, raised from
somewhere inside torchcodec, naming a DLL rather than anything recognisable. It
looks like a broken install. It is also *ordering*-dependent rather than
*state*-dependent: calling this function one line too late is indistinguishable
from not calling it at all, because the extension has already tried and failed
to load. So the call sites are immediately above the pyannote imports they
protect, and a late call emits a loud warning rather than silently doing nothing
useful.

The static-vs-shared trap. A static FFmpeg build is a single self-contained
``ffmpeg.exe``. ``shutil.which("ffmpeg")`` finds it, ``ffmpeg -version`` works,
and every obvious diagnostic says FFmpeg is present — but there are no
``avcodec-*.dll`` files for TorchCodec to load. This is the exact condition that
made the problem confusing in the first place, so directory candidates are
verified by globbing for the DLLs rather than by the presence of the executable.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

from meeting_assistant import config
from meeting_assistant.errors import ConfigError
from meeting_assistant.logging_setup import get_logger

log = get_logger(__name__)

# Modules whose import consumes the DLL search path. If any is already loaded
# when this runs, registration is too late to help.
_LATE_IF_LOADED = ("pyannote.audio", "torchcodec")

_state: dict[str, object] = {"done": False, "directory": None}


def _warn_if_late() -> None:
    already = [name for name in _LATE_IF_LOADED if name in sys.modules]
    if not already:
        return
    warnings.warn(
        "ensure_ffmpeg_dlls() was called after "
        f"{', '.join(already)} had already been imported. DLL directory "
        "registration only affects imports that happen after it, so audio "
        "decoding may still fail with OSError [WinError 126]. Move the call "
        "above the import.",
        RuntimeWarning,
        stacklevel=3,
    )


def ensure_ffmpeg_dlls(*, strict: bool = True) -> Path | None:
    """Make FFmpeg's shared libraries discoverable. Idempotent.

    Args:
        strict: raise if the libraries cannot be found. Pass ``False`` from
            diagnostics that want to report the problem rather than abort.

    Returns:
        The registered directory, or ``None`` when no action was needed — on
        non-Windows platforms, where the dynamic loader uses the normal search
        paths and no registration is required.

    Raises:
        ConfigError: when ``strict`` and no directory containing
            ``avcodec-*.dll`` could be found.
    """
    if _state["done"]:
        return _state["directory"]  # type: ignore[return-value]

    if sys.platform != "win32":
        _state["done"] = True
        return None

    _warn_if_late()

    directory = config.resolve_ffmpeg_bin_dir()
    if directory is None:
        if strict:
            raise ConfigError(
                "Could not locate FFmpeg's shared libraries (avcodec-*.dll), "
                "which pyannote.audio needs in order to decode audio.\n"
                "    Note that a static ffmpeg.exe on PATH is not enough: the "
                "shared build is required, because the DLLs are what get "
                "loaded.\n"
                "    Install it with:  winget install Gyan.FFmpeg.Shared\n"
                "    If it is still not detected, set FFMPEG_BIN in .env to the "
                "folder containing avcodec-*.dll."
            )
        log.warning("FFmpeg shared libraries not found; audio decoding will likely fail.")
        return None

    os.add_dll_directory(str(directory))
    # Also prepended to PATH: some torch builds shell out to ffmpeg, or load
    # libraries through paths that do not consult the added DLL directories.
    os.environ["PATH"] = f"{directory}{os.pathsep}{os.environ.get('PATH', '')}"

    log.debug("Registered FFmpeg DLL directory: %s", directory)
    _state["done"] = True
    _state["directory"] = directory
    return directory


def describe() -> dict[str, object]:
    """Report FFmpeg discovery state, for the ``doctor`` command.

    Read-only: deliberately does not register anything, so diagnostics can run
    without changing process state.
    """
    directory = config.resolve_ffmpeg_bin_dir()
    return {
        "platform": sys.platform,
        "registration_required": sys.platform == "win32",
        "already_registered": bool(_state["done"]),
        "directory": str(directory) if directory else None,
        "configured_override": os.environ.get("FFMPEG_BIN"),
        "loaded_too_late": [name for name in _LATE_IF_LOADED if name in sys.modules],
    }
