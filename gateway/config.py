from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
        return default
    return bool(value)


class Platform(Enum):
    LOCAL = "local"
    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    SLACK = "slack"
    SIGNAL = "signal"
    MATTERMOST = "mattermost"
    MATRIX = "matrix"
    HOMEASSISTANT = "homeassistant"
    EMAIL = "email"
    SMS = "sms"
    DINGTALK = "dingtalk"
    API_SERVER = "api_server"
    WEBHOOK = "webhook"
    MSGRAPH_WEBHOOK = "msgraph_webhook"
    FEISHU = "feishu"
    WECOM = "wecom"
    WECOM_CALLBACK = "wecom_callback"
    WEIXIN = "weixin"
    BLUEBUBBLES = "bluebubbles"
    QQBOT = "qqbot"
    YUANBAO = "yuanbao"

    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip().lower()
        pseudo = object.__new__(cls)
        pseudo._value_ = normalized
        pseudo._name_ = normalized.upper().replace("-", "_").replace(" ", "_")
        cls._value2member_map_[normalized] = pseudo
        cls._member_map_[pseudo._name_] = pseudo
        return pseudo


@dataclass
class HomeChannel:
    platform: Platform
    chat_id: str
    name: str = "Home"
    thread_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {"platform": self.platform.value, "chat_id": self.chat_id, "name": self.name}
        if self.thread_id:
            data["thread_id"] = self.thread_id
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HomeChannel":
        return cls(
            platform=Platform(data["platform"]),
            chat_id=str(data["chat_id"]),
            name=str(data.get("name") or "Home"),
            thread_id=str(data["thread_id"]) if data.get("thread_id") else None,
        )


@dataclass
class PlatformConfig:
    enabled: bool = False
    token: Optional[str] = None
    api_key: Optional[str] = None
    home_channel: Optional[HomeChannel] = None
    reply_to_mode: str = "first"
    gateway_restart_notification: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "enabled": self.enabled,
            "reply_to_mode": self.reply_to_mode,
            "gateway_restart_notification": self.gateway_restart_notification,
            "extra": self.extra,
        }
        if self.token:
            data["token"] = self.token
        if self.api_key:
            data["api_key"] = self.api_key
        if self.home_channel:
            data["home_channel"] = self.home_channel.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlatformConfig":
        home_channel = HomeChannel.from_dict(data["home_channel"]) if data.get("home_channel") else None
        return cls(
            enabled=_coerce_bool(data.get("enabled"), False),
            token=data.get("token"),
            api_key=data.get("api_key"),
            home_channel=home_channel,
            reply_to_mode=str(data.get("reply_to_mode") or "first"),
            gateway_restart_notification=_coerce_bool(data.get("gateway_restart_notification"), True),
            extra=dict(data.get("extra") or {}),
        )


@dataclass
class GatewayConfig:
    platforms: Dict[Platform, PlatformConfig] = field(default_factory=dict)
    home_channels: Dict[Platform, HomeChannel] = field(default_factory=dict)


@dataclass
class SessionResetPolicy:
    mode: str = "both"
    at_hour: int = 4
    idle_minutes: int = 1440
    notify: bool = True
