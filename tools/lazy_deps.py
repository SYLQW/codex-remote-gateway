from __future__ import annotations

import importlib


_ALIASES = {
    "platform.dingtalk": "dingtalk_stream",
    "platform.telegram": "telegram",
    "platform.slack": "slack_bolt",
    "platform.feishu": "lark_oapi",
}


def ensure(module_name: str, *args, **kwargs):
    del args, kwargs
    return importlib.import_module(_ALIASES.get(module_name, module_name))


def ensure_and_bind(module_name: str, import_fn=None, target_globals: dict | None = None, *args, **kwargs):
    del args, kwargs
    if callable(import_fn):
        values = import_fn()
        if target_globals is not None and isinstance(values, dict):
            target_globals.update(values)
        return True
    ensure(module_name)
    return True
