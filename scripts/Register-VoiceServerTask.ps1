#Requires -Version 5.1
# ログオン時にバックグラウンドで音声→Notion サーバ (uvicorn) を起動する Windows タスクを登録します。
# 右クリック → PowerShell で実行、または: powershell -ExecutionPolicy Bypass -File .\Register-VoiceServerTask.ps1
$ErrorActionPreference = "Stop"

$TaskName = "VoiceToNotionUvicorn"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Port = 8765

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Error "python.exe が見つかりません。Python をインストールし、PATH に追加してから再度実行してください。"
    exit 1
}

$argList = "-m uvicorn sandbox.app.voice_server:app --host 0.0.0.0 --port $Port"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "既存のタスクを削除しました: $TaskName"
}

$action = New-ScheduledTaskAction -Execute $python -Argument $argList -WorkingDirectory $ProjectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "音声→Notion: プロジェクト $ProjectRoot の uvicorn (ポート $Port)" | Out-Null

Write-Host "登録完了: $TaskName"
Write-Host "  作業フォルダ: $ProjectRoot"
Write-Host "  Python: $python"
Write-Host ""
Write-Host "【別のやり方】ウィンドウを閉じても動かすには、どちらか:"
Write-Host "  A) タスク登録（このスクリプト）… PCログオンのたびに自動起動"
Write-Host "  B) scripts\バックグラウンドで起動.bat … その都度裏で起動（再起動まで継続）"
Write-Host ""
Write-Host "【今すぐ1回だけ起動する】以下を実行してください:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "【停止】 scripts\Stop-VoiceServer.ps1 または タスク スケジューラで無効化"
Write-Host "【削除】 scripts\Unregister-VoiceServerTask.ps1"
