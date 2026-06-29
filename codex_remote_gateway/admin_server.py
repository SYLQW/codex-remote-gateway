from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .config_store import SUPPORTED_PLATFORMS, config_path, gateway_home, load_config, save_config

logger = logging.getLogger(__name__)


MINIMAL_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Remote Gateway - Minimal</title>
</head>
<body>
  <h1>Codex Remote Gateway</h1>
  <p>Minimal page ok.</p>
</body>
</html>
"""

NO_JS_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Remote Gateway - No JS</title>
  <style>
    body { font: 14px/1.45 "Segoe UI", system-ui, sans-serif; margin: 24px; }
    code { background: #f2f2f2; padding: 2px 4px; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>Codex Remote Gateway</h1>
  <p>这是无 JavaScript 诊断页。如果这个页面也能让 Codex Desktop 崩溃，问题基本在 Codex 内置浏览器打开 localhost 的链路上。</p>
  <p>配置接口：<code>/api/config</code></p>
</body>
</html>
"""


INDEX_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Codex Remote Gateway</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f7f7f4;
      --panel: #ffffff;
      --text: #1d2328;
      --muted: #66717d;
      --line: #d9ded7;
      --accent: #146c5f;
      --accent-2: #2b5c85;
      --danger: #a33b32;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg: #101314;
        --panel: #181d1f;
        --text: #e8ece9;
        --muted: #98a3a7;
        --line: #30383b;
        --accent: #52b8a8;
        --accent-2: #7eb0dd;
        --danger: #ef8c82;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 14px/1.45 "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    .wrap {
      max-width: 1180px;
      margin: 0 auto;
      padding: 18px 22px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 650;
      letter-spacing: 0;
    }
    .sub {
      margin-top: 4px;
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }
    .toolbar {
      display: flex;
      gap: 10px;
      align-items: center;
      justify-content: space-between;
      margin: 18px 0;
      flex-wrap: wrap;
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--text);
      padding: 8px 12px;
      border-radius: 6px;
      cursor: pointer;
      font: inherit;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }
    button:hover { filter: brightness(0.98); }
    .status {
      color: var(--muted);
      min-height: 22px;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
    }
    section.card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
    }
    .card-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 10px;
    }
    h2 {
      margin: 0;
      font-size: 16px;
      letter-spacing: 0;
    }
    .toggle {
      display: inline-flex;
      gap: 6px;
      align-items: center;
      color: var(--muted);
      white-space: nowrap;
    }
    label.field {
      display: block;
      margin-top: 9px;
    }
    label.field span {
      display: block;
      color: var(--muted);
      margin-bottom: 4px;
      font-size: 12px;
    }
    input, select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: transparent;
      color: var(--text);
      padding: 8px;
      font: inherit;
      min-height: 36px;
    }
    .admin {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 10px;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      margin-bottom: 14px;
    }
    .note {
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }
    .danger { color: var(--danger); }
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1>Codex Remote Gateway</h1>
      <div id="path" class="sub">正在读取配置...</div>
    </div>
  </header>
  <main class="wrap">
    <div class="toolbar">
      <div class="status" id="status"></div>
      <div>
        <button id="reload">重新载入</button>
        <button class="primary" id="save">保存配置</button>
      </div>
    </div>
    <div class="admin">
      <label class="field"><span>管理面板 Host</span><input id="admin-host" autocomplete="off"></label>
      <label class="field"><span>管理面板 Port</span><input id="admin-port" type="number" min="1" max="65535"></label>
    </div>
    <div id="platforms" class="grid"></div>
    <p class="note danger">提示：这是本机配置面板，默认只监听 127.0.0.1。不要把它暴露到公网。</p>
  </main>
  <script>
    let schema = {};
    let config = {};

    const $ = id => document.getElementById(id);
    const status = text => { $("status").textContent = text || ""; };

    async function load() {
      status("读取中...");
      const res = await fetch("/api/config");
      const data = await res.json();
      schema = data.schema;
      config = data.config;
      $("path").textContent = "配置文件：" + data.path;
      render();
      status("已载入");
    }

    function render() {
      $("admin-host").value = config.admin?.host || "127.0.0.1";
      $("admin-port").value = config.admin?.port || 8770;
      const root = $("platforms");
      root.innerHTML = "";
      Object.entries(schema).forEach(([name, meta]) => {
        const cfg = config.platforms?.[name] || { enabled: false, extra: {} };
        const card = document.createElement("section");
        card.className = "card";
        const head = document.createElement("div");
        head.className = "card-head";
        head.innerHTML = `<h2>${escapeHtml(meta.label || name)}</h2>`;
        const toggle = document.createElement("label");
        toggle.className = "toggle";
        toggle.innerHTML = `<input type="checkbox" data-platform="${name}" data-key="enabled" ${cfg.enabled ? "checked" : ""}> 启用`;
        head.appendChild(toggle);
        card.appendChild(head);
        (meta.fields || []).forEach(field => {
          const label = document.createElement("label");
          label.className = "field";
          const value = cfg.extra?.[field] ?? cfg[field] ?? "";
          const secret = /secret|token|key|password/i.test(field);
          label.innerHTML = `<span>${escapeHtml(field)}</span><input ${secret ? 'type="password"' : 'type="text"'} data-platform="${name}" data-key="${escapeAttr(field)}" value="${escapeAttr(value)}" autocomplete="off">`;
          card.appendChild(label);
        });
        const note = document.createElement("div");
        note.className = "note";
        note.textContent = "Adapter: " + meta.adapter;
        card.appendChild(note);
        root.appendChild(card);
      });
    }

    function collect() {
      const next = JSON.parse(JSON.stringify(config || {}));
      next.admin = next.admin || {};
      next.admin.host = $("admin-host").value.trim() || "127.0.0.1";
      next.admin.port = Number($("admin-port").value || 8770);
      next.platforms = next.platforms || {};
      document.querySelectorAll("[data-platform]").forEach(input => {
        const platform = input.dataset.platform;
        const key = input.dataset.key;
        next.platforms[platform] = next.platforms[platform] || { enabled: false, extra: {} };
        if (key === "enabled") {
          next.platforms[platform].enabled = input.checked;
        } else {
          next.platforms[platform].extra = next.platforms[platform].extra || {};
          next.platforms[platform].extra[key] = input.value;
        }
      });
      return next;
    }

    async function save() {
      status("保存中...");
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collect())
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || "保存失败");
      }
      const data = await res.json();
      config = data.config;
      render();
      status("已保存。重启 gateway 后生效。");
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
    }
    function escapeAttr(value) {
      return escapeHtml(value).replace(/`/g, "&#96;");
    }

    $("reload").onclick = () => load().catch(err => status(err.message));
    $("save").onclick = () => save().catch(err => status(err.message));
    load().catch(err => status(err.message));
  </script>
</body>
</html>
"""


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "codex-remote-admin/0.1"

    def do_GET(self) -> None:
        logger.info("GET %s from %s", self.path, self.client_address[0])
        if self.path in {"/", "/index.html"}:
            self._send_html(INDEX_HTML)
            return
        if self.path == "/minimal":
            self._send_html(MINIMAL_HTML)
            return
        if self.path == "/no-js":
            self._send_html(NO_JS_HTML)
            return
        if self.path == "/api/config":
            self._send_json({"config": load_config(), "schema": SUPPORTED_PLATFORMS, "path": str(config_path())})
            return
        if self.path == "/healthz":
            self._send_json({"ok": True})
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        logger.info("POST %s from %s", self.path, self.client_address[0])
        if self.path != "/api/config":
            self._send_json({"error": "not found"}, status=404)
            return
        try:
            payload = self._read_json()
            if not isinstance(payload, dict):
                raise ValueError("config must be a JSON object")
            save_config(payload)
            self._send_json({"ok": True, "config": load_config(), "path": str(config_path())})
        except Exception as exc:
            logger.exception("failed to save config")
            self._send_json({"error": f"{type(exc).__name__}: {exc}"}, status=400)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def _send_html(self, html: str) -> None:
        raw = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)


def _ensure_file_logging() -> None:
    log_path = gateway_home() / "admin.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", None) == str(log_path):
            return
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)


def run_admin_server(host: str = "127.0.0.1", port: int = 8770) -> None:
    _ensure_file_logging()
    server = ThreadingHTTPServer((host, port), AdminHandler)
    logger.info("admin panel listening on http://%s:%s", host, port)
    logger.info("admin log: %s", gateway_home() / "admin.log")
    try:
        server.serve_forever()
    finally:
        server.server_close()
