@echo off
REM PowerShell 5.1 + 日本語表示: スクリプトは UTF-8 BOM 付き。ここでコンソール出力を UTF-8 に合わせます。
cd /d "%~dp0"
set "SCR=%~dp0Start-VoiceServer-Background.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "chcp 65001 | Out-Null; [Console]::OutputEncoding = [System.Text.Encoding]::GetEncoding(65001); & '%SCR%'"
pause
