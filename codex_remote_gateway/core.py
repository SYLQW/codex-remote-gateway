from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable


PLUGIN_NAME = "codex-remote-gateway"
logger = logging.getLogger(__name__)
STATE_DIR = Path(
    os.getenv(
        "CODEX_REMOTE_GATEWAY_HOME",
        os.getenv("CODEX_BRIDGE_HOME", str(Path.home() / ".codex-remote-gateway")),
    )
)
STATE_PATH = STATE_DIR / "state.json"
MAX_REPLY_CHARS = int(os.getenv("CODEX_BRIDGE_MAX_REPLY_CHARS", "3600"))
TURN_TIMEOUT_SECONDS = float(os.getenv("CODEX_BRIDGE_TURN_TIMEOUT_SECONDS", "1800"))
PROGRESS_INTERVAL_SECONDS = float(os.getenv("CODEX_BRIDGE_PROGRESS_INTERVAL_SECONDS", "180"))
PROGRESS_FAILURE_COOLDOWN_SECONDS = float(os.getenv("CODEX_BRIDGE_PROGRESS_FAILURE_COOLDOWN_SECONDS", "600"))
PROGRESS_MAX_ITEMS = int(os.getenv("CODEX_BRIDGE_PROGRESS_MAX_ITEMS", "3"))
PROGRESS_MAX_CHARS = int(os.getenv("CODEX_BRIDGE_PROGRESS_MAX_CHARS", "1000"))
APPROVAL_POLICY = os.getenv("CODEX_BRIDGE_APPROVAL_POLICY", "never").strip()
SANDBOX_MODE = os.getenv("CODEX_BRIDGE_SANDBOX_MODE", "").strip()

_SOURCE_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class SourceIdentity:
    platform: str
    chat_id: str
    user_id: str
    user_name: str

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.chat_id}:{self.user_id}"


SendText = Callable[[str], Awaitable[None]]


class BridgeService:
    async def handle_message(self, text: str, ident: SourceIdentity, send: SendText) -> bool:
        text = (text or "").strip()
        if not text:
            return False

        is_command = _is_codex_command(text)
        state = _load_state()
        has_binding = ident.key in state.get("bindings", {})
        should_forward_plain = has_binding and not text.startswith("/")
        if not is_command and not should_forward_plain:
            return False

        if not _is_allowed(ident):
            await send("codex-remote-gateway: 你没有权限使用远程 Codex。")
            return True

        try:
            if is_command:
                await self._handle_command(text, ident, send)
            else:
                await self._forward_to_bound_thread(text, ident, send)
        except Exception as exc:
            await send(f"codex-remote-gateway 出错：{type(exc).__name__}: {_safe_text(str(exc), 500)}")
        return True

    async def _handle_command(self, text: str, ident: SourceIdentity, send: SendText) -> None:
        raw = _strip_codex_prefix(text).strip()
        if not raw or raw in {"help", "-h", "--help"}:
            await send(_help_text())
            return

        cmd, rest = _split_once(raw)
        cmd = cmd.lower().replace("_", "-")

        if cmd in {"threads", "list", "ls"}:
            limit = _parse_int(rest, default=8, minimum=1, maximum=20)
            threads = _list_threads(limit)
            state = _load_state()
            state.setdefault("last_thread_lists", {})[ident.key] = [t["id"] for t in threads]
            _save_state(state)
            await send(_format_threads(threads))
            return

        if cmd == "use":
            await self._cmd_use(ident, rest, send)
            return

        if cmd in {"where", "status"}:
            binding = _binding_for(ident)
            if not binding:
                await send("当前聊天还没有绑定 Codex thread。先发 `/codex threads`，再发 `/codex use <序号>`。")
                return
            await send(_format_binding(binding))
            return

        if cmd in {"off", "unbind", "disable"}:
            state = _load_state()
            removed = state.get("bindings", {}).pop(ident.key, None)
            _save_state(state)
            await send("已取消当前聊天的 Codex thread 绑定。" if removed else "当前聊天没有 Codex 绑定。")
            return

        if cmd == "tail":
            binding = _binding_for(ident)
            if not binding:
                await send("当前聊天还没有绑定 Codex thread。")
                return
            count = _parse_int(rest, default=1, minimum=1, maximum=5)
            messages = _tail_thread(binding["thread_id"], count)
            await send(_format_tail(messages))
            return

        if cmd == "ask":
            if not rest.strip():
                await send("用法：`/codex ask <要发给 Codex 的内容>`")
                return
            await self._forward_to_bound_thread(rest.strip(), ident, send)
            return

        await send(f"未知 /codex 子命令：{cmd}\n\n{_help_text()}")

    async def _cmd_use(self, ident: SourceIdentity, rest: str, send: SendText) -> None:
        arg = rest.strip()
        if not arg:
            await send("用法：`/codex use <序号或thread-id>`")
            return

        state = _load_state()
        thread_id = arg
        if arg.isdigit():
            ids = state.get("last_thread_lists", {}).get(ident.key, [])
            index = int(arg) - 1
            if index < 0 or index >= len(ids):
                await send("这个序号不在最近的 `/codex threads` 列表里。")
                return
            thread_id = ids[index]

        thread = _get_thread(thread_id)
        if not thread:
            await send(f"没有找到 Codex thread：{thread_id}")
            return

        state.setdefault("bindings", {})[ident.key] = {
            "thread_id": thread["id"],
            "title": thread.get("title") or thread.get("preview") or "",
            "cwd": thread.get("cwd") or "",
            "bound_at": int(time.time()),
        }
        _save_state(state)
        await send("已绑定：\n" + _format_binding(state["bindings"][ident.key]))

    async def _forward_to_bound_thread(self, message: str, ident: SourceIdentity, send: SendText) -> None:
        binding = _binding_for(ident)
        if not binding:
            await send("当前聊天还没有绑定 Codex thread。")
            return

        lock = _SOURCE_LOCKS.setdefault(ident.key, asyncio.Lock())
        if lock.locked():
            await send("这个聊天已经有一个 Codex 请求在跑，等它完成后再发下一条。")
            return

        async with lock:
            await send(f"已转发给 Codex：{_short_thread_label(binding)}")
            codex = CodexAppServer()
            started_at = time.time()
            await codex.start()
            try:
                result = await codex.send_turn(binding["thread_id"], message, progress_callback=send)
            finally:
                await codex.stop()

        final_text = result.strip() or "Codex 已完成，但没有生成可转发的文本。"
        await send(f"Codex 回复（用时 {_format_duration(time.time() - started_at)}）：\n{final_text}")


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", _pre_gateway_dispatch)


