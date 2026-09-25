"""Logging configuration.

Two destinations, on purpose. The console gets a terse stream for the person
watching a run; the run's own ``run.log`` gets everything at DEBUG, because the
interesting failures here are slow and hard to reproduce — a chunk that
diarized badly, an LLM that returned prose instead of JSON — and re-running a
recording to reproduce a problem costs minutes.

The per-run file handler is attached when a run starts and detached when it
finishes, so a long-lived process (the API server, later) does not accumulate
handlers or write one run's output into another's log.
"""

from __future__ import annotations

import logging
from pathlib import Path

_CONSOLE_FORMAT = "%(levelname)-7s %(name)-28s %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)-28s %(message)s"

_ROOT_LOGGER = "meeting_assistant"
_configured = False


def setup_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    """Configure console logging once. Safe to call repeatedly."""
    global _configured

    logger = logging.getLogger(_ROOT_LOGGER)
    # The logger itself stays at DEBUG so a per-run file handler can capture
    # everything; the console handler does the filtering.
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    if _configured:
        return

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO)
    console.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    logger.addHandler(console)

    # pyannote emits "std(): degrees of freedom is <= 0" on very short audio.
    # It comes from internal embedding statistics on a tiny sample and does not
    # affect correctness, but it appears on nearly every VAD-cut chunk, where it
    # would bury real warnings.
    logging.getLogger("pyannote").setLevel(logging.ERROR)
    logging.getLogger("speechbrain").setLevel(logging.ERROR)

    _configured = True


def attach_run_log(log_path: str | Path) -> logging.Handler:
    """Tee all DEBUG output into a run's log file. Returns the handler."""
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    logging.getLogger(_ROOT_LOGGER).addHandler(handler)
    return handler


def detach_run_log(handler: logging.Handler) -> None:
    """Remove and close a handler added by :func:`attach_run_log`."""
    logging.getLogger(_ROOT_LOGGER).removeHandler(handler)
    handler.close()


def get_logger(name: str) -> logging.Logger:
    """Logger for a module, namespaced under the package root.

    Call with ``__name__``; the ``meeting_assistant.`` prefix is already present
    for modules in this package.
    """
    return logging.getLogger(name)
