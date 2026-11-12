@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python wurde nicht gefunden. Bitte von https://www.python.org/downloads/ installieren
  echo ^(beim Setup "Add python.exe to PATH" anhaken^) und diese Datei erneut starten.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\pythonw.exe" (
  echo Erster Start: Umgebung wird eingerichtet, bitte warten ...
  py -3 -m venv .venv || (pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)
start "" ".venv\Scripts\pythonw.exe" AeroTagger.pyw
