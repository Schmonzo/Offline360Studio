@echo off
setlocal
cd /d "%~dp0"
if not exist "server.exe" (
  echo Fehler: server.exe fehlt. Bitte die Tour erneut exportieren.
  pause
  exit /b 1
)
"%~dp0server.exe"
if errorlevel 1 (
  echo.
  echo Der Tour-Server wurde mit einem Fehler beendet.
  pause
)
endlocal
