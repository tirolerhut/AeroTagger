# AeroTagger auf GitHub

## Schnellweg: `publish_github.bat`

Doppelklick auf `publish_github.bat` im Projektordner. Die Datei führt durch alles:

1. **Git und GitHub CLI** – fehlen sie, bietet sie die Installation per `winget`
   an. Danach das Fenster schließen und die Datei noch einmal starten.
2. **Anmeldung** – beim ersten Mal öffnet sich der Browser. Den im Fenster
   angezeigten Code eingeben und „GitHub CLI“ zulassen. Ein GitHub-Konto
   brauchst du vorher (kostenlos auf [github.com](https://github.com/signup)).
3. **Lokales Repository** – Git wird im Projektordner eingerichtet. Als Autor
   trägt die Datei deinen GitHub-Namen und die anonyme Adresse
   `…@users.noreply.github.com` ein, damit deine echte E-Mail nicht in der
   Versionsgeschichte steht.
4. **Commit** – alle Änderungen werden gesammelt. Du kannst eine kurze
   Beschreibung eingeben oder mit Enter „AeroTagger 0.2.12“ übernehmen.
5. **Hochladen** – beim ersten Mal fragt die Datei nach dem Namen
   (Vorschlag: `AeroTagger`) und der Sichtbarkeit, legt das Repository an und
   lädt alles hoch. Danach genügt ein erneuter Doppelklick für jede neue Version.

Liegt `dist\AeroTagger-<Version>-windows.zip` von `build_windows.bat` bereit,
bietet die Datei zum Schluss an, ein **Release** daraus zu machen. Es erscheint
auf GitHub rechts unter „Releases“ als Download – für alle, die nur die fertige
EXE wollen.

## Was hochgeladen wird – und was nicht

Hochgeladen wird der Quellcode, die Anleitung, die Beispiele, das Logo und
ExifTool für macOS/Linux (`vendor/exiftool`).

Nicht hochgeladen werden (siehe `.gitignore`): die Python-Umgebungen `.venv`
und `.venv-build`, die Build-Ordner `build` und `dist`, ein lokal abgelegtes
Windows-ExifTool sowie deine Einstellungen und der Flugzeug-Cache – die liegen
ohnehin außerhalb des Projekts in `%USERPROFILE%\.aerotagger`.

`.gitattributes` sorgt dafür, dass die `.bat`-Dateien Windows-Zeilenenden und
die Skripte für macOS/Linux Unix-Zeilenenden behalten, egal wo eingecheckt wird.

## Privat oder öffentlich?

AeroTagger hat **keine Lizenz** – alle Rechte liegen bei dir. Das heißt:

- **Privat** (empfohlen): nur du siehst das Repository. Andere lädst du unter
  *Settings → Collaborators* gezielt ein.
- **Öffentlich**: jeder kann den Code ansehen und das Repository „forken“,
  darf ihn aber rechtlich nicht verwenden, verändern oder weitergeben.

Die Sichtbarkeit lässt sich jederzeit unter *Settings → General → Danger Zone →
Change visibility* ändern. Soll AeroTagger später Open Source werden, genügt
eine Datei `LICENSE` (z. B. MIT) im Projektordner.

## Neue Version veröffentlichen

1. Versionsnummer in `aerotagger/core.py` (`APP_VERSION`) und in der ersten
   Zeile von `LIESMICH.md` erhöhen, z. B. auf 0.2.13.
2. Optional `build_windows.bat` starten, damit die neue Windows-Zip entsteht.
3. `publish_github.bat` starten, Beschreibung eingeben, beim Release mit J bestätigen.

## Auf einem anderen Rechner weiterarbeiten

```
gh repo clone <dein-name>/AeroTagger
```

oder auf GitHub *Code → Download ZIP*. Danach wie gewohnt `start_windows.bat`.
Änderungen vom anderen Rechner holst du mit `git pull` im Projektordner.

## Von Hand, ohne Batchdatei

```
git init -b main
git add -A
git update-index --chmod=+x start_mac_linux.command vendor/exiftool/exiftool
git commit -m "AeroTagger 0.2.12"
gh repo create AeroTagger --private --source . --remote origin --push
```

Ohne GitHub CLI: auf github.com über *New repository* ein leeres Repository
anlegen (ohne README und ohne Lizenz) und statt der letzten Zeile

```
git remote add origin https://github.com/<dein-name>/AeroTagger.git
git push -u origin main
```

Release von Hand: *Releases → Draft a new release*, Tag `v0.2.12`, die Zip aus
`dist` hineinziehen, *Publish release*.
