@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "PYTHONPATH=%ROOT%;%ROOT%vendor"
set "PYTHONIOENCODING=utf-8"
"%ROOT%.venv\Scripts\python.exe" -m ps5kbm %*
endlocal
