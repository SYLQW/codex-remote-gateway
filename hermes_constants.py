from __future__ import annotations

import os
from pathlib import Path


def get_hermes_home() -> Path:
    return Path(os.getenv("CODEX_REMOTE_GATEWAY_HOME", str(Path.home() / ".codex-remote-gateway")))


def get_hermes_dir(*parts: str) -> Path:
    base = get_hermes_home()
    if not parts:
        return base
    return base.joinpath(*(part for part in parts if part))


def get_default_hermes_root() -> Path:
    return Path.cwd()


def display_hermes_home() -> str:
    return str(get_hermes_home())
