@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
if exist "python\python.exe" set "PYTHON_EXE=%CD%\python\python.exe"
if not defined PYTHON_EXE (
  where py >nul 2>&1 && set "PYTHON_EXE=py -3"
)
if not defined PYTHON_EXE (
  where python >nul 2>&1 && set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
  echo FEHLER: Python 3 wurde nicht gefunden.
  echo Dieses Developer-Paket benoetigt Python 3 und die Pakete aus requirements.txt.
  echo Es werden keine Komponenten automatisch heruntergeladen oder installiert.
  pause
  exit /b 1
)

echo Starte Offline360 Studio...
set "OFFLINE360_STUDIO_RUNTIME_ROOT=%CD%"
set "APP_ENTRY=app.py"
if exist "app\app.py" set "APP_ENTRY=app\app.py"
%PYTHON_EXE% "%APP_ENTRY%"
if errorlevel 1 (
  echo.
  echo FEHLER: Offline360 Studio wurde mit einem Fehler beendet.
  echo Details stehen, soweit verfuegbar, in logs\offline360-studio.log.
  pause
  exit /b 1
)
endlocal

