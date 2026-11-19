"""Keep Windows filesystem paths and child-process working directories usable."""

from __future__ import annotations

import os
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

_MAX_PATH = 260
_MAX_DIRECTORY = 248
_EXTENDED_PREFIX = "\\\\?\\"


def _windows_length(path: Path) -> int:
    return len(str(path).encode("utf-16-le", errors="surrogatepass")) // 2


def filesystem_path(path: Path, *, reserve: int = 0) -> Path:
    if os.name != "nt" or str(path).startswith(_EXTENDED_PREFIX) or _windows_length(path) + reserve < _MAX_DIRECTORY:
        return path
    value = os.path.abspath(path)
    if value.startswith("\\\\"):
        return Path(_EXTENDED_PREFIX + "UNC\\" + value[2:])
    return Path(_EXTENDED_PREFIX + value)


@contextmanager
def process_working_directory(path: Path) -> Iterator[Path]:
    if os.name != "nt" or (_windows_length(path) < _MAX_PATH and not str(path).startswith(_EXTENDED_PREFIX)):
        yield path
        return

    from _winapi import CreateJunction

    # CreateProcessW cannot start in an extended-length working directory.
    value = str(path)
    if value.startswith(_EXTENDED_PREFIX + "UNC\\"):
        value = "\\\\" + value[len(_EXTENDED_PREFIX + "UNC\\"):]
    elif value.startswith(_EXTENDED_PREFIX):
        value = value[len(_EXTENDED_PREFIX):]
    working = Path(os.path.abspath(value))
    if _windows_length(working) < _MAX_PATH:
        yield working
        return
    if working.drive.startswith("\\\\"):
        raise OSError("Windows에서 긴 네트워크 작업 경로를 열 수 없습니다. 짧은 로컬 경로를 사용해 주세요.")

    with ExitStack() as stack:
        directory = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="awo-")))
        index = 0
        while _windows_length(working) >= _MAX_PATH:
            ancestor = next(parent for parent in working.parents if _windows_length(parent) < _MAX_DIRECTORY)
            junction = directory / str(index)
            shortened = junction / working.relative_to(ancestor)
            if _windows_length(shortened) >= _windows_length(working):
                raise OSError("Windows에서 작업 폴더 경로를 줄일 수 없습니다. 프로젝트 경로를 줄여 주세요.")
            CreateJunction(str(ancestor), str(junction))
            stack.callback(junction.rmdir)
            working = shortened
            index += 1
        yield working
