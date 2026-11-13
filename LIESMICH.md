# AeroTagger 0.2.16

Ordner durchsuchen, JPEG- und RAW-Dateien ansehen und IPTC-/XMP-/EXIF-Metadaten
schreiben – mit Variablen, Kürzel-Ersetzung und CSV-Daten.

## Start

| System | Vorgehen |
|---|---|
| Windows | Python 3.9+ von python.org installieren, dann `start_windows.bat` doppelklicken |
| macOS / Linux | `start_mac_linux.command` doppelklicken (macOS beim ersten Mal: Rechtsklick → Öffnen) |

Der erste Start richtet eine eigene Python-Umgebung im Ordner `.venv` ein (Internet nötig).

Beim ersten Start fragt `start_windows.bat`, ob eine **Verknüpfung auf dem
Desktop** angelegt werden soll. Sie trägt das AeroTagger-Logo und startet das
Programm direkt, ohne Konsolenfenster. Wer sie später doch möchte: die Datei
`.venv\verknuepfung-gefragt` löschen und `start_windows.bat` erneut starten.

**ExifTool** erledigt das eigentliche Lesen und Schreiben. Für macOS/Linux liegt es
im Ordner `vendor/exiftool` bei. Unter Windows bietet AeroTagger beim ersten Start an,
es von exiftool.org zu laden. Alternativ das Windows-Zip von exiftool.org
**vollständig** entpacken und beim Nachfragen `exiftool(-k).exe` auswählen – der
Ordner `exiftool_files` muss daneben liegen. AeroTagger legt daneben selbst eine
Kopie namens `exiftool.exe` an (ohne „-k“, das sonst nach jedem Aufruf auf die
Eingabetaste wartet). Klappt es nicht, nennt AeroTagger den Grund.

## Windows-EXE erstellen

`build_windows.bat` doppelklicken (auf einem Windows-Rechner mit Python). Die Datei

1. richtet eine eigene Build-Umgebung `.venv-build` mit PySide6 und PyInstaller ein,
2. baut `dist\AeroTagger\AeroTagger.exe` (mit Logo, ohne Konsolenfenster),
3. legt ExifTool daneben – aus diesem Ordner, dem Unterordner `exiftool`,
   `%USERPROFILE%\.aerotagger\exiftool` oder, falls nirgends vorhanden, frisch
   geladen (über SourceForge, wo exiftool.org die Windows-Version bereitstellt),
4. kopiert Beispiele und Anleitung dazu und
5. packt alles als `dist\AeroTagger-<Version>-windows.zip`.

Der Ordner `dist\AeroTagger` läuft ohne installiertes Python und lässt sich
beliebig verschieben oder weitergeben; die EXE braucht den Ordner `_internal`
und ExifTool daneben. Eine nicht signierte EXE zeigt beim ersten Start die
SmartScreen-Warnung – „Weitere Informationen → Trotzdem ausführen“.

## Updates

**Hilfe → Nach Updates suchen …** fragt bei GitHub nach dem neuesten Release.
Gibt es eine neuere Version, zeigt AeroTagger, was neu ist, und bietet an:

- **Jetzt aktualisieren** – lädt die neue Version und spielt sie ein:
  - gestartet mit `start_windows.bat` bzw. `start_mac_linux.command`: der
    Quellcode wird ersetzt (`.venv`, eigene Dateien und Einstellungen bleiben),
    geänderte Abhängigkeiten werden nachinstalliert, danach Neustart;
  - als Windows-EXE: die `AeroTagger-<Version>-windows.zip` aus dem Release
    wird geladen; AeroTagger beendet sich, ein kleines Hilfsfenster ersetzt
    die Dateien und startet das Programm neu.
- **Auf GitHub ansehen** – öffnet die Release-Seite im Browser.

Woher die Updates kommen, trägt `publish_github.bat` automatisch ein
(`aerotagger/resources/github_repo.txt`). Abweichend davon lässt es sich unter
**Einstellungen → Updates von GitHub** festlegen (Form `benutzer/AeroTagger`).

Das AeroTagger-Repository ist öffentlich – dafür ist kein Token nötig.