def _pre_gateway_dispatch(event, gateway, session_store):
    text = (getattr(event, "text", "") or "").strip()
    if not text:
        return None

    ident = _identity_from_event(event)
    is_command = _is_codex_command(text)
    state = _load_state()
    has_binding = ident.key in state.get("bindings", {})

    # Slash commands that are not /codex should remain Hermes commands.
    should_forward_plain = has_binding and not text.startswith("/")
    if not is_command and not should_forward_plain:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return None

    loop.create_task(_handle_gateway_event(event, gateway, text, ident, is_command))
    return {"action": "skip", "reason": "codex-remote-gateway"}


async def _handle_gateway_event(event, gateway, text: str, ident: SourceIdentity, is_command: bool) -> None:
    del is_command

    async def send(message: str) -> None:
        await _send(gateway, event.source, message)

    await BridgeService().handle_message(text, ident, send)


async def _handle_command(event, gateway, text: str, ident: SourceIdentity) -> None:
    raw = _strip_codex_prefix(text).strip()
    if not raw or raw in {"help", "-h", "--help"}:
        await _send(gateway, event.source, _help_text())
        return

    cmd, rest = _split_once(raw)
    cmd = cmd.lower().replace("_", "-")

    if cmd in {"threads", "list", "ls"}:
        limit = _parse_int(rest, default=8, minimum=1, maximum=20)
        threads = _list_threads(limit)
        state = _load_state()
        state.setdefault("last_thread_lists", {})[ident.key] = [t["id"] for t in threads]
        _save_state(state)
        await _send(gateway, event.source, _format_threads(threads))
        return

    if cmd == "use":
        await _cmd_use(event, gateway, ident, rest)
        return

    if cmd in {"where", "status"}:
        binding = _binding_for(ident)
        if not binding:
            await _send(gateway, event.source, "当前聊天还没有绑定 Codex thread。先发 `/codex threads`，再发 `/codex use <序号>`。")
            return
        await _send(gateway, event.source, _format_binding(binding))
        return

    if cmd in {"off", "unbind", "disable"}:
        state = _load_state()
        removed = state.get("bindings", {}).pop(ident.key, None)
        _save_state(state)
        await _send(gateway, event.source, "已取消当前聊天的 Codex thread 绑定。" if removed else "当前聊天没有 Codex 绑定。")
        return

    if cmd == "tail":
        binding = _binding_for(ident)
        if not binding:
            await _send(gateway, event.source, "当前聊天还没有绑定 Codex thread。")
            return
        count = _parse_int(rest, default=1, minimum=1, maximum=5)
        messages = _tail_thread(binding["thread_id"], count)
        await _send(gateway, event.source, _format_tail(messages))
        return

    if cmd == "ask":
        if not rest.strip():
            await _send(gateway, event.source, "用法：`/codex ask <要发给 Codex 的内容>`")
            return
        await _forward_to_bound_thread(event, gateway, rest.strip(), ident)
        return

    await _send(gateway, event.source, f"未知 /codex 子命令：{cmd}\n\n{_help_text()}")


