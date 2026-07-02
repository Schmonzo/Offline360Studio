@echo off
setlocal
cd /d "%~dp0"
echo =====================================
echo   Panorama Studio v0.1
echo =====================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo Erzeuge lokale Python-Umgebung...
  python -m venv .venv
)
echo Installiere/aktualisiere Abhaengigkeiten...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo FEHLER: Abhaengigkeiten konnten nicht installiert werden.
  echo Bitte pruefen, ob Python installiert und im PATH verfuegbar ist.
  pause
  exit /b 1
)
echo.
echo Starte Panorama Studio...
".venv\Scripts\python.exe" app.py
pause