**Nur bei privatem Repository:** GitHub gibt die Releases dann nur mit Anmeldung heraus.
Unter **Einstellungen → GitHub-Token** einen Token eintragen: auf github.com
Settings → Developer settings → Personal access tokens → *Fine-grained tokens* →
*Generate new token*, nur das AeroTagger-Repository auswählen und bei
*Repository permissions* „Contents“ auf *Read-only* stellen. Der Token wird
unverschlüsselt in `%USERPROFILE%\.aerotagger\einstellungen.json` gespeichert.

Im eigenen Entwicklungsordner (mit `.git`) ist das Update abgeschaltet – dort
aktualisiert man mit Git bzw. `publish_github.bat`.

## Auf GitHub veröffentlichen

`publish_github.bat` doppelklicken – Einzelheiten in [GITHUB.md](GITHUB.md).

## Bedienung

1. Links einen Ordner wählen. Die Ordnerspalte lässt sich einklappen – mit
   „◧ Ordner“ in der Werkzeugleiste, Strg+B, dem „«“ oben in der Spalte oder
   indem man die Trennlinie ganz nach links zieht. In der Mitte zeigt AeroTagger oben das aktuelle Bild
   groß mit Aufnahmedaten, darunter alle Bilder des Ordners als Filmstreifen.
   Mit ← → oder dem Mausrad blättern, Strg/Umschalt+Klick oder Strg+A markiert
   mehrere Bilder. Die Trennlinie über dem Filmstreifen lässt sich ziehen; die
   Bildgröße im Streifen passt sich an. Doppelklick öffnet das Bild im
   Standardprogramm.
   **Sternbewertung:** Tasten **0–5** (auch Ziffernblock) setzen die Bewertung
   der ausgewählten Bilder und schreiben sie sofort in die Datei – 0 entfernt
   sie. Geschrieben wird XMP-Rating (Lightroom, Bridge, Photo Mechanic), bei
   JPEG zusätzlich EXIF Rating/RatingPercent für den Windows-Explorer; bei RAW
   je nach Einstellung in die XMP-Begleitdatei. Die Sterne stehen im
   Filmstreifen links oben, die getaggte Registrierung in derselben Zeile
   rechtsbündig, und unter der großen Vorschau. RAW-Dateien tragen rechts
   unter dem Bild, neben dem Dateinamen, das Kennzeichen „RAW“.
   **Bewertungsfilter:** Die Zeile über dem Filmstreifen filtert wie in
   Lightroom Classic: Vergleich wählen (≥ mindestens, = genau, ≤ höchstens),
   dann auf einen Stern klicken – nur passende Bilder bleiben sichtbar.
   Erneuter Klick auf denselben Stern oder „✕“ hebt den Filter auf. Rechts steht,
   wie viele Bilder zu sehen sind. „≤“ schließt unbewertete Bilder ein. Der
   Filter gilt sofort auch für neu vergebene Sterne und bleibt beim nächsten
   Start erhalten.
   **Lupe:** Rechte Maustaste im großen Vorschaubild gedrückt halten – eine
   runde Lupe folgt dem Mauszeiger und zeigt den Bereich in voller Auflösung
   (100 %). Mit dem Mausrad lässt sich bei gedrückter Taste zwischen 50, 100,
   200 und 400 % wechseln; Loslassen schließt die Lupe. Die volle Auflösung wird
   beim ersten Rechtsklick geladen (bei RAW-Dateien das größte eingebettete JPEG).
   Unter der Vorschau stehen die vorhandenen Metadaten des Bildes (Überschrift,
   Beschreibung, Stichwörter, Ort, Fotograf, Copyright, Bewertung …) und
   wechseln beim Blättern sofort mit. Ein- und ausblenden: „Metadaten
   einblenden“ in der Werkzeugleiste oder Strg+I.
   Unter „Ansicht“ (Strg+1 / Strg+2) lässt sich auf den Kontaktabzug umschalten,
   der alle Bilder als Raster zeigt; dort regelt der Schieber „Größe“ die Kacheln
   (der Schieber erscheint nur im Kontaktabzug).
2. Rechts unter „Metadaten schreiben“ Felder ausfüllen. Nur **angehakte** Felder
   werden geschrieben; ein angehaktes leeres Feld löscht den Inhalt im Bild.