async def _cmd_use(event, gateway, ident: SourceIdentity, rest: str) -> None:
    arg = rest.strip()
    if not arg:
        await _send(gateway, event.source, "用法：`/codex use <序号或thread-id>`")
        return

    state = _load_state()
    thread_id = arg
    if arg.isdigit():
        ids = state.get("last_thread_lists", {}).get(ident.key, [])
        index = int(arg) - 1
        if index < 0 or index >= len(ids):
            await _send(gateway, event.source, "这个序号不在最近的 `/codex threads` 列表里。")
            return
        thread_id = ids[index]

    thread = _get_thread(thread_id)
    if not thread:
        await _send(gateway, event.source, f"没有找到 Codex thread：{thread_id}")
        return

    state.setdefault("bindings", {})[ident.key] = {
        "thread_id": thread["id"],
        "title": thread.get("title") or thread.get("preview") or "",
        "cwd": thread.get("cwd") or "",
        "bound_at": int(time.time()),
    }
    _save_state(state)
    await _send(gateway, event.source, "已绑定：\n" + _format_binding(state["bindings"][ident.key]))


async def _forward_to_bound_thread(event, gateway, message: str, ident: SourceIdentity) -> None:
    binding = _binding_for(ident)
    if not binding:
        await _send(gateway, event.source, "当前聊天还没有绑定 Codex thread。")
        return

    lock = _SOURCE_LOCKS.setdefault(ident.key, asyncio.Lock())
    if lock.locked():
        await _send(gateway, event.source, "这个聊天已经有一个 Codex 请求在跑，等它完成后再发下一条。")
        return

    async with lock:
        await _send(gateway, event.source, f"已转发给 Codex：{_short_thread_label(binding)}")
        codex = CodexAppServer()
        started_at = time.time()

        async def send_progress(summary: str) -> None:
            await _send(gateway, event.source, summary)

        await codex.start()
        try:
            result = await codex.send_turn(binding["thread_id"], message, progress_callback=send_progress)
        finally:
            await codex.stop()

    final_text = result.strip() or "Codex 已完成，但没有生成可转发的文本。"
    await _send(gateway, event.source, f"Codex 回复（用时 {_format_duration(time.time() - started_at)}）：\n{final_text}")


