from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping


def application_config_root(
    *, platform: str | None = None, environment: Mapping[str, str] | None = None, home: Path | None = None,
) -> Path:
    selected_platform = platform or sys.platform
    selected_environment = environment if environment is not None else os.environ
    selected_home = (home or Path.home()).expanduser().resolve()
    if selected_platform == "win32":
        configured = selected_environment.get("APPDATA", "").strip()
        base = Path(configured).expanduser() if configured else selected_home / "AppData" / "Roaming"
    elif selected_platform == "darwin":
        base = selected_home / "Library" / "Application Support"
    else:
        configured = selected_environment.get("XDG_CONFIG_HOME", "").strip()
        base = Path(configured).expanduser() if configured else selected_home / ".config"
    return (base / "ai-work-orchestrator").resolve()
