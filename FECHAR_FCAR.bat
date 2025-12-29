@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if not exist "fcar.pid" (
  echo Nao achei o arquivo fcar.pid. Se o FCAR estiver aberto, feche e abra de novo pelo ABRIR_FCAR.vbs.
  pause
  exit /b 0
)

set /p PID=<fcar.pid
if "%PID%"=="" (
  echo PID vazio. Apague fcar.pid e abra o FCAR de novo.
  pause
  exit /b 0
)

echo Fechando FCAR (PID %PID%)...
taskkill /PID %PID% /T /F >nul 2>&1

del /f /q fcar.pid >nul 2>&1
echo OK! FCAR fechado.
pause
