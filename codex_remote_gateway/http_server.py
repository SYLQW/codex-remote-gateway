from __future__ import annotations

import asyncio
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .core import BridgeService, SourceIdentity

logger = logging.getLogger(__name__)


class CodexRemoteGatewayHandler(BaseHTTPRequestHandler):
    server_version = "codex-remote-gateway/0.1"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json({"ok": True})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path not in {"/message", "/webhook"}:
            self._send_json({"error": "not found"}, status=404)
            return

        try:
            payload = self._read_json()
            result = asyncio.run(self._handle_payload(payload))
        except Exception as exc:
            logger.exception("request failed")
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=500)
            return
        self._send_json(result)

    async def _handle_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = str(payload.get("text") or payload.get("message") or "")
        ident = SourceIdentity(
            platform=str(payload.get("platform") or "webhook"),
            chat_id=str(payload.get("chat_id") or payload.get("chatId") or "default"),
            user_id=str(payload.get("user_id") or payload.get("userId") or "default"),
            user_name=str(payload.get("user_name") or payload.get("userName") or ""),
        )
        replies: list[str] = []

        async def collect(message: str) -> None:
            replies.append(message)

        handled = await BridgeService().handle_message(text, ident, collect)
        return {"handled": handled, "replies": replies}

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def run_http_server(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), CodexRemoteGatewayHandler)
    logger.info("codex-remote-gateway HTTP server listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
