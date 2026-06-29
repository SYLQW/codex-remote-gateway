from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import threading

from .core import BridgeService, SourceIdentity
from .http_server import run_http_server
from .admin_server import run_admin_server
from .config_store import load_config
from .gateway_runner import run_standalone_gateway


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-remote-gateway")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging.")
    sub = parser.add_subparsers(dest="command", required=True)

    send = sub.add_parser("send", help="Send one message through the bridge and print replies.")
    send.add_argument("text", help="Message text, for example '/codex threads'.")
    send.add_argument("--platform", default="cli")
    send.add_argument("--chat-id", default="cli")
    send.add_argument("--user-id", default="local")
    send.add_argument("--user-name", default="local")

    serve = sub.add_parser("serve-http", help="Run a local HTTP JSON webhook server.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    admin = sub.add_parser("serve-admin", help="Run the local configuration panel.")
    admin.add_argument("--host", default=None)
    admin.add_argument("--port", type=int, default=None)

    sub.add_parser("serve-gateway", help="Run configured messaging platform adapters.")

    all_cmd = sub.add_parser("serve-all", help="Run platform adapters and the admin panel.")
    all_cmd.add_argument("--admin-host", default=None)
    all_cmd.add_argument("--admin-port", type=int, default=None)

    return parser


async def _send_once(args: argparse.Namespace) -> int:
    service = BridgeService()
    ident = SourceIdentity(
        platform=args.platform,
        chat_id=args.chat_id,
        user_id=args.user_id,
        user_name=args.user_name,
    )

    async def emit(text: str) -> None:
        print(text)
        print("", flush=True)

    handled = await service.handle_message(args.text, ident, emit)
    if not handled:
        print("消息未被 codex-remote-gateway 处理。绑定后发普通消息，或使用 /codex 命令。")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "send":
        return asyncio.run(_send_once(args))
    if args.command == "serve-http":
        run_http_server(args.host, args.port)
        return 0
    if args.command == "serve-admin":
        config = load_config()
        admin_cfg = config.get("admin") or {}
        run_admin_server(args.host or admin_cfg.get("host") or "127.0.0.1", args.port or int(admin_cfg.get("port") or 8770))
        return 0
    if args.command == "serve-gateway":
        run_standalone_gateway()
        return 0
    if args.command == "serve-all":
        config = load_config()
        admin_cfg = config.get("admin") or {}
        host = args.admin_host or admin_cfg.get("host") or "127.0.0.1"
        port = args.admin_port or int(admin_cfg.get("port") or 8770)
        thread = threading.Thread(target=run_admin_server, args=(host, port), daemon=True)
        thread.start()
        logging.info("admin panel started on http://%s:%s", host, port)
        run_standalone_gateway()
        return 0

    parser.print_help(sys.stderr)
    return 2
