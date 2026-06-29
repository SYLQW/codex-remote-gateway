from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import Platform


@dataclass
class SessionSource:
    platform: Platform
    chat_id: str
    chat_name: Optional[str] = None
    chat_type: str = "dm"
    user_id: Optional[str] = None
    user_name: Optional[str] = None
    thread_id: Optional[str] = None
    chat_topic: Optional[str] = None
    user_id_alt: Optional[str] = None
    chat_id_alt: Optional[str] = None
    is_bot: bool = False
    guild_id: Optional[str] = None
    parent_chat_id: Optional[str] = None
    message_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform.value,
            "chat_id": self.chat_id,
            "chat_name": self.chat_name,
            "chat_type": self.chat_type,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "thread_id": self.thread_id,
            "chat_topic": self.chat_topic,
            "user_id_alt": self.user_id_alt,
            "chat_id_alt": self.chat_id_alt,
            "is_bot": self.is_bot,
            "guild_id": self.guild_id,
            "parent_chat_id": self.parent_chat_id,
            "message_id": self.message_id,
        }


def _canonical_whatsapp_identifier(value: str | None) -> str | None:
    if not value:
        return value
    return str(value).split("@", 1)[0]


def is_shared_multi_user_session(
    source: SessionSource,
    *,
    group_sessions_per_user: bool = True,
    thread_sessions_per_user: bool = False,
) -> bool:
    if source.chat_type == "dm":
        return False
    if source.thread_id:
        return not thread_sessions_per_user
    return not group_sessions_per_user


def build_session_key(
    source: SessionSource,
    group_sessions_per_user: bool = True,
    thread_sessions_per_user: bool = False,
) -> str:
    platform = getattr(source.platform, "value", str(source.platform))
    if source.chat_type == "dm":
        dm_chat_id = source.chat_id
        if source.platform == Platform.WHATSAPP:
            dm_chat_id = _canonical_whatsapp_identifier(source.chat_id)

        if dm_chat_id:
            if source.thread_id:
                return f"agent:main:{platform}:dm:{dm_chat_id}:{source.thread_id}"
            return f"agent:main:{platform}:dm:{dm_chat_id}"
        if source.thread_id:
            return f"agent:main:{platform}:dm:{source.thread_id}"
        return f"agent:main:{platform}:dm"

    participant_id = source.user_id_alt or source.user_id
    if participant_id and source.platform == Platform.WHATSAPP:
        participant_id = _canonical_whatsapp_identifier(str(participant_id)) or participant_id

    key_parts = ["agent:main", platform, source.chat_type or "group"]
    if source.chat_id:
        key_parts.append(str(source.chat_id))
    if source.thread_id:
        key_parts.append(str(source.thread_id))

    isolate_user = group_sessions_per_user
    if source.thread_id and not thread_sessions_per_user:
        isolate_user = False

    if isolate_user and participant_id:
        key_parts.append(str(participant_id))

    return ":".join(key_parts)
