@echo off
setlocal EnableExtensions EnableDelayedExpansion
rem ===========================================================================
rem  AeroTagger - Projekt auf GitHub hochladen oder neue Version veroeffentlichen
rem
rem  Neues Repository:     installiert bei Bedarf Git und GitHub CLI, meldet dich
rem                        bei GitHub an, legt das Repository an, laedt alles hoch.
rem  Bestehendes Repository (neue Version):
rem                        verbindet den Ordner mit dem Repository auf GitHub -
rem                        auch wenn du ein neues Paket in einen frischen Ordner
rem                        entpackt hast - und laedt nur die Aenderungen hoch.
rem  Danach:               Versions-Tag und Release (noetig fuer die Update-
rem                        Funktion der App), wahlweise mit der Windows-Zip.
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
set "TAG=v!VERSION!"
echo AeroTagger Version !VERSION!
echo.

rem --- 1. Git und GitHub CLI ------------------------------------------------
echo [1/6] Pruefe Git und GitHub CLI ...
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
echo [2/6] Pruefe GitHub-Anmeldung ...
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

rem --- 3. Ziel-Repository -------------------------------------------------------
echo [3/6] Ziel-Repository ...
if exist ".git\" (
  git remote get-url origin >nul 2>nul
  if not errorlevel 1 goto :have_origin
)
echo.
echo       Dieser Ordner ist noch mit keinem Repository auf GitHub verbunden.
echo         N = neues Repository anlegen - erstes Hochladen
echo         B = bestehendes Repository aktualisieren - neue Version, z. B. nachdem
echo             du ein neues AeroTagger-Paket in einen frischen Ordner entpackt hast
choice /c NB /n /m "      Neu oder bestehend? [N/B] "
if errorlevel 2 goto :ask_existing

rem ---- 3a. neues Repository
set "MODE=new"
set "REPO="
set /p "REPO=      Name des neuen Repositorys [Enter = AeroTagger]: "
if not defined REPO set "REPO=AeroTagger"
call :fullname
gh repo view "!REPOFULL!" >nul 2>nul
if not errorlevel 1 (
  echo       !REPOFULL! gibt es schon - es wird als bestehendes Repository aktualisiert.
  goto :connect
)
echo.
echo       Sichtbarkeit:
echo         O = oeffentlich - jeder kann Code und Releases sehen; die Update-Funktion
echo                          der App braucht keinen Token. Empfohlen.
echo         P = privat     - nur du und eingeladene Personen; die App braucht fuer
echo                          Updates dann einen GitHub-Token in den Einstellungen.
choice /c OP /n /m "      Oeffentlich oder privat? [O/P] "
if errorlevel 2 (set "VIS=--private") else (set "VIS=--public")
if not exist ".git\" (
  git init -q || goto :fail
  git symbolic-ref HEAD refs/heads/main
)
goto :prepare

rem ---- 3b. bestehendes Repository verbinden
:ask_existing
echo.
echo       Deine Repositorys:
gh repo list !GHLOGIN! --limit 20
echo.
set "REPO="
set /p "REPO=      Welches Repository? [Enter = AeroTagger]: "
if not defined REPO set "REPO=AeroTagger"
call :fullname
gh repo view "!REPOFULL!" >nul 2>nul
if errorlevel 1 (
  echo       !REPOFULL! wurde auf GitHub nicht gefunden.
  goto :fail
)
:connect
set "MODE=update"
if not exist ".git\" (
  git init -q || goto :fail
  git symbolic-ref HEAD refs/heads/main
)
git remote get-url origin >nul 2>nul
if errorlevel 1 (
  git remote add origin "https://github.com/!REPOFULL!.git"
) else (
  git remote set-url origin "https://github.com/!REPOFULL!.git"
)
echo       Hole den Stand von GitHub ...
git fetch -q origin || goto :fail
set "BR="
for /f "usebackq delims=" %%b in (`gh repo view "!REPOFULL!" --json defaultBranchRef --jq .defaultBranchRef.name`) do set "BR=%%b"
if defined BR (
  git rev-parse -q --verify "refs/remotes/origin/!BR!" >nul 2>nul
  if not errorlevel 1 (
    rem Historie von GitHub uebernehmen, die Dateien in diesem Ordner bleiben
    rem unveraendert - sie bilden die neue Version
    git symbolic-ref HEAD "refs/heads/!BR!"
    git reset -q "origin/!BR!" || goto :fail
  )
)
call :visibility
goto :prepare

