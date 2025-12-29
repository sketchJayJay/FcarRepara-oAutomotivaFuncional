@echo off
setlocal
cd /d "%~dp0"
python importar_estoque_csv.py
echo.
pause
