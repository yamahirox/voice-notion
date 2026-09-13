#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$TaskName = "VoiceToNotionUvicorn"

& "$PSScriptRoot\Stop-VoiceServer.ps1"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "タスクは登録されていません: $TaskName"
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "削除しました: $TaskName"
