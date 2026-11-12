<p align="center">
  <img src="aerotagger/resources/lockup@2x.png" alt="AeroTagger" height="72">
</p>

**AeroTagger** ist ein Desktop-Programm zum Sichten und Beschriften von Fotos –
zugeschnitten auf Flugzeugfotografie. Ordner durchsuchen, JPEG- und RAW-Dateien
ansehen, bewerten und IPTC-/XMP-/EXIF-Metadaten schreiben, ähnlich wie in
Photo Mechanic.

> Version 0.2.12 – in Entwicklung. Es fehlt noch einiges bis zur Version 1.0.

## Funktionen

- **Ordnerbaum, Vorschau, Filmstreifen und Kontaktbogen** für JPEG und gängige RAW-Formate,
  Lupe mit der rechten Maustaste
- **AircraftTag-Modus**: Registrierung eingeben, Flugzeugdaten aus eigener CSV oder
  online (adsbdb.com, Ersatz hexdb.io) holen, mit lokalem Cache
- **Metadaten schreiben** mit Variablen (`{ac:Typ}`, `{airport}`, `{aufnahme:%Y}` …),
  Kürzel-Ersetzung (`=fra=`) und Daten aus CSV
- **Metadaten-Templates** als JSON exportieren und importieren
- **Sternebewertung** 0–5 per Tastatur, Filter über dem Filmstreifen wie in Lightroom
- **Umbenennen** nach Vorlage beim Schreiben, XMP-Sidecars für RAW-Dateien
- Getaggte Fotos werden erkannt und zeigen Registrierung, Operator und Typ unter dem Bild

Die ausführliche Anleitung steht in [LIESMICH.md](LIESMICH.md).

## Starten

| System | Vorgehen |
|---|---|
| Windows | Python 3.9+ von [python.org](https://www.python.org/downloads/) installieren, dann `start_windows.bat` doppelklicken |
| macOS / Linux | `start_mac_linux.command` doppelklicken |

Der erste Start richtet eine eigene Python-Umgebung ein (Internet nötig).
Eine eigenständige Windows-EXE erzeugt `build_windows.bat`
(Ergebnis: `dist\AeroTagger-<Version>-windows.zip`).

## Voraussetzungen

- Python 3.9 oder neuer, [PySide6](https://pypi.org/project/PySide6/)
- [ExifTool](https://exiftool.org) von Phil Harvey – für macOS/Linux unter
  `vendor/exiftool` enthalten (eigene Lizenz, siehe dort), unter Windows lädt
  AeroTagger es beim ersten Start bzw. beim Build

## Rechte

© 2026 Alexander Pauli. Alle Rechte vorbehalten.

Der Quellcode von AeroTagger steht unter keiner Open-Source-Lizenz. Ansehen ist
erlaubt, Verwenden, Verändern oder Weitergeben nur mit Zustimmung des Autors.
Mitgelieferte Drittsoftware (ExifTool) steht unter ihrer eigenen Lizenz.