class CodexAppServer:
    def __init__(self) -> None:
        self.codex_exe = _find_codex_exe()
        self.port = _free_tcp_port()
        self.proc: asyncio.subprocess.Process | None = None
        self.ws = None
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._reader_task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.codex_exe:
            raise RuntimeError("找不到 Codex CLI。可设置 CODEX_BRIDGE_CODEX_EXE 指向 codex.exe。")

        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        args = [
            str(self.codex_exe),
            "app-server",
            "--listen",
            f"ws://127.0.0.1:{self.port}",
            "--analytics-default-enabled",
        ]
        if APPROVAL_POLICY:
            args.extend(["-c", f'approval_policy="{APPROVAL_POLICY}"'])
        if SANDBOX_MODE:
            args.extend(["-c", f'sandbox_mode="{SANDBOX_MODE}"'])

        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        await self._wait_ready()

        import websockets

        self.ws = await websockets.connect(f"ws://127.0.0.1:{self.port}/", max_size=16 * 1024 * 1024)
        self._reader_task = asyncio.create_task(self._reader())
        await self.rpc(
            "initialize",
            {
                "clientInfo": {"name": "codex-remote-gateway", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True},
            },
        )

    async def stop(self) -> None:
        if self.ws is not None:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self.proc is not None and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self.proc.kill()

    async def send_turn(
        self,
        thread_id: str,
        text: str,
        progress_callback: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        await self.rpc("thread/resume", {"threadId": thread_id, "excludeTurns": True})
        progress_start_line = _rollout_line_count(thread_id)
        started_at = time.time()
        last_progress_sent = started_at
        progress_muted_until = 0.0
        response = await self.rpc(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": text}],
                "responsesapiClientMetadata": {"codex_remote_gateway": "standalone"},
            },
        )
        turn_id = ((response or {}).get("turn") or {}).get("id")
        if not turn_id:
            raise RuntimeError("Codex 没有返回 turn id。")

        chunks: list[str] = []
        completed_turn: dict[str, Any] | None = None
        deadline = time.time() + TURN_TIMEOUT_SECONDS
        while time.time() < deadline:
            now = time.time()
            if (
                progress_callback is not None
                and PROGRESS_INTERVAL_SECONDS > 0
                and now >= progress_muted_until
                and now - started_at >= PROGRESS_INTERVAL_SECONDS
                and now - last_progress_sent >= PROGRESS_INTERVAL_SECONDS
            ):
                try:
                    await progress_callback(_build_progress_summary(thread_id, progress_start_line, now - started_at))
                except Exception as exc:
                    progress_muted_until = now + PROGRESS_FAILURE_COOLDOWN_SECONDS
                    logger.warning(
                        "codex-remote-gateway progress send failed; muting progress for %.1fs: %s",
                        PROGRESS_FAILURE_COOLDOWN_SECONDS,
                        exc,
                    )
                finally:
                    last_progress_sent = now

            timeout = max(0.1, min(2.0, deadline - time.time()))
            try:
                msg = await asyncio.wait_for(self._notifications.get(), timeout=timeout)
            except asyncio.TimeoutError:
                continue
            method = msg.get("method")
            params = msg.get("params") or {}
            if params.get("threadId") != thread_id:
                continue
            if params.get("turnId") not in {None, turn_id}:
                continue
            if method == "item/agentMessage/delta":
                chunks.append(str(params.get("delta") or ""))
            elif method == "turn/completed":
                completed_turn = params.get("turn") or {}
                break

        if completed_turn is None:
            raise TimeoutError("等待 Codex 回复超时。")

        text_out = _extract_agent_text_from_turn(completed_turn)
        if not text_out:
            text_out = "".join(chunks).strip()
        return text_out

    async def rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if self.ws is None:
            raise RuntimeError("Codex app-server 尚未连接。")
        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[request_id] = future
        await self.ws.send(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}))
        response = await asyncio.wait_for(future, timeout=60)
        if "error" in response:
            err = response["error"]
            raise RuntimeError(err.get("message") or json.dumps(err, ensure_ascii=False))
        return response.get("result")

    async def _reader(self) -> None:
        assert self.ws is not None
        async for raw in self.ws:
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self._pending:
                future = self._pending.pop(msg["id"])
                if not future.done():
                    future.set_result(msg)
            else:
                await self._notifications.put(msg)

    async def _wait_ready(self) -> None:
        url = f"http://127.0.0.1:{self.port}/readyz"
        for _ in range(80):
            if self.proc is not None and self.proc.returncode is not None:
                raise RuntimeError("Codex app-server 启动后立即退出。")
            try:
                ok = await asyncio.to_thread(_http_ok, url)
                if ok:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.25)
        raise TimeoutError("Codex app-server 没有就绪。")


def _identity_from_event(event) -> SourceIdentity:
    source = event.source
    platform = str(getattr(getattr(source, "platform", None), "value", getattr(source, "platform", "")) or "")
    return SourceIdentity(
        platform=platform,
        chat_id=str(getattr(source, "chat_id", "") or ""),
        user_id=str(getattr(source, "user_id", "") or ""),
        user_name=str(getattr(source, "user_name", "") or ""),
    )


def _is_allowed(ident: SourceIdentity) -> bool:
    raw = os.getenv("CODEX_BRIDGE_ALLOWED_USERS", "").strip()
    if not raw:
        return True
    allowed = {part.strip() for part in re.split(r"[,;]", raw) if part.strip()}
    candidates = {
        ident.user_id,
        f"{ident.platform}:{ident.user_id}",
        f"{ident.platform}:{ident.chat_id}",
        ident.key,
    }
    return bool(allowed & candidates)


def _is_codex_command(text: str) -> bool:
    lower = text.strip().lower()
    return lower == "/codex" or lower.startswith("/codex ")


def _strip_codex_prefix(text: str) -> str:
    stripped = text.strip()
    return stripped[6:] if stripped.lower().startswith("/codex") else stripped


def _split_once(text: str) -> tuple[str, str]:
    parts = text.strip().split(maxsplit=1)
    if not parts:
        return "", ""
    return parts[0], parts[1] if len(parts) > 1 else ""


