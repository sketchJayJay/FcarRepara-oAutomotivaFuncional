@echo off
setlocal
cd /d "%~dp0"

if not exist "estoque.csv" (
  if exist "estoque_modelo.csv" (
    copy /Y "estoque_modelo.csv" "estoque.csv" >nul
  )
)

if not exist "estoque.csv" (
  echo Nao foi possivel criar o arquivo estoque.csv (modelo nao encontrado).
  pause
  exit /b 1
)

echo ✅ Abri o estoque.csv para voce preencher e salvar.
start "" "estoque.csv"
echo.
echo Depois de salvar, rode: IMPORTAR_ESTOQUE.bat
pause
