@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ===========================================================================
rem  AeroTagger - Projekt auf GitHub hochladen bzw. aktualisieren
rem
rem  Beim ersten Mal:  installiert bei Bedarf Git und GitHub CLI, meldet dich
rem                    bei GitHub an, legt das Repository an und laedt alles hoch.
rem  Danach:           einfach erneut starten - neue Aenderungen werden
rem                    committet und hochgeladen.
rem  Optional:         legt ein Release mit der Windows-Zip aus build_windows.bat an.
rem ===========================================================================
cd /d "%~dp0"
title AeroTagger - GitHub

rem --- Version aus aerotagger\core.py lesen (ohne Python) -------------------
set "VERSION="
for /f "tokens=2 delims==" %%v in ('findstr /b /c:"APP_VERSION =" aerotagger\core.py') do set "VERSION=%%v"
if defined VERSION for %%q in (!VERSION!) do set "VERSION=%%~q"
if not defined VERSION (
  echo Version in aerotagger\core.py nicht gefunden.
  goto :fail
)
echo AeroTagger Version !VERSION!
echo.

rem --- 1. Git und GitHub CLI ------------------------------------------------
echo [1/5] Pruefe Git und GitHub CLI ...
set "NEEDRESTART="
where git >nul 2>nul
if errorlevel 1 call :install Git.Git "Git"
where gh >nul 2>nul
if errorlevel 1 call :install GitHub.cli "GitHub CLI"
if defined FAILED goto :fail
if defined NEEDRESTART (
  echo.
  echo Installation abgeschlossen. Bitte dieses Fenster schliessen und
  echo publish_github.bat noch einmal starten, damit Windows die neuen Programme findet.
  goto :end
)

rem --- 2. Bei GitHub anmelden -----------------------------------------------
echo [2/5] Pruefe GitHub-Anmeldung ...
gh auth status >nul 2>nul
if errorlevel 1 (
  echo       Du bist noch nicht angemeldet. Gleich oeffnet sich der Browser:
  echo       den angezeigten Code dort eingeben und GitHub CLI zulassen.
  echo.
  gh auth login --hostname github.com --git-protocol https --web || goto :fail
)
gh auth setup-git >nul 2>nul
set "GHLOGIN="
for /f "usebackq delims=" %%a in (`gh api user --jq .login`) do set "GHLOGIN=%%a"
if not defined GHLOGIN goto :fail
echo       Angemeldet als !GHLOGIN!

rem --- 3. Lokales Repository ------------------------------------------------
echo [3/5] Bereite lokales Repository vor ...
if not exist ".git\" (
  git init -q || goto :fail
  git symbolic-ref HEAD refs/heads/main
)
rem Name und E-Mail fuer Commits - die E-Mail ist die anonyme GitHub-Adresse,
rem damit deine echte Adresse nicht oeffentlich in der Historie steht
git config user.name >nul 2>nul
if errorlevel 1 (
  set "GHNAME="
  for /f "usebackq delims=" %%a in (`gh api user --jq ".name // .login"`) do set "GHNAME=%%a"
  if not defined GHNAME set "GHNAME=!GHLOGIN!"
  git config user.name "!GHNAME!"
)
git config user.email >nul 2>nul
if errorlevel 1 (
  set "GHID="
  for /f "usebackq delims=" %%a in (`gh api user --jq .id`) do set "GHID=%%a"
  git config user.email "!GHID!+!GHLOGIN!@users.noreply.github.com"
)

rem --- 4. Aenderungen committen ---------------------------------------------
echo [4/5] Sammle Aenderungen ...
git add -A || goto :fail
rem Startskripte fuer macOS/Linux als ausfuehrbar markieren
git update-index --chmod=+x start_mac_linux.command >nul 2>nul
if exist "vendor\exiftool\exiftool" git update-index --chmod=+x vendor/exiftool/exiftool >nul 2>nul
git diff --cached --quiet
if errorlevel 1 (
  git status --short
  echo.
  set "MSG="
  set /p "MSG=Beschreibung der Aenderung [Enter = AeroTagger !VERSION!]: "
  if not defined MSG set "MSG=AeroTagger !VERSION!"
  git commit -q -m "!MSG!" || goto :fail
  echo       Commit angelegt.
) else (
  echo       Keine neuen Aenderungen.
)

rem --- 5. Hochladen -----------------------------------------------------------
echo [5/5] Lade zu GitHub hoch ...
git remote get-url origin >nul 2>nul
if not errorlevel 1 goto :push

echo.
echo       Das Repository existiert auf GitHub noch nicht.
set "REPO="
set /p "REPO=      Name des Repositorys [Enter = AeroTagger]: "
if not defined REPO set "REPO=AeroTagger"
echo.
echo       Sichtbarkeit:
echo         P = privat     - nur du (und wen du einlaedst) siehst den Code. Empfohlen,
echo                          da AeroTagger keine Open-Source-Lizenz hat.
echo         O = oeffentlich - jeder kann den Code ansehen, aber ohne Lizenz nicht nutzen.
choice /c PO /n /m "      Privat oder oeffentlich? [P/O] "
if errorlevel 2 (set "VIS=--public") else (set "VIS=--private")
gh repo create "!REPO!" !VIS! --source . --remote origin --push ^
  --description "Fotos von Flugzeugen sichten, bewerten und mit Metadaten beschriften" || goto :fail
goto :pushed

:push
for /f "usebackq delims=" %%b in (`git branch --show-current`) do set "BRANCH=%%b"
git push -u origin !BRANCH! || goto :fail

:pushed
set "URL="
for /f "usebackq delims=" %%u in (`gh repo view --json url --jq .url`) do set "URL=%%u"
echo       Online: !URL!

rem --- Optional: Release mit Windows-Zip -----------------------------------
set "ZIP=dist\AeroTagger-!VERSION!-windows.zip"
echo.
if not exist "!ZIP!" (
  echo Tipp: Mit build_windows.bat entsteht !ZIP! - danach kann diese
  echo Datei sie als Release v!VERSION! auf GitHub zum Download anbieten.
  goto :done
)
choice /c JN /n /m "Release v!VERSION! mit !ZIP! anlegen bzw. aktualisieren? [J/N] "
if errorlevel 2 goto :done
gh release view "v!VERSION!" >nul 2>nul
if errorlevel 1 (
  gh release create "v!VERSION!" "!ZIP!" --title "AeroTagger !VERSION!" ^
    --notes "Windows: Zip entpacken und AeroTagger\AeroTagger.exe starten. Python ist nicht noetig." || goto :fail
) else (
  gh release upload "v!VERSION!" "!ZIP!" --clobber || goto :fail
)
echo       Release v!VERSION! ist online.

:done
echo.
echo Fertig.
goto :end

rem --- Unterprogramm: Programm per winget installieren ----------------------
:install
echo       %~2 fehlt.
where winget >nul 2>nul
if errorlevel 1 (
  echo       Bitte %~2 von Hand installieren:
  if "%~1"=="Git.Git" (echo       https://git-scm.com/download/win) else (echo       https://cli.github.com)
  set "FAILED=1"
  exit /b
)
choice /c JN /n /m "      %~2 jetzt mit winget installieren? [J/N] "
if errorlevel 2 (
  set "FAILED=1"
  exit /b
)
winget install --id %~1 -e --source winget --accept-package-agreements --accept-source-agreements
if errorlevel 1 (
  set "FAILED=1"
  exit /b
)
set "NEEDRESTART=1"
exit /b

:fail
echo.
echo *** Abbruch - siehe Meldungen oben. ***
:end
echo.
pause
exit /b
