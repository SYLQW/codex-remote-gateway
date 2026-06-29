param(
    [string]$HermesConfig = "G:\Hermes\.sandbox\hermes-home\config.yaml",
    [string]$HermesEnv = "G:\Hermes\.sandbox\hermes-home\.env"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location -LiteralPath $ProjectRoot
$HermesPython = "G:\Hermes\.venv\Scripts\python.exe"
$Python = if (Test-Path -LiteralPath $HermesPython) { $HermesPython } else { "python" }

$script = @'
import json
import sys
from pathlib import Path

try:
    import yaml
except Exception as exc:
    raise SystemExit(f"PyYAML is required to migrate Hermes config: {exc}")

from codex_remote_gateway.config_store import SUPPORTED_PLATFORMS, load_config, save_config, config_path

source = Path(sys.argv[1])
env_source = Path(sys.argv[2]) if len(sys.argv) > 2 else None
if not source.exists():
    raise SystemExit(f"Hermes config not found: {source}")

data = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
gateway = data.get("gateway") or {}
platforms = gateway.get("platforms") or data.get("platforms") or {}
config = load_config()
config.setdefault("platforms", {})

def read_env(path):
    result = {}
    if not path or not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        value = value.strip().strip('"').strip("'")
        result[key.strip()] = value
    return result

env = read_env(env_source)

for name in SUPPORTED_PLATFORMS:
    src = platforms.get(name)
    if not isinstance(src, dict):
        continue
    dst = config["platforms"].setdefault(name, {"enabled": False, "extra": {}})
    if "enabled" in src:
        dst["enabled"] = bool(src.get("enabled"))
    for key in ("token", "api_key", "reply_to_mode", "gateway_restart_notification"):
        if key in src:
            dst[key] = src[key]
    dst_extra = dst.setdefault("extra", {})
    src_extra = src.get("extra")
    if isinstance(src_extra, dict):
        dst_extra.update(src_extra)

env_mappings = {
    "weixin": {
        "WEIXIN_ACCOUNT_ID": "account_id",
        "WEIXIN_TOKEN": "token",
        "WEIXIN_BASE_URL": "base_url",
        "WEIXIN_CDN_BASE_URL": "cdn_base_url",
        "WEIXIN_DM_POLICY": "dm_policy",
        "WEIXIN_GROUP_POLICY": "group_policy",
    },
    "dingtalk": {
        "DINGTALK_CLIENT_ID": "client_id",
        "DINGTALK_CLIENT_SECRET": "client_secret",
        "DINGTALK_ROBOT_CODE": "robot_code",
        "DINGTALK_CARD_TEMPLATE_ID": "card_template_id",
    },
    "telegram": {
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_REQUIRE_MENTION": "require_mention",
    },
    "slack": {
        "SLACK_BOT_TOKEN": "bot_token",
        "SLACK_APP_TOKEN": "app_token",
        "SLACK_SIGNING_SECRET": "signing_secret",
        "SLACK_REQUIRE_MENTION": "require_mention",
    },
    "feishu": {
        "FEISHU_APP_ID": "app_id",
        "FEISHU_APP_SECRET": "app_secret",
        "FEISHU_ENCRYPT_KEY": "encrypt_key",
        "FEISHU_VERIFICATION_TOKEN": "verification_token",
        "FEISHU_CONNECTION_MODE": "connection_mode",
    },
    "wecom": {
        "WECOM_BOT_ID": "bot_id",
        "WECOM_SECRET": "secret",
        "WECOM_WEBSOCKET_URL": "websocket_url",
    },
}

for name, mapping in env_mappings.items():
    dst = config["platforms"].setdefault(name, {"enabled": False, "extra": {}})
    dst_extra = dst.setdefault("extra", {})
    for env_key, field in mapping.items():
        if env.get(env_key):
            dst_extra[field] = env[env_key]

save_config(config)
print(f"Migrated platform config to: {config_path()}")
'@

$script | & $Python - $HermesConfig $HermesEnv
