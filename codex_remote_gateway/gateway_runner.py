from __future__ import annotations

import asyncio
import importlib
import logging
import os
import signal
from typing import Any

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageEvent

from .config_store import SUPPORTED_PLATFORMS, load_config
from .core import BridgeService, SourceIdentity, _chunks, _redact, _safe_text

logger = logging.getLogger(__name__)


class StandaloneGatewayRunner:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or load_config()
        self.service = BridgeService()
        self.adapters = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        for name, platform_cfg in (self.config.get("platforms") or {}).items():
            if not platform_cfg.get("enabled"):
                continue
            adapter = self._build_adapter(name, platform_cfg)
            if adapter is None:
                continue
            adapter.set_message_handler(self._handle_event)
            ok = await adapter.connect()
            if ok:
                self.adapters[name] = adapter
                logger.info("%s connected", name)
            else:
                logger.warning("%s did not connect", name)

    async def stop(self) -> None:
        for name, adapter in list(self.adapters.items()):
            try:
                await adapter.disconnect()
            except Exception:
                logger.exception("disconnect failed for %s", name)
        self.adapters.clear()

    async def run_forever(self) -> None:
        await self.start()
        if not self.adapters:
            logger.warning("No platform adapters are connected. Open the admin panel and enable a platform.")
        await self._stop_event.wait()
        await self.stop()

    def stop_soon(self) -> None:
        self._stop_event.set()

    def _build_adapter(self, name: str, platform_cfg: dict[str, Any]):
        meta = SUPPORTED_PLATFORMS.get(name)
        if not meta:
            logger.warning("Unsupported platform in config: %s", name)
            return None
        module_name, class_name = str(meta["adapter"]).split(":", 1)
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        extra = dict(platform_cfg.get("extra") or {})
        self._apply_env_compat(name, extra)
        cfg = PlatformConfig(
            enabled=bool(platform_cfg.get("enabled")),
            token=platform_cfg.get("token") or extra.get("token") or extra.get("bot_token"),
            api_key=platform_cfg.get("api_key") or extra.get("api_key"),
            reply_to_mode=str(platform_cfg.get("reply_to_mode") or "first"),
            gateway_restart_notification=bool(platform_cfg.get("gateway_restart_notification", True)),
            extra=extra,
        )
        return cls(cfg)

    def _apply_env_compat(self, name: str, extra: dict[str, Any]) -> None:
        mappings = {
            "slack": {
                "bot_token": "SLACK_BOT_TOKEN",
                "app_token": "SLACK_APP_TOKEN",
                "signing_secret": "SLACK_SIGNING_SECRET",
            },
            "telegram": {"token": "TELEGRAM_BOT_TOKEN"},
            "weixin": {
                "account_id": "WEIXIN_ACCOUNT_ID",
                "token": "WEIXIN_TOKEN",
                "base_url": "WEIXIN_BASE_URL",
                "cdn_base_url": "WEIXIN_CDN_BASE_URL",
            },
            "dingtalk": {
                "client_id": "DINGTALK_CLIENT_ID",
                "client_secret": "DINGTALK_CLIENT_SECRET",
            },
            "feishu": {
                "app_id": "FEISHU_APP_ID",
                "app_secret": "FEISHU_APP_SECRET",
                "encrypt_key": "FEISHU_ENCRYPT_KEY",
                "verification_token": "FEISHU_VERIFICATION_TOKEN",
                "connection_mode": "FEISHU_CONNECTION_MODE",
            },
            "wecom": {
                "bot_id": "WECOM_BOT_ID",
                "secret": "WECOM_SECRET",
                "websocket_url": "WECOM_WEBSOCKET_URL",
            },
        }
        for key, env_name in mappings.get(name, {}).items():
            value = str(extra.get(key) or "").strip()
            if value:
                os.environ[env_name] = value

    async def _handle_event(self, event: MessageEvent):
        source = event.source
        platform = str(getattr(getattr(source, "platform", None), "value", getattr(source, "platform", "")) or "")
        ident = SourceIdentity(
            platform=platform,
            chat_id=str(getattr(source, "chat_id", "") or ""),
            user_id=str(getattr(source, "user_id", "") or ""),
            user_name=str(getattr(source, "user_name", "") or ""),
        )
        adapter = self.adapters.get(platform)
        if adapter is None:
            adapter = self.adapters.get(str(platform).lower())
        if adapter is None:
            logger.warning("No adapter found for platform=%s", platform)
            return None

        async def send(text: str) -> None:
            safe = _redact(_safe_text(text, 14400))
            for chunk in _chunks(safe, 3600):
                await adapter.send(
                    source.chat_id,
                    chunk,
                    metadata={"thread_id": getattr(source, "thread_id", None)} if getattr(source, "thread_id", None) else None,
                )

        handled = await self.service.handle_message(event.text or "", ident, send)
        if not handled:
            await send("当前聊天还没有绑定 Codex thread。发送 `/codex threads` 开始绑定。")
        return None


def run_standalone_gateway() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    runner = StandaloneGatewayRunner()

    async def main() -> None:
        loop = asyncio.get_running_loop()
        for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None)):
            if sig is None:
                continue
            try:
                loop.add_signal_handler(sig, runner.stop_soon)
            except NotImplementedError:
                pass
        await runner.run_forever()

    asyncio.run(main())
