from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_LOCKS: dict[str, dict[str, Any]] = {}


def _status_dir() -> Path:
    path = Path(os.getenv("CODEX_REMOTE_GATEWAY_HOME", str(Path.home() / ".codex-remote-gateway"))) / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def acquire_scoped_lock(scope: str, identity: str | None = None, metadata: dict[str, Any] | None = None):
    existing = _LOCKS.get(scope)
    if existing:
        return False, existing
    record = {"scope": scope, "identity": identity, "pid": os.getpid(), "metadata": metadata or {}}
    _LOCKS[scope] = record
    return True, record


def release_scoped_lock(scope: str, identity: str | None = None) -> None:
    existing = _LOCKS.get(scope)
    if not existing:
        return
    if identity is None or existing.get("identity") == identity:
        _LOCKS.pop(scope, None)


def write_runtime_status(platform: str, status: str | None = None, **kwargs: Any) -> None:
    state = status or kwargs.get("platform_state") or "unknown"
    payload = {"platform": platform, "status": state, "pid": os.getpid(), **kwargs}
    path = _status_dir() / f"{platform}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