3. „Vorschau…“ zeigt je Datei, was geschrieben würde. „Anwenden“ (Strg+Enter) schreibt.

„Bild-Info“ zeigt die Metadaten des aktuellen Bildes, „Protokoll“ Hinweise und Fehler.
Feldsätze lassen sich als Vorlage speichern.

## Fokuspunkte (Canon)

**Ansicht → Fokuspunkte anzeigen** oder Taste **F** blendet in der großen Vorschau
die AF-Felder ein, die die Kamera in der Datei vermerkt hat – ähnlich dem
Lightroom-Plugin FocusPoints:

- **rot**: Feld, auf das scharfgestellt wurde
- **weiß**: ausgewähltes Feld ohne Schärfe-Bestätigung
- **blass**: übrige AF-Felder der Kamera (bei Spiegelreflexkameras)

- **bernstein, gestrichelt**: das von der Kamera verfolgte Motiv (EOS R, siehe unten)

Oben links stehen AF-Bereichsmodus, Zahl der Felder im Fokus und – wenn
vorhanden – was die Kamera verfolgt hat, z. B. „Verfolgt: Fahrzeug · Körper“. Hochformat-Bilder
werden richtig gedreht. Die Daten stammen aus den Canon-MakerNotes (CR2, CR3, CRW
und Kamera-JPEGs); bei anderen Herstellern oder bearbeiteten Exporten ohne
MakerNotes erscheint „Keine Fokuspunkte“. Die Einstellung bleibt nach dem
Neustart erhalten.

**EOS R-Serie:** Im Servo-AF mit Motivverfolgung markieren die R-Modelle oft
kein Feld als „im Fokus“ – das AF-Feld erscheint dann weiß. Aussagekräftiger
ist der Bereich, den die Kamera beim Auslösen verfolgt hat:

| Modelle | angezeigt |
|---|---|
| R1, R5 Mark II, R6 Mark III, R8 Mark II | verfolgter Bereich mit Motivart (Person, Tier, Fahrzeug) und Teil (Kopf, Körper, Auge …) |
| R3, R5, R6, R6 Mark II, R8, R50 | verfolgter Bereich |
| R7, R10 | nur der Mittelpunkt (Fadenkreuz) |

Dafür ist ExifTool 13.62 oder neuer nötig (beiliegend bzw. beim Windows-Build
geladen; ein älteres, selbst ausgewähltes ExifTool zeigt nur die AF-Felder).
Bilder mit Seitenverhältnis 1:1, 4:3 oder 16:9 aus dem Kameramenü werden
berücksichtigt. Liegt ein AF-Feld nur bei gespiegelter Höhenachse auf dem
verfolgten Motiv, korrigiert AeroTagger die Richtung automatisch.

## Metadaten Template

Menü **Metadaten › Metadaten Template…** (Strg+M) öffnet einen Dialog mit
denselben Feldern wie der Reiter „Metadaten schreiben“: alle Metadatenfelder,
Weitere Tags, Kürzel- und Daten-CSV, Stichwort-Modus, Startwert für `{seq}`
und Umbenennen. Das Template wird mit einem Namen dauerhaft gespeichert und ist
unabhängig vom Reiter; „Aus Reiter übernehmen“ kopiert den aktuellen Stand
des Reiters hinein.

- **Exportieren… / Importieren…** speichern bzw. laden das Template als
  JSON-Datei – zum Sichern, für mehrere Projekte oder zum Weitergeben.
  Vorlagen aus dem Reiter „Metadaten schreiben“ lassen sich ebenfalls
  importieren. Beides gibt es auch direkt im Menü Metadaten.
- **Metadaten › Template „…“ auf Auswahl anwenden** (Strg+Umschalt+M)
  schreibt das Template in die ausgewählten Bilder – mit Rückfrage bzw.
  Vorschau, wenn Variablen nicht aufgelöst werden können.

## Feld „Bewertung“

Im Reiter „Metadaten schreiben“ und im Dialog „Metadaten Template“ gibt es in
der Gruppe „Inhalt“ das Feld **Bewertung**: Klick auf einen Stern setzt die
Bewertung, ein erneuter Klick auf denselben Stern setzt sie auf 0 (keine
Sterne); mit Fokus gehen auch die Tasten 0–5. Wie alle Felder wird es nur
geschrieben, wenn es angehakt ist – XMP-Rating, bei JPEG zusätzlich EXIF
Rating/RatingPercent. „Aus Bild übernehmen“ liest die Sterne zurück.