def _parse_int(text: str, *, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int((text or "").strip().split()[0])
    except Exception:
        value = default
    return max(minimum, min(maximum, value))


def _load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"bindings": {}, "last_thread_lists": {}}


def _save_state(state: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _binding_for(ident: SourceIdentity) -> dict[str, Any] | None:
    return _load_state().get("bindings", {}).get(ident.key)


def _codex_home() -> Path:
    raw = os.getenv("CODEX_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".codex"


def _state_db() -> Path:
    explicit = os.getenv("CODEX_BRIDGE_STATE_DB")
    if explicit:
        return Path(explicit)
    candidates = sorted(_codex_home().glob("state_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError("找不到 Codex state_*.sqlite。")
    return candidates[0]


def _connect_state_db() -> sqlite3.Connection:
    con = sqlite3.connect(_state_db())
    con.row_factory = sqlite3.Row
    return con


def _list_threads(limit: int) -> list[dict[str, Any]]:
    with _connect_state_db() as con:
        rows = con.execute(
            """
            select id, title, cwd, updated_at, preview
            from threads
            where archived = 0
            order by updated_at desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [_thread_row_to_dict(row) for row in rows]


def _get_thread(thread_id: str) -> dict[str, Any] | None:
    with _connect_state_db() as con:
        row = con.execute(
            "select id, title, cwd, updated_at, preview from threads where id = ?",
            (thread_id,),
        ).fetchone()
    return _thread_row_to_dict(row) if row else None


def _thread_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"] or "",
        "cwd": _clean_win_path(row["cwd"] or ""),
        "updated_at": row["updated_at"],
        "preview": row["preview"] or "",
    }


def _tail_thread(thread_id: str, count: int) -> list[str]:
    rollout = _rollout_path_for_thread(thread_id)
    if not rollout or not rollout.exists():
        return [f"找不到 thread 的本地记录文件：{thread_id}"]

    messages: list[str] = []
    for line in rollout.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            payload = (json.loads(line).get("payload") or {})
        except Exception:
            continue
        if payload.get("type") != "message" or payload.get("role") != "assistant":
            continue
        text = _extract_message_payload_text(payload)
        if text:
            messages.append(text)
    return messages[-count:] if messages else ["这个 thread 里暂时没有可提取的 assistant 回复。"]


def _rollout_path_for_thread(thread_id: str) -> Path | None:
    with _connect_state_db() as con:
        row = con.execute("select rollout_path from threads where id = ?", (thread_id,)).fetchone()
    if row and row["rollout_path"]:
        path = Path(str(row["rollout_path"]))
        if path.exists():
            return path
    matches = list((_codex_home() / "sessions").rglob(f"*{thread_id}.jsonl"))
    return matches[0] if matches else None


def _rollout_line_count(thread_id: str) -> int:
    rollout = _rollout_path_for_thread(thread_id)
    if not rollout or not rollout.exists():
        return 0
    try:
        with rollout.open("r", encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except Exception:
        return 0


def _progress_items_since(thread_id: str, start_line: int) -> list[str]:
    rollout = _rollout_path_for_thread(thread_id)
    if not rollout or not rollout.exists():
        return []

    items: list[str] = []
    try:
        with rollout.open("r", encoding="utf-8", errors="replace") as fh:
            for index, line in enumerate(fh):
                if index < start_line:
                    continue
                try:
                    payload = (json.loads(line).get("payload") or {})
                except Exception:
                    continue

                item = _progress_text_from_payload(payload)
                if item:
                    items.append(item)
    except Exception:
        return []
    return _dedupe_keep_order(items)


def _progress_text_from_payload(payload: dict[str, Any]) -> str:
    kind = payload.get("type")
    phase = payload.get("phase")
    if kind == "agent_message" and phase != "final_answer":
        return _one_line(payload.get("message") or "")
    if kind == "message" and payload.get("role") == "assistant" and phase != "final_answer":
        return _one_line(_extract_message_payload_text(payload))
    if kind == "patch_apply_end":
        return "已应用文件修改。"
    if kind == "web_search_call":
        action = payload.get("action") or {}
        query = action.get("query") or action.get("url") or ""
        return _one_line(f"正在查资料：{query}") if query else "正在查资料。"
    if kind in {"function_call", "custom_tool_call"}:
        name = payload.get("name") or "工具"
        return _one_line(f"正在调用 {name}。")
    return ""


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _extract_message_payload_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in payload.get("content") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"output_text", "text"}:
            parts.append(str(item.get("text") or ""))
    return "\n".join(part for part in parts if part).strip()


def _extract_agent_text_from_turn(turn: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in turn.get("items") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "agentMessage":
            parts.append(str(item.get("text") or ""))
        elif item.get("type") == "message" and item.get("role") == "assistant":
            parts.append(_extract_message_payload_text(item))
    return "\n".join(part for part in parts if part).strip()


def _find_codex_exe() -> Path | None:
    explicit = os.getenv("CODEX_BRIDGE_CODEX_EXE")
    if explicit and Path(explicit).exists():
        return Path(explicit)

    local = os.getenv("LOCALAPPDATA")
    if local:
        candidates = sorted(
            Path(local).glob("OpenAI/Codex/bin/*/codex.exe"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0]

    found = shutil.which("codex") or shutil.which("codex.exe")
    return Path(found) if found else None


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _http_ok(url: str) -> bool:
    with urllib.request.urlopen(url, timeout=1.0) as response:
        return 200 <= response.status < 300


async def _send(gateway, source, text: str) -> None:
    adapter = gateway.adapters.get(source.platform)
    if adapter is None:
        return
    for chunk in _chunks(_redact(_safe_text(text, MAX_REPLY_CHARS * 4)), MAX_REPLY_CHARS):
        await adapter.send(source.chat_id, chunk)


def _chunks(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _redact(text: str) -> str:
    text = re.sub(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{12,}\b", "[REDACTED]", text)
    return re.sub(r"(?i)\b(Bearer\s+)[A-Za-z0-9._\-]{20,}", r"\1[REDACTED]", text)


def _safe_text(text: str, max_chars: int) -> str:
    text = str(text or "")
    return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]"


def _clean_win_path(path: str) -> str:
    return path[4:] if path.startswith("\\\\?\\") else path


def _short_thread_label(binding: dict[str, Any]) -> str:
    title = binding.get("title") or binding.get("thread_id", "")
    return _safe_text(str(title).replace("\n", " "), 80)


def _format_threads(threads: list[dict[str, Any]]) -> str:
    if not threads:
        return "没有找到 Codex thread。"
    lines = ["最近的 Codex threads："]
    for i, thread in enumerate(threads, 1):
        title = (thread.get("title") or thread.get("preview") or "(no title)").replace("\n", " ")
        lines.append(
            f"{i}. {_safe_text(title, 64)}\n"
            f"   id: {thread['id']}\n"
            f"   cwd: {thread.get('cwd') or '-'}"
        )
    lines.append("\n绑定示例：`/codex use 1`")
    return "\n".join(lines)


def _format_binding(binding: dict[str, Any]) -> str:
    return (
        f"Codex thread: {binding.get('thread_id')}\n"
        f"title: {_safe_text(str(binding.get('title') or ''), 120)}\n"
        f"cwd: {binding.get('cwd') or '-'}"
    )


def _format_tail(messages: list[str]) -> str:
    return "\n\n---\n\n".join(_safe_text(m, MAX_REPLY_CHARS) for m in messages)


def _build_progress_summary(thread_id: str, start_line: int, elapsed_seconds: float) -> str:
    items = _progress_items_since(thread_id, start_line)
    lines = [f"Codex 仍在运行（已 {_format_duration(elapsed_seconds)}）："]
    if items:
        lines.append("最近进度：")
        for item in items[-PROGRESS_MAX_ITEMS:]:
            lines.append(f"- {_safe_text(item, PROGRESS_MAX_CHARS)}")
    else:
        lines.append("暂时没有新的可见进度，仍在等待 Codex 完成。")
    return "\n".join(lines)


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    if minutes <= 0:
        return f"{secs} 秒"
    hours, minutes = divmod(minutes, 60)
    if hours <= 0:
        return f"{minutes} 分 {secs} 秒"
    return f"{hours} 小时 {minutes} 分 {secs} 秒"


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _help_text() -> str:
    return (
        "codex-remote-gateway 命令：\n"
        "`/codex threads [数量]` 列出最近 Codex 会话\n"
        "`/codex use <序号或thread-id>` 绑定当前聊天\n"
        "`/codex where` 查看绑定\n"
        "`/codex ask <消息>` 发给绑定的 Codex thread\n"
        "`/codex tail [数量]` 查看最近 Codex 回复\n"
        "`/codex off` 取消绑定\n\n"
        "绑定后，当前聊天里的普通非 slash 消息会转发给 Codex。"
    )
