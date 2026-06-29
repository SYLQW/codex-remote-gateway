from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SUPPORTED_PLATFORMS: dict[str, dict[str, Any]] = {
    "weixin": {
        "label": "微信",
        "adapter": "gateway.platforms.weixin:WeixinAdapter",
        "fields": ["account_id", "token", "base_url", "cdn_base_url", "dm_policy", "group_policy"],
    },
    "dingtalk": {
        "label": "钉钉",
        "adapter": "gateway.platforms.dingtalk:DingTalkAdapter",
        "fields": ["client_id", "client_secret", "robot_code", "card_template_id"],
    },
    "telegram": {
        "label": "Telegram",
        "adapter": "gateway.platforms.telegram:TelegramAdapter",
        "fields": ["token", "require_mention"],
    },
    "slack": {
        "label": "Slack",
        "adapter": "gateway.platforms.slack:SlackAdapter",
        "fields": ["bot_token", "app_token", "signing_secret", "require_mention"],
    },
    "feishu": {
        "label": "飞书",
        "adapter": "gateway.platforms.feishu:FeishuAdapter",
        "fields": ["app_id", "app_secret", "encrypt_key", "verification_token"],
    },
    "wecom": {
        "label": "企业微信",
        "adapter": "gateway.platforms.wecom:WeComAdapter",
        "fields": ["bot_id", "secret", "websocket_url", "dm_policy", "group_policy"],
    },
    "webhook": {
        "label": "Webhook",
        "adapter": "gateway.platforms.webhook:WebhookAdapter",
        "fields": ["host", "port", "path", "secret"],
    },
}


DEFAULT_CONFIG: dict[str, Any] = {
    "admin": {"host": "127.0.0.1", "port": 8770},
    "platforms": {
        name: {"enabled": False, "extra": {}} for name in SUPPORTED_PLATFORMS
    },
}


def gateway_home() -> Path:
    return Path(os.getenv("CODEX_REMOTE_GATEWAY_HOME", str(Path.home() / ".codex-remote-gateway")))


def config_path() -> Path:
    return Path(os.getenv("CODEX_REMOTE_GATEWAY_CONFIG", str(gateway_home() / "config.json")))


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    data = json.loads(path.read_text(encoding="utf-8"))
    return merge_config(DEFAULT_CONFIG, data)


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = json.loads(json.dumps(base))
    _deep_update(result, override)
    return result


def _deep_update(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_update(target[key], value)
        else:
            target[key] = value
