"""Guard the FFmpeg-before-pyannote import ordering.

On Windows, ``pyannote.audio`` transitively loads TorchCodec, which resolves
FFmpeg's ``avcodec-*.dll`` when its C extension loads. The FFmpeg directory has
to be registered with the DLL loader before that happens. Registration one line
too late is indistinguishable from never registering at all, and the symptom is
an ``OSError: [WinError 126]`` from deep inside torchcodec that reads like a
broken installation rather than an ordering mistake.

The realistic way to regress this is innocuous: someone adds a convenience
re-export to an ``__init__.py`` so callers can write
``from meeting_assistant.diarize import load_pipeline``. That single line makes
importing *anything* in the package pull in pyannote as a side effect, before any
bootstrap code has run.

These tests are cheap and permanent, which is the right trade for a failure this
hard to attribute.
"""

from __future__ import annotations

import subprocess
import sys


# Run in a fresh interpreter each time: within one pytest process another test
# may already have imported pyannote, which would make these assertions
# meaningless.
def _module_loaded_after(import_statement: str, module: str) -> bool:
    code = f"import sys; {import_statement}; print(int({module!r} in sys.modules))"
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=180,
        check=True,
    )
    return bool(int(result.stdout.strip().splitlines()[-1]))


def test_importing_package_does_not_load_pyannote():
    assert not _module_loaded_after("import meeting_assistant", "pyannote.audio")


def test_importing_package_does_not_load_torch():
    """torch costs seconds to import and the CLI must stay responsive without it."""
    assert not _module_loaded_after("import meeting_assistant", "torch")


def test_importing_config_does_not_load_pyannote():
    assert not _module_loaded_after("import meeting_assistant.config", "pyannote.audio")


def test_importing_diarize_subpackage_does_not_load_pyannote():
    """The subpackage's __init__ must stay free of re-exports.

    This is the assertion that catches the realistic regression described above.
    """
    assert not _module_loaded_after("import meeting_assistant.diarize", "pyannote.audio")


def test_bootstrap_module_does_not_import_pyannote():
    """The bootstrap must not import what it exists to make importable."""
    assert not _module_loaded_after(
        "import meeting_assistant.bootstrap.ffmpeg_dll", "pyannote.audio"
    )


def test_cli_module_does_not_load_pyannote_at_import():
    """Importing the CLI must not be expensive; --help has to stay instant."""
    assert not _module_loaded_after("import meeting_assistant.cli.main", "pyannote.audio")


def test_ensure_ffmpeg_dlls_warns_when_called_late():
    """A late call must complain loudly rather than fail silently.

    Simulated by planting a sentinel in ``sys.modules`` so the check trips without
    actually importing pyannote, which would make the test slow.
    """
    code = (
        "import sys, types, warnings\n"
        "sys.modules['pyannote.audio'] = types.ModuleType('pyannote.audio')\n"
        "from meeting_assistant.bootstrap.ffmpeg_dll import ensure_ffmpeg_dlls\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    ensure_ffmpeg_dlls(strict=False)\n"
        "    print(int(any(w.category is RuntimeWarning for w in caught)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True
    )
    assert result.stdout.strip().splitlines()[-1] == "1"
