# codex-remote-gateway

独立版 Codex 远程网关。它把来自外部聊天平台、HTTP webhook 或命令行的消息转发给本机 Codex Desktop 的 thread。

当前项目已经把 Codex 控制核心从 Hermes 插件里抽出来：

```text
外部消息入口
  -> BridgeService
  -> 本地 codex app-server ws://127.0.0.1:<临时端口>
  -> Codex thread / turn
  -> send(text) 回调返回进度和最终回复
```

## 当前入口

- `python -m codex_remote_gateway send ...`
  本机命令行测试入口。
- `python -m codex_remote_gateway serve-http`
  独立 HTTP JSON webhook 服务。
- `python -m codex_remote_gateway serve-admin`
  本地配置面板，默认 http://127.0.0.1:8770。
- `python -m codex_remote_gateway serve-gateway`
  按配置启动微信、钉钉、Telegram、Slack、飞书、企业微信、Webhook 等平台 adapter。
- `python -m codex_remote_gateway serve-all`
  同时启动配置面板和平台网关。
- `codex_remote_gateway.core.BridgeService`
  给微信、钉钉、企业微信等平台适配器复用的核心类。
- `integrations/hermes-plugin`
  Hermes Gateway 兼容包装层，只负责把 Hermes hook 接到 standalone 核心。

Hermes 插件版可以继续跑；这个目录是独立化后的项目。

## 安装

```powershell
cd G:\Hermes\codex-remote-gateway
python -m pip install -e .
```

如果你把项目 clone 到其他位置，把上面的 `G:\Hermes\codex-remote-gateway`
换成自己的项目目录即可。

安装所有已迁移平台依赖：

```powershell
python -m pip install -e ".[all-platforms]"
```

也可以不安装，直接在项目目录里运行：

```powershell
python -m codex_remote_gateway send "/codex threads"
```

## 配置面板

启动配置面板：

```powershell
python -m codex_remote_gateway serve-admin
```

打开：

```text
http://127.0.0.1:8770
```

配置文件默认写入：

```text
C:\Users\你\.codex-remote-gateway\config.json
```

配置好平台参数后，启动完整独立网关：

```powershell
python -m codex_remote_gateway serve-gateway
```

或者一条命令同时启动网关和面板：

```powershell
python -m codex_remote_gateway serve-all
```

Windows 脚本：

```powershell
.\scripts\start-admin.ps1
.\scripts\start-all.ps1
```

## 已迁移平台

首批已迁移 Hermes adapter：

```text
weixin      微信个人号 iLink
dingtalk    钉钉 Stream Mode 机器人
telegram    Telegram Bot
slack       Slack Socket Mode
feishu      飞书
wecom       企业微信机器人 websocket
webhook     通用 webhook
```

## 命令行测试

列出最近 Codex 会话：

```powershell
python -m codex_remote_gateway send "/codex threads" --platform cli --chat-id local --user-id me
```

绑定一个 thread：

```powershell
python -m codex_remote_gateway send "/codex use 1" --platform cli --chat-id local --user-id me
```

绑定后发送普通消息：

```powershell
python -m codex_remote_gateway send "帮我看一下当前任务状态" --platform cli --chat-id local --user-id me
```

## HTTP Webhook

启动服务：

```powershell
python -m codex_remote_gateway serve-http --host 127.0.0.1 --port 8765
```

发送消息：

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8765/message `
  -ContentType "application/json; charset=utf-8" `
  -Body (@{
    platform = "weixin"
    chat_id = "demo-chat"
    user_id = "demo-user"
    text = "/codex threads"
  } | ConvertTo-Json -Compress)
```

响应格式：

```json
{
  "handled": true,
  "replies": ["..."]
}
```

## 支持的命令

```text
/codex help
/codex threads [数量]
/codex use <序号或thread-id>
/codex where
/codex tail [数量]
/codex ask <消息>
/codex off
```

绑定后，同一个 `platform + chat_id + user_id` 发来的普通非 slash 消息会被转发给绑定的 Codex thread。

## 环境变量

```text
CODEX_REMOTE_GATEWAY_HOME=C:\Users\你\.codex-remote-gateway
CODEX_BRIDGE_ALLOWED_USERS=weixin:<user-or-chat-id>
CODEX_BRIDGE_CODEX_EXE=C:\path\to\codex.exe
CODEX_BRIDGE_TURN_TIMEOUT_SECONDS=1800
CODEX_BRIDGE_PROGRESS_INTERVAL_SECONDS=180
CODEX_BRIDGE_PROGRESS_FAILURE_COOLDOWN_SECONDS=600
CODEX_BRIDGE_PROGRESS_MAX_ITEMS=3
CODEX_BRIDGE_PROGRESS_MAX_CHARS=1000
CODEX_BRIDGE_MAX_REPLY_CHARS=3600
CODEX_BRIDGE_APPROVAL_POLICY=never
CODEX_BRIDGE_SANDBOX_MODE=
```

如果你明确要让远程 Codex 使用完全访问权限，可以设置：

```powershell
$env:CODEX_BRIDGE_SANDBOX_MODE = "danger-full-access"
$env:CODEX_BRIDGE_APPROVAL_POLICY = "never"
```

这等价于让远程聊天能触发无审批本机操作，风险很高，建议只在自己私聊、限定用户、可信网络下使用。

## 与 Hermes 版本的关系

Hermes 插件版是旧方案，仍然可用。

这个目录是独立版：它已经内置一批 Hermes 平台 adapter，并用 `StandaloneGatewayRunner`
把平台消息直接接到 Codex，不再需要 Hermes Gateway 先运行。
