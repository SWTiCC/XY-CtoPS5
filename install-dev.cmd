@echo off
rem XY-CtoPS5 - install dev/source build (venv + deps + desktop shortcut)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-dev.ps1"
echo.
pause
