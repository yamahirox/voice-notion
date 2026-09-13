@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Register-VoiceServerTask.ps1"
if errorlevel 1 pause & exit /b 1
echo.
echo 今すぐ起動しますか？ (Y/N)
set /p ANS=
if /i "%ANS%"=="Y" powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-VoiceServerTask-Now.ps1"
pause
