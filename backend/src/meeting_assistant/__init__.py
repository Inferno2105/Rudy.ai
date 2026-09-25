"""Local multilingual (Hindi-English) meeting assistant.

Importing this package must stay cheap. It deliberately exposes nothing but
``__version__``, and in particular must never pull in ``pyannote.audio``,
``torch`` or ``faster_whisper``.

Two reasons, and the first one is load-bearing rather than cosmetic:

1. On Windows, ``pyannote.audio`` transitively loads TorchCodec, which resolves
   FFmpeg's ``avcodec-*.dll`` at extension-load time. The FFmpeg directory has
   to be registered with the DLL loader *before* that first import, which
   ``meeting_assistant.bootstrap.ffmpeg_dll`` handles. A convenience re-export
   here would pull pyannote in as a side effect of importing anything at all,
   defeating that ordering and producing an opaque ``OSError: [WinError 126]``
   much later, at diarization time.
2. Model imports cost seconds. The CLI needs to be able to print help, validate
   configuration and report errors without paying for them.

``tests/test_import_order.py`` enforces this, so keep every ``__init__.py`` in
this package free of re-exports.
"""

__version__ = "0.1.0"
