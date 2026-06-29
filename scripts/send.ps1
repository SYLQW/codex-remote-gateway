param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Text,
    [string]$Platform = "cli",
    [string]$ChatId = "local",
    [string]$UserId = "me",
    [string]$UserName = "me"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location -LiteralPath $ProjectRoot

python -m codex_remote_gateway send $Text --platform $Platform --chat-id $ChatId --user-id $UserId --user-name $UserName