rem ---- 3c. Ordner ist schon verbunden
:have_origin
set "MODE=update"
set "REPOFULL="
for /f "usebackq delims=" %%a in (`gh repo view --json nameWithOwner --jq .nameWithOwner`) do set "REPOFULL=%%a"
if not defined REPOFULL (
  echo       Das Repository hinter "origin" ist auf GitHub nicht erreichbar.
  goto :fail
)
echo       Verbunden mit !REPOFULL!
call :visibility
git fetch -q origin || goto :fail
set "BR="
for /f "usebackq delims=" %%b in (`git branch --show-current`) do set "BR=%%b"
set "BEHIND=0"
for /f %%c in ('git rev-list --count "HEAD..origin/!BR!" 2^>nul') do set "BEHIND=%%c"
if not "!BEHIND!"=="0" (
  echo       Auf GitHub gibt es !BEHIND! neuere Commits, die hier fehlen.
  choice /c JN /n /m "      Zuerst uebernehmen - git pull? [J/N] "
  if errorlevel 2 goto :fail
  git pull --no-rebase --no-edit origin "!BR!" || goto :fail
)

rem --- 4. Version pruefen ---------------------------------------------------
:prepare
echo [4/6] Pruefe Version !VERSION! ...
rem Repository-Name fuer die Update-Funktion der App hinterlegen
>"aerotagger\resources\github_repo.txt" echo !REPOFULL!
if "!MODE!"=="update" (
  set "TAGREMOTE="
  for /f "usebackq delims=" %%t in (`git ls-remote --tags origin "refs/tags/!TAG!"`) do set "TAGREMOTE=1"
  if defined TAGREMOTE (
    echo.
    echo       Version !VERSION! ist auf GitHub schon veroeffentlicht.
    echo       Fuer eine neue Version zuerst APP_VERSION in aerotagger\core.py erhoehen,
    echo       sonst bietet die Update-Funktion der App die Aenderungen nicht an.
    choice /c JN /n /m "      Trotzdem hochladen, ohne neues Release? [J/N] "
    if errorlevel 2 goto :fail
  )
)

rem --- 5. Aenderungen committen ---------------------------------------------
echo [5/6] Sammle Aenderungen ...
git config user.name >nul 2>nul
if errorlevel 1 (
  set "GHNAME="
  for /f "usebackq delims=" %%a in (`gh api user --jq ".name // .login"`) do set "GHNAME=%%a"
  if not defined GHNAME set "GHNAME=!GHLOGIN!"
  git config user.name "!GHNAME!"
)
rem anonyme GitHub-Adresse, damit die echte E-Mail nicht in der Historie steht
git config user.email >nul 2>nul
if errorlevel 1 (
  set "GHID="
  for /f "usebackq delims=" %%a in (`gh api user --jq .id`) do set "GHID=%%a"
  git config user.email "!GHID!+!GHLOGIN!@users.noreply.github.com"
)
git add -A || goto :fail
rem Startskripte fuer macOS/Linux als ausfuehrbar markieren
git update-index --chmod=+x start_mac_linux.command >nul 2>nul
if exist "vendor\exiftool\exiftool" git update-index --chmod=+x vendor/exiftool/exiftool >nul 2>nul
git diff --cached --quiet
if errorlevel 1 (
  git status --short
  echo.
  set "MSG="
  set /p "MSG=      Beschreibung der Aenderung [Enter = AeroTagger !VERSION!]: "
  if not defined MSG set "MSG=AeroTagger !VERSION!"
  git commit -q -m "!MSG!" || goto :fail
  echo       Commit angelegt.
) else (
  echo       Keine neuen Aenderungen.
)