## Variablen

Über „Variable einfügen“ oder von Hand, z. B.

    © {year4} Alexander Pauli Photography
    {folder}-{seq:3}
    Aufgenommen am {date:%d. %B %Y} mit {model}

- Datei: `{filename}` `{filenamebase}` `{extension}` `{folder}` `{folderpath}` `{path}` `{frame}`
- Aufnahmedatum: `{date}` `{isodate}` `{time}` `{year4}` `{year2}` `{month2}` `{day2}`
  `{monthname}` `{dayname}` `{hour24}` `{minute}` `{second}`, eigenes Format `{date:%d.%m.%Y}`, `{today}`
- Kamera: `{make}` `{model}` `{lens}` `{serial}` `{focallength}` `{aperture}` `{shutter}` `{iso}` `{width}` `{height}`
- Zähler: `{seq}` `{seq:3}` `{count}`
- vorhandene Metadaten: `{headline}` `{caption}` `{keywords}` `{city}` … (alle Feldschlüssel)
- beliebiger ExifTool-Tag: `{tag:XMP-dc:Title}`
- Zusätze: `{city|upper}` `{city|lower}` `{name|title}`, Ersatztext falls leer: `{city?unbekannt}`

## Kürzel-CSV (Ersetzungsroutine)

Tabelle ohne Kopfzeile: Spalte 1 = Kürzel, Spalte 2 ff. = Ersetzungen (siehe `beispiele/kuerzel.csv`).

    h17;Max Mustermann (#17);Stürmer

Im Text ergibt `=h17=` → „Max Mustermann (#17)“, `=h17#3=` → „Stürmer“.
Ersetzungen dürfen selbst Variablen enthalten.

## Daten-CSV

Tabelle mit Kopfzeile; eine Spalte enthält den Dateinamen (mit oder ohne Endung),
siehe `beispiele/daten.csv`. `{csv:Spaltenname}` liefert den Wert aus der Zeile des
jeweiligen Bildes. „Spalten den Feldern zuordnen“ trägt das automatisch ein, wenn
Spaltenüberschriften wie die Felder heißen (Überschrift, Stadt, Stichwörter …).

Trennzeichen (; , Tab) und Kodierung (UTF-8 oder Windows/Excel) werden erkannt.

## AircraftTag – Flugzeugfotos beschriften

Der Reiter **AircraftTag** ist ein eigener Modus für Flugzeugfotos. Er steht an
erster Stelle und ist beim Start immer aktiv.

1. Unten unter „AircraftTags-Quelle“ die Flugzeug-CSV laden (Beispiel:
   `beispiele/aircrafttags.csv`). Kopfzeile mit beliebigen Spalten; die Spalte
   mit der Registrierung wird erkannt (Registration, Registrierung, Reg,
   Kennzeichen …) oder unter „Registrierung in“ gewählt. Zeilen mit `#` am
   Anfang werden übersprungen. Nach Änderungen an der CSV: ⟳.
2. Bild(er) im Filmstreifen wählen, oben die Registrierung eintippen
   (Strg+T springt von überall in dieses Feld). Groß-/Kleinschreibung,
   Bindestrich und Leerzeichen sind egal – `oelba` findet `OE-LBA`.
   Die Vorschlagsliste zeigt passende Registrierungen; der gefundene Datensatz
   steht darunter.
3. **Enter** schreibt. Ist „zum nächsten Bild springen“ an, geht es danach
   automatisch weiter; die Registrierung bleibt markiert stehen – Enter schreibt
   sie ins nächste Bild, Tippen ersetzt sie.

### Kennzeichnung „getaggt“

Jedes Bild, das im Reiter AircraftTag geschrieben wird, bekommt zusätzlich

- das Stichwort **AeroTagger** und
- die hierarchischen Stichwörter `AeroTagger|Registrierung|…`,
  `AeroTagger|Operator|…` und `AeroTagger|Typ|…` (XMP `lr:HierarchicalSubject`,
  in Lightroom als Stichwortbaum AeroTagger › Registrierung › … sichtbar).

Wird ein Bild neu getaggt, ersetzt AeroTagger diese drei Einträge. Daran
erkennt AeroTagger getaggte Bilder: Im Filmstreifen tragen sie oben rechts
die Registrierung auf einem bernsteinfarbenen Schild, und unter der großen
Vorschau stehen Registrierung, Operator und Flugzeugtyp. Der Ordner wird dazu
beim Öffnen im Hintergrund gelesen. Operator und Typ stammen aus den Spalten
Airline/Operator/Betreiber bzw. Type/Typ/Muster der Flugzeugdaten.

### Aufnahmedaten: Airport, Fotograf, Aufnahmedatum

Im Block „Aufnahmedaten“ stehen drei Felder, die als Variablen weiterverwendet
werden können – im Reiter AircraftTag und im Reiter „Metadaten schreiben“:

| Feld | Variable | vorausgefüllt mit |
|---|---|---|
| Airport | `{airport}` | dem zuletzt verwendeten Airport; die Liste merkt sich die letzten 20 |
| Fotograf | `{fotograf}` | dem gespeicherten Namen; ist das Feld leer, mit dem Fotografen aus dem Bild |
| Aufnahmedatum | `{aufnahme}` | dem EXIF-Aufnahmedatum des jeweiligen Bildes |

Das Aufnahmedatum gilt automatisch je Bild – beim Schreiben mehrerer Bilder
bekommt jedes sein eigenes Datum, eigenes Format z. B. `{aufnahme:%d. %B %Y}`.
Wer ins Feld tippt, setzt ein festes Datum für alle Bilder; „↺ aus Bild“
schaltet zurück.

Voreingestellt schreibt der AircraftTagger `{airport}` ins Ortsdetail und
`{fotograf}` ins Fotografenfeld. Ergibt ein Feld im AircraftTagger einen leeren
Text (z. B. weil kein Airport eingetragen ist), wird es nicht geschrieben und
der vorhandene Inhalt im Bild bleibt erhalten.

### Online-Abfrage über adsbdb.com (Ersatz: hexdb.io)

Unter „Flugzeugdaten-Quelle“ lässt sich umschalten:

| Quelle | Verhalten |
|---|---|
| CSV-Datei | nur die eigene AircraftTags-CSV |
| Online: adsbdb.com / hexdb.io | Abfrage bei `https://api.adsbdb.com/v0/aircraft/<Registrierung>`; liefert adsbdb.com nichts (unbekannt oder nicht erreichbar), dann `https://hexdb.io/api/v2/aircraft?registration=<Registrierung>` |
| CSV-Datei, sonst online | erst die CSV, für unbekannte Registrierungen online wie oben |

Online wird nachgeschlagen, sobald die Eingabe kurz ruht oder mit Enter. Statt der
Registrierung darf auch der Mode-S-Hexcode (z. B. `440017`) eingegeben werden.
Jedes Ergebnis wird in der **Cache-Tabelle** `~/.aerotagger/aircraft_cache.csv`
gespeichert und danach ohne erneute Online-Abfrage verwendet – auch offline.
„Öffnen“ zeigt die Tabelle (z. B. in Excel; vor dem nächsten Schreiben wieder
schließen), „Leeren“ löscht sie, „neu abfragen“ aktualisiert einen Eintrag.

Spalten aus adsbdb.com (als `{ac:Spalte}` nutzbar):

| Spalte | Inhalt |
|---|---|
| Registration | Registrierung, auch `{ac}` |
| Type | Hersteller + Typ, z. B. „Airbus A320 214“ |
| Manufacturer, Model | Hersteller bzw. Typbezeichnung einzeln |
| ICAO-Typ | ICAO-Typcode, z. B. A320 |
| Airline | eingetragener Halter (kann auch eine Leasingfirma sein) |
| Operator-ICAO | ICAO-Code des Halters |
| Country, CountryCode | Registrierungsland |
| ModeS | Mode-S-Hexcode |
| PhotoURL, Abgefragt, Quelle | Foto-Link, Abfragedatum, „adsbdb.com“ |

Ergebnisse von hexdb.io landen mit denselben Spalten im Cache; die Spalte
„Quelle“ zeigt, woher ein Eintrag stammt. hexdb.io liefert kein
Registrierungsland – Country und CountryCode bleiben dann leer. Ist eine
Registrierung dort mehreren Flugzeugen zugeordnet, wird das erste genommen.

Die Spaltennamen passen zu den voreingestellten Feldvorlagen. Im Modus
„CSV-Datei, sonst online“ gelten die Spalten beider Quellen; was eine Quelle
nicht kennt, bleibt leer.

Was geschrieben wird, legen die Felder unter „Beim Taggen schreiben“ fest.
Alle CSV-Spalten stehen dort (und auch im Reiter „Metadaten schreiben“) als
Variablen bereit:

    {ac}               Registrierung
    {ac:Type}          Spalte „Type“ der CSV
    {ac:Airline}       Spalte „Airline“ der CSV

Die Tabelle unter der Registrierung zeigt Airport, Fotograf, Aufnahmedatum und
den Datensatz des Flugzeugs, jeweils mit Variablenname. Ein Klick auf die
Variable (oder ein Doppelklick auf die Zeile) fügt sie in das zuletzt bearbeitete
Feld ein – auch in die Umbenennen-Vorlage.
Die Flugzeugdaten lassen sich über den kleinen Pfeil über der Tabelle ein- und
ausklappen; Airport, Fotograf und Aufnahmedatum bleiben dabei sichtbar.
Stichwörter werden in diesem Modus standardmäßig **hinzugefügt**, nicht ersetzt.
Steht eine Registrierung nicht in der Liste, fragt AeroTagger nach und setzt nur
die Registrierung ein. Ist in einem Bild schon eine bekannte Registrierung
eingetragen (Stichwörter, Titel oder Überschrift), zeigt der Reiter sie an.

## Dateien umbenennen

In beiden Reitern („Metadaten schreiben“ und „AircraftTag“) gibt es den Block
**Datei umbenennen**: Ist „beim Schreiben umbenennen“ angehakt, erhält jede
Datei nach dem Schreiben der Metadaten einen neuen Namen nach der Vorlage, z. B.

    {isodate}_{ac}_{frame}                 → 2026-11-07_OE-ABC_4711.jpg
    {aufnahme:%Y%m%d}_{ac:ICAO-Typ}_{ac}   → 20261107_A320_OE-ABC.jpg

- Die Endung bleibt erhalten und wird nicht in die Vorlage geschrieben.
- Unerlaubte Zeichen (`\ / : * ? " < > |`) werden zu „-“; doppelte oder
  hängende Trenner aus leeren Variablen fallen weg.
- Ist der Name bereits vergeben, wird `_2`, `_3` … angehängt – zum Beispiel
  für Serien desselben Flugzeugs (besser: `{frame}` oder `{seq:3}` verwenden).
- Bei RAW-Dateien wird die XMP-Begleitdatei mit umbenannt.
- Ergibt die Vorlage einen leeren Namen, bleibt die Datei, wie sie ist.
- Die Live-Vorschau und „Vorschau…“ zeigen den neuen Namen vorab. Ist kein Feld
  angehakt, wird nur umbenannt.
- Der Filmstreifen behält die Reihenfolge bei; F5 sortiert neu.

## Wohin wird geschrieben?

Jedes Feld landet in XMP und – soweit vorhanden – im passenden IPTC- und EXIF-Feld
(Tooltip am Feldnamen zeigt die Ziele). Unter „Weitere Tags“ lässt sich jeder
ExifTool-Tag direkt setzen, z. B. `XMP-xmp:Rating = 5`.

RAW-Dateien bleiben standardmäßig unangetastet: Die Metadaten kommen in eine
XMP-Begleitdatei (`IMG_1234.xmp`, wie bei Lightroom). In den Einstellungen lässt
sich das auf „direkt in die RAW-Datei“ umstellen; dort gibt es auch die Option
für Sicherungskopien.

Einstellungen, Vorlagen und Vorschau-Cache liegen in `~/.aerotagger`.
Beim ersten Start übernimmt AeroTagger Einstellungen, Vorlagen und den
Flugzeug-Cache des Vorgängers „FotoMeta“ aus `~/.fotometa`.
