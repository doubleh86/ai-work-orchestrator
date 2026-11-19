"""Build child environments from the variables each runtime needs."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping


_RUNTIME_VARIABLES = frozenset({
    "PATH", "PATHEXT", "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PROGRAMFILES", "PROGRAMFILES(X86)",
    "PROGRAMW6432", "PROGRAMDATA", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOMEDRIVE", "HOMEPATH",
    "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR",
})


def runtime_environment(
    source: Mapping[str, str] | None = None, *, extra: Iterable[str] = (),
) -> dict[str, str]:
    environment = os.environ if source is None else source
    allowed = _RUNTIME_VARIABLES.union(extra)
    if os.name == "nt":
        return {name.upper(): value for name, value in environment.items() if name.upper() in allowed}
    return {name: value for name, value in environment.items() if name in allowed}