rem --- 6. Hochladen -----------------------------------------------------------
echo [6/6] Lade zu GitHub hoch ...
if "!MODE!"=="new" (
  gh repo create "!REPOFULL!" !VIS! --source . --remote origin --push ^
    --description "Fotos von Flugzeugen sichten, bewerten und mit Metadaten beschriften" || goto :fail
) else (
  for /f "usebackq delims=" %%b in (`git branch --show-current`) do set "BR=%%b"
  git push -u origin "!BR!" || goto :fail
)
rem Versions-Tag (nur wenn es ihn noch nicht gibt)
git rev-parse -q --verify "refs/tags/!TAG!" >nul 2>nul
if errorlevel 1 git tag -a "!TAG!" -m "AeroTagger !VERSION!"
git push -q origin "!TAG!" >nul 2>nul
echo       Online: https://github.com/!REPOFULL!

rem --- Release ----------------------------------------------------------------
set "ZIP=dist\AeroTagger-!VERSION!-windows.zip"
echo.
gh release view "!TAG!" >nul 2>nul
if not errorlevel 1 (
  if exist "!ZIP!" (
    choice /c JN /n /m "Release !TAG! gibt es schon. Windows-Zip dort ersetzen? [J/N] "
    if not errorlevel 2 gh release upload "!TAG!" "!ZIP!" --clobber || goto :fail
  )
  goto :done
)
echo Ein Release !TAG! ist noetig, damit AeroTagger ueber Hilfe - Nach Updates suchen
echo die neue Version findet.
choice /c JN /n /m "Release !TAG! jetzt anlegen? [J/N] "
if errorlevel 2 goto :done
if not exist "!ZIP!" (
  echo.
  echo Ohne !ZIP! koennen sich nur Installationen mit Python aktualisieren,
  echo nicht die Windows-EXE.
  choice /c JN /n /m "Jetzt build_windows.bat ausfuehren und die EXE bauen? [J/N] "
  if not errorlevel 2 call build_windows.bat
  cd /d "%~dp0"
)
set "ASSET="
if exist "!ZIP!" set "ASSET="!ZIP!""
set "NOTES="
set /p "NOTES=Was ist neu? [Enter = Liste der Commits]: "
if defined NOTES (
  gh release create "!TAG!" !ASSET! --verify-tag --title "AeroTagger !VERSION!" --notes "!NOTES!" || goto :fail
) else (
  gh release create "!TAG!" !ASSET! --verify-tag --title "AeroTagger !VERSION!" --generate-notes || goto :fail
)
echo       Release !TAG! ist online.

:done
echo.
echo Fertig.
goto :end

rem --- Unterprogramm: Sichtbarkeit anzeigen -----------------------------------
:visibility
set "VISNOW="
for /f "usebackq delims=" %%v in (`gh repo view "!REPOFULL!" --json visibility --jq .visibility`) do set "VISNOW=%%v"
if /i "!VISNOW!"=="PUBLIC" (
  echo       Sichtbarkeit: oeffentlich - Updates in der App funktionieren ohne Token.
) else if defined VISNOW (
  echo       Sichtbarkeit: privat - die App braucht fuer Updates einen GitHub-Token
  echo       unter Einstellungen.
)
exit /b

rem --- Unterprogramm: owner/name aus der Eingabe ------------------------------
:fullname
set "REPO=!REPO:https://github.com/=!"
set "REPO=!REPO:.git=!"
if "!REPO!"=="!REPO:/=!" (set "REPOFULL=!GHLOGIN!/!REPO!") else (set "REPOFULL=!REPO!")
exit /b

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
