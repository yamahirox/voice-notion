@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 家のパソコンを起動したまま、外出先のスマホから使います。
echo Notion のキーはパソコン側にだけ置きます。
echo この黒い窓は閉じないでください。
echo.

set VOICE_REMOTE=1

if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" app.py
) else (
  python app.py
)

if errorlevel 1 (
  echo.
  echo 起動に失敗しました。インターネットにつながっているか確認してください。
  pause
)
