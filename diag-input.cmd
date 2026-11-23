@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONPATH=%~dp0;%~dp0vendor"
"%~dp0.venv\Scripts\python.exe" "%~dp0diag_input.py"
echo.
pause
