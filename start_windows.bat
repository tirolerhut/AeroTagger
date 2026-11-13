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

rem Beim ersten Start einmal nach einer Desktop-Verknuepfung fragen
if not exist ".venv\verknuepfung-gefragt" (
  echo.
  choice /c JN /n /m "Verknuepfung zu AeroTagger auf dem Desktop anlegen? [J/N] "
  if not errorlevel 2 call :shortcut
  type nul > ".venv\verknuepfung-gefragt"
)

start "" ".venv\Scripts\pythonw.exe" AeroTagger.pyw
exit /b 0

rem --- Verknuepfung: startet AeroTagger direkt, ohne Konsolenfenster -----------
:shortcut
set "AT_DIR=%CD%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = [Environment]::GetFolderPath('Desktop');" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'AeroTagger.lnk'));" ^
  "$s.TargetPath = Join-Path $env:AT_DIR '.venv\Scripts\pythonw.exe';" ^
  "$q = [char]34; $s.Arguments = $q + (Join-Path $env:AT_DIR 'AeroTagger.pyw') + $q;" ^
  "$s.WorkingDirectory = $env:AT_DIR;" ^
  "$s.IconLocation = (Join-Path $env:AT_DIR 'aerotagger\resources\icon.ico') + ',0';" ^
  "$s.Description = 'AeroTagger';" ^
  "$s.Save()"
if errorlevel 1 (
  echo Die Verknuepfung konnte nicht angelegt werden.
) else (
  echo Verknuepfung "AeroTagger" liegt auf dem Desktop.
)
exit /b 0
