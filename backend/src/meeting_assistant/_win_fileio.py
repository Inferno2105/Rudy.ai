"""Windows file primitives that let atomic replaces coexist with readers.

Background: :func:`meeting_assistant.io_utils.write_json` writes a temp file
and renames it over the target, so a reader always sees a complete artifact.
On Windows that rename fails while *any* other handle has the target open --
``os.replace`` uses ``MoveFileExW``, which refuses to replace an open file
regardless of how it was opened. Before the HTTP API existed, nothing read an
artifact while its run was writing it; with the API polling manifests and
transcripts during a run, the run's own writes started failing at random.

The two halves of the fix, both verified on this machine before being relied on:

* :func:`open_shared_read` opens with ``FILE_SHARE_DELETE`` (which Python's
  ``open()`` never requests), declaring that this reader tolerates the file
  being renamed or replaced underneath it.
* :func:`posix_replace` renames with POSIX semantics
  (``FileRenameInfoEx`` + ``FILE_RENAME_FLAG_POSIX_SEMANTICS``, Windows 10
  1709+): the target name is swapped immediately even while such readers hold
  the old file open, and they keep reading the old contents -- exactly the
  atomic-swap behaviour the writers already assume.

A reader that did not use ``FILE_SHARE_DELETE`` (another program, or a plain
``open()`` elsewhere) still blocks the swap; the caller retries briefly for
that case. Filesystems without POSIX rename support (FAT, some network
shares) report it as unsupported and the caller falls back to ``os.replace``.
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import IO

_GENERIC_READ = 0x80000000
_DELETE = 0x00010000
_SHARE_READ_WRITE_DELETE = 0x1 | 0x2 | 0x4
_OPEN_EXISTING = 3
_FILE_ATTRIBUTE_NORMAL = 0x80
_FILE_RENAME_INFO_EX = 22
_RENAME_REPLACE_IF_EXISTS = 0x1
_RENAME_POSIX_SEMANTICS = 0x2
_INVALID_HANDLE = wintypes.HANDLE(-1).value

# Windows error codes meaning "this filesystem can't do POSIX renames".
UNSUPPORTED_ERRORS = frozenset({1, 50, 87})  # INVALID_FUNCTION, NOT_SUPPORTED, INVALID_PARAMETER

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_create_file = _kernel32.CreateFileW
_create_file.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_create_file.restype = wintypes.HANDLE

_set_file_information = _kernel32.SetFileInformationByHandle
_set_file_information.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
_set_file_information.restype = wintypes.BOOL

_close_handle = _kernel32.CloseHandle
_close_handle.argtypes = [wintypes.HANDLE]
_close_handle.restype = wintypes.BOOL


def _open_handle(path: Path, access: int) -> int:
    handle = _create_file(
        str(path),
        access,
        _SHARE_READ_WRITE_DELETE,
        None,
        _OPEN_EXISTING,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if handle is None or handle == _INVALID_HANDLE:
        error = ctypes.get_last_error()
        raise OSError(None, ctypes.FormatError(error), str(path), error)
    return handle


def open_shared_read(path: Path) -> IO[str]:
    """Open ``path`` as UTF-8 text, allowing it to be replaced while open."""
    import msvcrt

    handle = _open_handle(path, _GENERIC_READ)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY)
    except Exception:
        _close_handle(handle)
        raise
    return open(fd, encoding="utf-8")


def posix_replace(src: Path, dst: Path) -> None:
    """Rename ``src`` over ``dst`` with POSIX semantics.

    Raises:
        OSError: with ``winerror`` in :data:`UNSUPPORTED_ERRORS` if the
            filesystem cannot do this; a ``PermissionError`` if a reader that
            did not allow deletion holds ``dst`` open.
    """
    target = str(Path(dst).resolve())

    class _FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * (len(target) + 1)),
        ]

    info = _FileRenameInfo(
        _RENAME_REPLACE_IF_EXISTS | _RENAME_POSIX_SEMANTICS,
        None,
        len(target) * ctypes.sizeof(wintypes.WCHAR),
        target,
    )

    handle = _open_handle(Path(src), _DELETE)
    try:
        ok = _set_file_information(
            handle, _FILE_RENAME_INFO_EX, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            error = ctypes.get_last_error()
            raise OSError(None, ctypes.FormatError(error), str(dst), error)
    finally:
        _close_handle(handle)
