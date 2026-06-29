$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location -LiteralPath $ProjectRoot

if (-not $env:CODEX_BRIDGE_APPROVAL_POLICY) {
    $env:CODEX_BRIDGE_APPROVAL_POLICY = "never"
}
if (-not $env:CODEX_BRIDGE_PROGRESS_INTERVAL_SECONDS) {
    $env:CODEX_BRIDGE_PROGRESS_INTERVAL_SECONDS = "180"
}
if (-not $env:CODEX_BRIDGE_PROGRESS_FAILURE_COOLDOWN_SECONDS) {
    $env:CODEX_BRIDGE_PROGRESS_FAILURE_COOLDOWN_SECONDS = "600"
}

python -m codex_remote_gateway serve-http --host 127.0.0.1 --port 8765
