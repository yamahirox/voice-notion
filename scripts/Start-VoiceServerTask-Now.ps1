#Requires -Version 5.1
# タスクに登録済みのサーバを、いますぐ1回起動します（PC再起動を待たない）。
$ErrorActionPreference = "Stop"
$TaskName = "VoiceToNotionUvicorn"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Error "先に Register-VoiceServerTask.ps1 を実行してタスクを登録してください。"
    exit 1
}

Start-ScheduledTask -TaskName $TaskName
Write-Host "起動トリガーを送りました: $TaskName"
Write-Host "数秒待ってからブラウザで http://127.0.0.1:8765 を開いてください。"
