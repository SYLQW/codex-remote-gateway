from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def is_truthy_value(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
        return default
    return bool(value)


def atomic_replace(tmp_path: str | Path, target: str | Path) -> str:
    os.replace(str(tmp_path), str(target))
    return str(target)


def atomic_json_write(path: str | Path, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    atomic_replace(tmp, target)


def normalize_proxy_url(proxy_url: str | None) -> str | None:
    if not proxy_url:
        return None
    value = str(proxy_url).strip()
    if not value:
        return None
    if "://" not in value:
        return "http://" + value
    return value
