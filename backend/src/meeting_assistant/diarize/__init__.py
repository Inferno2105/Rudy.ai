# Intentionally empty.
#
# Do NOT add convenience re-exports here (e.g. `from .pyannote_diarizer import
# load_pipeline`). The modules in this subpackage import `pyannote.audio`, which
# must not be imported until `bootstrap.ffmpeg_dll.ensure_ffmpeg_dlls()` has
# registered FFmpeg's DLL directory with the Windows loader. A re-export here
# would trigger that import as a side effect of touching the subpackage at all,
# and the resulting failure is an opaque OSError [WinError 126] raised later,
# during diarization. Import the concrete modules directly instead.
