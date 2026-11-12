@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ===========================================================================
rem  AeroTagger - Windows-EXE erzeugen
rem
rem  Ergebnis:  dist\AeroTagger\AeroTagger.exe  (mit ExifTool daneben)
rem             dist\AeroTagger-<Version>-windows.zip  (zum Weitergeben)
rem
rem  Voraussetzung: Python 3.9 oder neuer von python.org
rem  ExifTool wird gesucht in:  diesem Ordner, Unterordner "exiftool",
rem  %USERPROFILE%\.aerotagger\exiftool  - sonst von exiftool.org geladen.
rem ===========================================================================
cd /d "%~dp0"
title AeroTagger - EXE erstellen

where py >nul 2>nul
if errorlevel 1 (
  echo Python wurde nicht gefunden. Bitte von https://www.python.org/downloads/ installieren
  echo und beim Setup "Add python.exe to PATH" anhaken.
  goto :fail
)

rem --- 1. Build-Umgebung -----------------------------------------------------
if not exist ".venv-build\Scripts\python.exe" (
  echo [1/5] Richte Build-Umgebung ein ...
  py -3 -m venv .venv-build || goto :fail
)
set "PY=.venv-build\Scripts\python.exe"
echo [1/5] Installiere bzw. aktualisiere PySide6 und PyInstaller ...
"%PY%" -m pip install --upgrade --quiet pip || goto :fail
"%PY%" -m pip install --upgrade --quiet -r requirements.txt pyinstaller || goto :fail

for /f "usebackq delims=" %%v in (`%PY% -c "from aerotagger.core import APP_VERSION; print(APP_VERSION)"`) do set "VERSION=%%v"
if not defined VERSION goto :fail
echo       AeroTagger Version !VERSION!

rem --- 2. EXE bauen ------------------------------------------------------------
echo [2/5] Baue AeroTagger.exe - das dauert ein bis zwei Minuten ...
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN ^
  --windowed --name AeroTagger ^
  --icon "aerotagger\resources\icon.ico" ^
  --add-data "aerotagger\resources;aerotagger\resources" ^
  AeroTagger.pyw || goto :fail
set "OUT=dist\AeroTagger"
if not exist "%OUT%\AeroTagger.exe" goto :fail

rem --- 3. ExifTool neben die EXE ---------------------------------------------
echo [3/5] Lege ExifTool dazu ...
set "ETDIR="
for %%d in ("%CD%" "%CD%\exiftool" "%USERPROFILE%\.aerotagger\exiftool") do (
  if not defined ETDIR if exist "%%~d\exiftool_files\" (
    if exist "%%~d\exiftool.exe" (set "ETDIR=%%~d" & set "ETEXE=exiftool.exe")
    if not defined ETDIR if exist "%%~d\exiftool(-k).exe" (set "ETDIR=%%~d" & set "ETEXE=exiftool(-k).exe")
  )
)
if not defined ETDIR (
  echo       ExifTool nicht gefunden - lade es von exiftool.org ...
  if exist "build\exiftool-download" rmdir /s /q "build\exiftool-download"
  mkdir "build\exiftool-download"
  set "ETVER="
  for /f "usebackq delims=" %%v in (`curl -s -L https://exiftool.org/ver.txt`) do set "ETVER=%%v"
  if not defined ETVER (
    echo       Download nicht moeglich. Bitte ExifTool von https://exiftool.org laden,
    echo       entpacken und exiftool^(-k^).exe samt Ordner exiftool_files in diesen Ordner legen.
    goto :fail
  )
  set "ETZIP=build\exiftool-download\exiftool.zip"
  set "ETOK="
  rem exiftool.org liefert die Zips ueber SourceForge aus - beide Quellen versuchen
  for %%u in ("https://sourceforge.net/projects/exiftool/files/exiftool-!ETVER!_64.zip/download" "https://exiftool.org/exiftool-!ETVER!_64.zip") do (
    if not defined ETOK (
      echo       Version !ETVER! von %%~u
      if exist "!ETZIP!" del /q "!ETZIP!"
      curl -s -L -f -A "AeroTagger-Build" -o "!ETZIP!" "%%~u"
      if exist "!ETZIP!" tar -tf "!ETZIP!" >nul 2>nul && set "ETOK=1"
    )
  )
  if not defined ETOK (
    echo       Download nicht moeglich. Bitte ExifTool von https://exiftool.org laden,
    echo       entpacken und exiftool^(-k^).exe samt Ordner exiftool_files in diesen Ordner legen.
    goto :fail
  )
  tar -xf "!ETZIP!" -C "build\exiftool-download" || goto :fail
  for /d %%d in ("build\exiftool-download\exiftool-*") do set "ETDIR=%%~fd"
  if not defined ETDIR goto :fail
  set "ETEXE="
  for %%f in ("!ETDIR!\exiftool*.exe") do if not defined ETEXE set "ETEXE=%%~nxf"
)
echo       aus !ETDIR!
copy /y "!ETDIR!\!ETEXE!" "%OUT%\exiftool.exe" >nul || goto :fail
xcopy "!ETDIR!\exiftool_files" "%OUT%\exiftool_files\" /e /i /q /y >nul || goto :fail
"%OUT%\exiftool.exe" -ver >nul 2>nul || (
  echo       ExifTool laesst sich nicht starten.
  goto :fail
)

rem --- 4. Beispiele und Anleitung ---------------------------------------------
echo [4/5] Kopiere Beispiele und Anleitung ...
xcopy "beispiele" "%OUT%\beispiele\" /e /i /q /y >nul
copy /y "LIESMICH.md" "%OUT%\LIESMICH.md" >nul

rem --- 5. Zip zum Weitergeben ----------------------------------------------------
set "ZIP=dist\AeroTagger-!VERSION!-windows.zip"
echo [5/5] Packe !ZIP! ...
if exist "!ZIP!" del /q "!ZIP!"
powershell -NoProfile -Command "Compress-Archive -Path '%OUT%' -DestinationPath '!ZIP!'" || goto :fail

echo.
echo Fertig.
echo   Programm:  %CD%\%OUT%\AeroTagger.exe
echo   Zip:       %CD%\!ZIP!
echo.
echo Den Ordner dist\AeroTagger kannst du beliebig verschieben - die EXE braucht
echo den Ordner _internal und ExifTool daneben. Python ist auf dem Zielrechner nicht noetig.
echo.
pause
exit /b 0

:fail
echo.
echo *** Abbruch - siehe Meldungen oben. ***
pause
exit /b 1
