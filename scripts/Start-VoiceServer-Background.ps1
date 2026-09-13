#Requires -Version 5.1
# uvicorn を別プロセスで起動します。このウィンドウを閉じてもサーバは動き続けます（PC再起動までは）。
# 停止: Stop-VoiceServer.ps1 または サーバを止める.bat
$ErrorActionPreference = "Stop"

$Port = 8765
$ProjectRoot = Split-Path -Parent $PSScriptRoot

$listen = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($listen) {
    Write-Host "ポート $Port は既に待ち受けています。"
    Write-Host "  ブラウザ: http://127.0.0.1:$Port/"
    exit 0
}

$python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
if (-not $python) {
    Write-Error "python.exe が見つかりません。Python を PATH に追加してから再実行してください。"
    exit 1
}

$arguments = @(
    "-m", "uvicorn",
    "sandbox.app.voice_server:app",
    "--host", "0.0.0.0",
    "--port", "$Port"
)

$proc = Start-Process `
    -FilePath $python `
    -ArgumentList $arguments `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru

Write-Host "バックグラウンドで起動しました (PID $($proc.Id))。"
Write-Host "  作業フォルダ: $ProjectRoot"
Write-Host "  ブラウザ: http://127.0.0.1:$Port/  （スマホLANなら PCのIP: $Port ）"
Write-Host ""
Write-Host "停止する: scripts\Stop-VoiceServer.ps1 または サーバを止める.bat"
