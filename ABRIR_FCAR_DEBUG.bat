@echo off
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
  venv\Scripts\python.exe start_fcar.py
) else (
  python start_fcar.py
)
pause
