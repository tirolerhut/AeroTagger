# AeroTagger auf GitHub

## Schnellweg: `publish_github.bat`

Doppelklick auf `publish_github.bat` im Projektordner. Die Datei führt durch alles:

1. **Git und GitHub CLI** – fehlen sie, bietet sie die Installation per `winget`
   an. Danach das Fenster schließen und die Datei noch einmal starten.
2. **Anmeldung** – beim ersten Mal öffnet sich der Browser. Den im Fenster
   angezeigten Code eingeben und „GitHub CLI“ zulassen. Ein GitHub-Konto
   brauchst du vorher (kostenlos auf [github.com](https://github.com/signup)).
3. **Ziel-Repository** – ist der Ordner noch mit keinem Repository verbunden,
   fragt die Datei:
   - **N – neues Repository**: Name (Vorschlag `AeroTagger`) und Sichtbarkeit
     wählen (Vorschlag: öffentlich); es wird angelegt.
   - **B – bestehendes Repository aktualisieren**: für eine neue Version, etwa
     wenn du ein neues AeroTagger-Paket in einen frischen Ordner entpackt hast.
     Die Datei zeigt deine Repositorys, holt die bisherige Versionsgeschichte
     von GitHub und nimmt die Dateien im Ordner als neue Version – geänderte,
     neue **und gelöschte** Dateien werden erfasst.

   Ist der Ordner schon verbunden, geht es ohne Frage weiter. Gibt es auf GitHub
   Änderungen, die hier fehlen, bietet die Datei an, sie zuerst zu übernehmen.
4. **Version prüfen** – ist die Version (z. B. `v0.2.16`) auf GitHub schon
   veröffentlicht, warnt die Datei: Für eine neue Version zuerst `APP_VERSION` in
   `aerotagger/core.py` erhöhen, sonst bieten die Apps das Update nicht an.
5. **Commit** – kurze Beschreibung eingeben oder mit Enter „AeroTagger 0.2.16“
   übernehmen. Als Autor stehen dein GitHub-Name und die anonyme Adresse
   `…@users.noreply.github.com` drin, nicht deine echte E-Mail.
6. **Hochladen** – samt Versions-Tag `v0.2.16`.

Zum Schluss bietet die Datei ein **Release** an. Das brauchst du, damit
AeroTagger über *Hilfe → Nach Updates suchen* die neue Version findet. Liegt
`dist\AeroTagger-<Version>-windows.zip` noch nicht vor, kann die Datei vorher
`build_windows.bat` ausführen – nur mit dieser Zip können sich auch
EXE-Installationen selbst aktualisieren. Als Beschreibung („Was ist neu?“)
zeigt die App später genau diesen Text an; mit Enter wird die Liste der
Commits verwendet.

Außerdem trägt die Datei den Namen des Repositorys in
`aerotagger/resources/github_repo.txt` ein – daher weiß jede AeroTagger-Kopie,
wo sie nach Updates suchen soll.

## Was hochgeladen wird – und was nicht

Hochgeladen wird der Quellcode, die Anleitung, die Beispiele, das Logo und
ExifTool für macOS/Linux (`vendor/exiftool`).

Nicht hochgeladen werden (siehe `.gitignore`): die Python-Umgebungen `.venv`
und `.venv-build`, die Build-Ordner `build` und `dist`, ein lokal abgelegtes
Windows-ExifTool sowie deine Einstellungen und der Flugzeug-Cache – die liegen
ohnehin außerhalb des Projekts in `%USERPROFILE%\.aerotagger`.

`.gitattributes` sorgt dafür, dass die `.bat`-Dateien Windows-Zeilenenden und
die Skripte für macOS/Linux Unix-Zeilenenden behalten, egal wo eingecheckt wird.

## Öffentlich oder privat?

Das AeroTagger-Repository ist **öffentlich**. Damit

- kann jeder Code und Releases sehen und die Windows-Zip herunterladen,
- funktioniert *Hilfe → Nach Updates suchen* in jeder AeroTagger-Kopie ohne
  GitHub-Token.

AeroTagger hat weiterhin **keine Lizenz** – alle Rechte liegen bei dir. Den Code
ansehen und forken darf jeder (das erlauben die GitHub-Nutzungsbedingungen),
verwenden, verändern oder weitergeben aber nur mit deiner Zustimmung. Soll
AeroTagger Open Source werden, genügt eine Datei `LICENSE` (z. B. MIT) im
Projektordner.

Die Sichtbarkeit lässt sich jederzeit unter *Settings → General → Danger Zone →
Change visibility* ändern. Bei einem privaten Repository braucht die
Update-Funktion einen Token (siehe `LIESMICH.md`, Abschnitt „Updates“);
`publish_github.bat` zeigt beim Verbinden an, welche Sichtbarkeit gerade gilt.

## Neue Version veröffentlichen

1. Versionsnummer in `aerotagger/core.py` (`APP_VERSION`) und in der ersten
   Zeile von `LIESMICH.md` erhöhen, z. B. auf 0.2.17. Bei Paketen von Claude
   ist das schon erledigt.
2. Neues Paket entpacken – in den bisherigen Ordner (Dateien ersetzen) oder in
   einen neuen; im neuen Ordner bei der Frage **B** wählen.
3. `publish_github.bat` starten, Beschreibung eingeben, Release mit J bestätigen
   und auf Wunsch die EXE bauen lassen.

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
