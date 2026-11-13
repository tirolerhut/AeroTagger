"""AeroTagger – Kernlogik ohne GUI: ExifTool-Anbindung, Felddefinitionen,
Variablen-/Ersetzungs-Engine und CSV-Tabellen."""
from __future__ import annotations

import csv
import datetime as dt
import html
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "AeroTagger"
APP_VERSION = "0.2.16"
if getattr(sys, "frozen", False):
    # als EXE (PyInstaller): Programmordner = Ordner der AeroTagger.exe,
    # dort liegt auch ExifTool (exiftool.exe + exiftool_files)
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path.home() / ".aerotagger"
OLD_CONFIG_DIR = Path.home() / ".fotometa"     # Vorgänger „FotoMeta“


def migrate_config() -> bool:
    """Übernimmt beim ersten Start Einstellungen, Vorlagen und den
    Flugzeug-Cache aus ~/.fotometa (Vorschaubilder werden neu erzeugt)."""
    if CONFIG_DIR.exists() or not OLD_CONFIG_DIR.is_dir():
        return False
    try:
        shutil.copytree(OLD_CONFIG_DIR, CONFIG_DIR,
                        ignore=shutil.ignore_patterns("vorschau", "*.tmp"))
        cfg = CONFIG_DIR / "einstellungen.json"
        if cfg.is_file():
            data = json.loads(cfg.read_text(encoding="utf-8"))
            et = data.get("exiftool", "")
            if et and et.startswith(str(OLD_CONFIG_DIR)):
                data["exiftool"] = str(CONFIG_DIR) + et[len(str(OLD_CONFIG_DIR)):]
            cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except (OSError, ValueError):
        return False

JPEG_EXT = {".jpg", ".jpeg", ".jpe"}
RAW_EXT = {
    ".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf",
    ".orf", ".rw2", ".dng", ".pef", ".raw", ".rwl", ".3fr", ".iiq", ".erf",
    ".srw", ".x3f", ".gpr", ".mrw", ".dcr", ".kdc", ".mos",
}


def is_raw(path) -> bool:
    return Path(path).suffix.lower() in RAW_EXT


def is_jpeg(path) -> bool:
    return Path(path).suffix.lower() in JPEG_EXT


def is_supported(path) -> bool:
    s = Path(path).suffix.lower()
    return s in JPEG_EXT or s in RAW_EXT


def sidecar_path(path) -> str:
    """Adobe-/Lightroom-Konvention: IMG_1234.CR3 -> IMG_1234.xmp"""
    return str(Path(path).with_suffix(".xmp"))


# --------------------------------------------------------------------------
# Felder
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Field:
    key: str
    label: str
    group: str
    tags: tuple          # Schreibziele; Lesereihenfolge: XMP vor IPTC vor EXIF
    multiline: bool = False
    is_list: bool = False
    hint: str = ""


FIELDS = [
    # Inhalt
    Field("headline", "Überschrift", "Inhalt",
          ("XMP-photoshop:Headline", "IPTC:Headline")),
    Field("caption", "Beschreibung", "Inhalt",
          ("XMP-dc:Description", "IPTC:Caption-Abstract", "EXIF:ImageDescription"),
          multiline=True),
    Field("keywords", "Stichwörter", "Inhalt",
          ("XMP-dc:Subject", "IPTC:Keywords"), is_list=True,
          hint="durch Komma oder Semikolon getrennt"),
    Field("rating", "Bewertung", "Inhalt", ("XMP-xmp:Rating", "IFD0:Rating"),
          hint="Sterne 0–5"),
    Field("title", "Titel", "Inhalt", ("XMP-dc:Title", "IPTC:ObjectName")),
    Field("persons", "Abgebildete Personen", "Inhalt",
          ("XMP-iptcExt:PersonInImage",), is_list=True,
          hint="durch Komma oder Semikolon getrennt"),
    Field("event", "Ereignis", "Inhalt", ("XMP-iptcExt:Event",)),
    Field("captionwriter", "Autor der Beschreibung", "Inhalt",
          ("XMP-photoshop:CaptionWriter", "IPTC:Writer-Editor")),
    # Urheber
    Field("creator", "Fotograf", "Urheber und Rechte",
          ("XMP-dc:Creator", "IPTC:By-line", "EXIF:Artist")),
    Field("creatortitle", "Position", "Urheber und Rechte",
          ("XMP-photoshop:AuthorsPosition", "IPTC:By-lineTitle")),
    Field("credit", "Bildnachweis", "Urheber und Rechte",
          ("XMP-photoshop:Credit", "IPTC:Credit")),
    Field("source", "Quelle", "Urheber und Rechte",
          ("XMP-photoshop:Source", "IPTC:Source")),
    Field("copyright", "Copyright", "Urheber und Rechte",
          ("XMP-dc:Rights", "IPTC:CopyrightNotice", "EXIF:Copyright")),
    Field("usage", "Nutzungsbedingungen", "Urheber und Rechte",
          ("XMP-xmpRights:UsageTerms",), multiline=True),
    Field("email", "E-Mail", "Urheber und Rechte",
          ("XMP-iptcCore:CreatorWorkEmail",)),
    Field("url", "Website", "Urheber und Rechte",
          ("XMP-iptcCore:CreatorWorkURL",)),
    # Ort
    Field("location", "Ortsdetail", "Ort",
          ("XMP-iptcCore:Location", "IPTC:Sub-location")),
    Field("city", "Stadt", "Ort", ("XMP-photoshop:City", "IPTC:City")),
    Field("state", "Bundesland", "Ort",
          ("XMP-photoshop:State", "IPTC:Province-State")),
    Field("country", "Land", "Ort",
          ("XMP-photoshop:Country", "IPTC:Country-PrimaryLocationName")),
    Field("countrycode", "Ländercode", "Ort",
          ("XMP-iptcCore:CountryCode", "IPTC:Country-PrimaryLocationCode"),
          hint="ISO-Code, z. B. AUT"),
    # Workflow
    Field("instructions", "Anweisungen", "Workflow",
          ("XMP-photoshop:Instructions", "IPTC:SpecialInstructions")),
    Field("jobid", "Auftragskennung", "Workflow",
          ("XMP-photoshop:TransmissionReference",
           "IPTC:OriginalTransmissionReference")),
    Field("usercomment", "EXIF-Kommentar", "Workflow", ("EXIF:UserComment",)),
]
FIELD_BY_KEY = {f.key: f for f in FIELDS}

# Technische Angaben, die für Anzeige und Variablen gelesen werden
INFO_TAGS = [
    "Make", "Model", "LensModel", "LensID", "Lens", "SerialNumber",
    "FocalLength", "FNumber", "ExposureTime", "ISO", "DateTimeOriginal",
    "CreateDate", "FileModifyDate", "ImageWidth", "ImageHeight",
    "Orientation", "FileSize", "FileType", "Rating", "Label", "HierarchicalSubject",
]

_EXIF_GROUPS = {"ifd0", "exififd", "subifd", "ifd1", "gps", "interopifd"}


def _to_text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ", ".join(_to_text(x) for x in v)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def lookup(meta: dict, spec: str):
    """Sucht einen Tag in einem ExifTool-JSON-Datensatz (-G1).
    spec: 'Tag', 'Gruppe:Tag'; Gruppe darf Familie 0 (EXIF, XMP, IPTC) oder
    Familie 1 (XMP-dc, IFD0 …) sein. Groß-/Kleinschreibung egal."""
    if not meta:
        return None
    grp, _, tag = spec.rpartition(":")
    grp, tag = grp.lower(), tag.lower()
    for k, v in meta.items():
        kg, _, kt = k.rpartition(":")
        if kt.lower() != tag:
            continue
        kg = kg.lower()
        if (not grp or kg == grp
                or (grp == "exif" and kg in _EXIF_GROUPS)
                or (grp == "xmp" and kg.startswith("xmp"))):
            if v not in (None, ""):
                return v
    return None


def field_value(meta: dict, f: Field) -> str:
    for t in f.tags:
        v = lookup(meta, t)
        if v is not None:
            return _to_text(v)
    return ""


_BAD_FN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def clean_filename(name: str, ext: str = "") -> str:
    """Macht aus dem Ergebnis der Umbenennen-Vorlage einen gültigen Dateinamen
    (ohne Endung). Unerlaubte Zeichen werden zu „-“, doppelte Trenner und
    Trenner am Anfang/Ende entfallen (z. B. bei leeren Variablen)."""
    s = (name or "").replace("\n", " ").strip()
    if ext and s.lower().endswith(ext.lower()):
        s = s[: -len(ext)]
    s = _BAD_FN.sub("-", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"_{2,}", "_", s)
    s = re.sub(r"-{2,}", "-", s)
    s = re.sub(r"\.{2,}", ".", s)
    s = re.sub(r"[_\-.]\s*[_\-]+", lambda m: m.group(0)[0], s)   # „_-“, „-_“ → erstes Zeichen
    s = s.strip(" ._-")
    return s[:200].rstrip(" .")


def rename_file(path: str, new_stem: str) -> str:
    """Benennt eine Datei um (Endung bleibt). Bei RAW wird eine vorhandene
    XMP-Begleitdatei mitgenommen. Ist der Name belegt, wird _2, _3 …
    angehängt. Rückgabe: neuer Pfad."""
    p = Path(path)
    ext = p.suffix
    stem = clean_filename(new_stem, ext)
    if not stem:
        raise OSError("Der neue Dateiname ist leer.")
    side = Path(sidecar_path(p)) if is_raw(p) else None
    if side is not None and not side.is_file():
        side = None

    def same(a: Path, b: Path) -> bool:
        try:
            return a.exists() and os.path.samefile(a, b)
        except OSError:
            return False

    n = 1
    while True:
        cand = stem if n == 1 else f"{stem}_{n}"
        target = p.with_name(cand + ext)
        starget = p.with_name(cand + ".xmp") if side else None
        free = not target.exists() or same(target, p)
        if free and starget is not None:
            free = not starget.exists() or same(starget, side)
        if free:
            break
        n += 1
        if n > 9999:
            raise OSError("Kein freier Dateiname gefunden.")
    if target.name == p.name:
        return str(p)
    os.rename(p, target)
    if side is not None and starget.name != side.name:
        try:
            os.rename(side, starget)
        except OSError as e:
            os.rename(target, p)   # zurück, damit Bild und Begleitdatei zusammenbleiben
            raise OSError(f"Begleitdatei {side.name} ließ sich nicht umbenennen: {e}")
    return str(target)


def tidy_line(text: str) -> str:
    """Doppelte Leerzeichen und verwaiste Trenner entfernen, die entstehen,
    wenn eine Variable leer bleibt (z. B. „ – A320“ → „A320“)."""
    t = re.sub(r"[ \t]{2,}", " ", text or "")
    t = re.sub(r"\(\s*\)", "", t)
    t = re.sub(r"\s+([,.;:])", r"\1", t)
    t = re.sub(r"^[\s,;:–\-·]+|[\s,;:–\-·]+$", "", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def split_list(text: str) -> list:
    out = []
    for part in re.split(r"[;,\n]", text):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


# --------------------------------------------------------------------------
# ExifTool
# --------------------------------------------------------------------------
class ExifToolError(Exception):
    pass


def _popen_flags():
    if sys.platform == "win32":
        return {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    return {}


LAST_ERROR = ""   # Grund, warum das zuletzt geprüfte ExifTool nicht lief


def _resolve_dir(p: Path) -> Path:
    """Ordner gewählt? Dann die ExifTool-Programmdatei darin suchen."""
    if not p.is_dir():
        return p
    for name in ("exiftool.exe", "exiftool(-k).exe", "exiftool"):
        if (p / name).is_file():
            return p / name
    hits = sorted(p.glob("exiftool*.exe")) or sorted(p.glob("*/exiftool*.exe"))
    return hits[0] if hits else p


def _prepare_windows_exe(p: Path) -> Path:
    """Das Windows-Paket heißt „exiftool(-k).exe“. Das „-k“ im Namen lässt
    ExifTool nach jedem Aufruf auf die Eingabetaste warten – damit ist es für
    andere Programme unbrauchbar. Wie von exiftool.org empfohlen, wird eine
    Kopie namens exiftool.exe angelegt (neben dem Original, sonst unter
    ~/.aerotagger/exiftool samt Ordner exiftool_files)."""
    name = p.name.lower()
    if (p.suffix.lower() != ".exe" or name == "exiftool.exe"
            or not name.startswith("exiftool") or "(" not in name):
        return p
    target = p.with_name("exiftool.exe")
    try:
        if not target.exists():
            shutil.copy2(p, target)
        return target
    except OSError:
        pass
    dest = CONFIG_DIR / "exiftool"
    try:
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest / "exiftool.exe")
        files = p.parent / "exiftool_files"
        if files.is_dir() and not (dest / "exiftool_files").exists():
            shutil.copytree(files, dest / "exiftool_files")
        return dest / "exiftool.exe"
    except OSError:
        return p


def _as_cmd(p: Path):
    """Pfad -> Kommandoliste (Perl-Skript wird über perl gestartet)."""
    global LAST_ERROR
    p = _resolve_dir(p)
    if not p.is_file():
        LAST_ERROR = f"Datei nicht gefunden: {p}"
        return None
    if sys.platform == "win32":
        p = _prepare_windows_exe(p)
    if p.suffix.lower() == ".exe":
        return [str(p)]
    try:
        with open(p, "rb") as fh:
            head = fh.read(64)
    except OSError as e:
        LAST_ERROR = f"Datei nicht lesbar: {e}"
        return None
    if head.startswith(b"#!") and b"perl" in head:
        perl = shutil.which("perl")
        if not perl:
            LAST_ERROR = f"{p.name} ist ein Perl-Skript, Perl ist aber nicht installiert."
            return None
        return [perl, str(p)]
    return [str(p)]


def exiftool_version(cmd):
    global LAST_ERROR
    try:
        # stdin=DEVNULL: Falls doch eine „-k“-Version läuft, endet die Pause sofort
        r = subprocess.run(cmd + ["-ver"], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, timeout=30, **_popen_flags())
    except subprocess.TimeoutExpired:
        LAST_ERROR = f"{cmd[-1]} antwortet nicht (Zeitüberschreitung)."
        return None
    except Exception as e:  # noqa – z. B. OSError, fehlende Rechte
        LAST_ERROR = f"{cmd[-1]} lässt sich nicht starten: {e}"
        return None
    m = re.search(r"^\s*(\d+\.\d+)", r.stdout or "")
    if m:
        return m.group(1)
    detail = (r.stderr or r.stdout or "").strip()[:300]
    hint = ""
    exe = Path(cmd[-1])
    if exe.suffix.lower() == ".exe" and not (exe.parent / "exiftool_files").is_dir():
        hint = (" Neben der exe fehlt der Ordner „exiftool_files“ – bitte den "
                "gesamten Inhalt des ExifTool-Zips zusammen entpacken.")
    LAST_ERROR = f"{exe.name} liefert keine Versionsnummer.{hint}" + \
        (f" Meldung: {detail}" if detail else "")
    return None


def find_exiftool(configured: str = "", strict=False):
    """Liefert (Kommandoliste, Version) oder (None, None). Schlägt der
    ausdrücklich gewählte Pfad fehl, steht der Grund danach in LAST_ERROR;
    mit strict=True wird dann nicht nach anderen Installationen gesucht."""
    global LAST_ERROR
    configured = (configured or "").strip().strip('"')
    if configured:
        cmd = _as_cmd(Path(configured))
        ver = exiftool_version(cmd) if cmd else None
        if ver:
            LAST_ERROR = ""
            return cmd, ver
        if strict:
            return None, None
        first_error = LAST_ERROR
    else:
        first_error = ""
    cands = []
    dirs = [APP_DIR, APP_DIR / "exiftool", CONFIG_DIR / "exiftool"]
    names = ("exiftool.exe", "exiftool(-k).exe") if sys.platform == "win32" else ("exiftool",)
    for d in dirs:
        cands += [d / n for n in names]
    w = shutil.which("exiftool")
    if w:
        cands.append(Path(w))
    if sys.platform != "win32":
        cands.append(APP_DIR / "vendor" / "exiftool" / "exiftool")
    for c in cands:
        if not c.is_file():
            continue
        cmd = _as_cmd(c)
        if cmd:
            ver = exiftool_version(cmd)
            if ver:
                LAST_ERROR = ""
                return cmd, ver
    if first_error:
        LAST_ERROR = first_error
    elif not LAST_ERROR:
        LAST_ERROR = "Kein ExifTool gefunden."
    return None, None


# exiftool.org liefert die Windows-Zips über SourceForge aus; beide Quellen versuchen
EXIFTOOL_ZIP_URLS = (
    "https://sourceforge.net/projects/exiftool/files/exiftool-{ver}_64.zip/download",
    "https://exiftool.org/exiftool-{ver}_64.zip",
)


def download_exiftool_windows(progress=None) -> str:
    """Lädt die offizielle Windows-Version von exiftool.org nach
    ~/.aerotagger/exiftool und gibt den Pfad zur exiftool.exe zurück."""
    import urllib.request
    import zipfile

    def get(url):
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()

    ver = get("https://exiftool.org/ver.txt").decode().strip()
    if progress:
        progress(f"Lade ExifTool {ver} …")
    data, last = None, ""
    for url in (EXIFTOOL_ZIP_URLS):
        url = url.format(ver=ver)
        try:
            d = get(url)
        except Exception as e:  # noqa
            last = f"{url}: {e}"
            continue
        if d[:2] == b"PK":                     # wirklich ein Zip, keine Webseite
            data = d
            break
        last = f"{url} lieferte keine ZIP-Datei"
    if data is None:
        raise ExifToolError(f"Download von ExifTool {ver} fehlgeschlagen ({last}).")
    dest = CONFIG_DIR / "exiftool"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(dest)
    # Inhalt liegt in einem Unterordner exiftool-XX.XX_64
    subs = [p for p in dest.iterdir() if p.is_dir()]
    if len(subs) == 1 and not (dest / "exiftool_files").exists():
        for item in subs[0].iterdir():
            shutil.move(str(item), str(dest / item.name))
        subs[0].rmdir()
    exe = dest / "exiftool.exe"
    for p in dest.glob("exiftool*.exe"):
        if p.name != "exiftool.exe":
            p.rename(exe)
    if not exe.exists():
        raise ExifToolError("exiftool.exe wurde im Download nicht gefunden.")
    return str(exe)


class ExifTool:
    """Dauerhaft laufender ExifTool-Prozess (-stay_open)."""

    def __init__(self, cmd):
        self.cmd = list(cmd)
        self.proc = None
        self._lock = threading.Lock()
        self._errq: queue.Queue = queue.Queue()
        self._n = 0

    def _start(self):
        self.proc = subprocess.Popen(
            self.cmd + ["-stay_open", "True", "-@", "-",
                        "-common_args", "-charset", "filename=UTF8"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, **_popen_flags())
        self._errq = queue.Queue()
        threading.Thread(target=self._drain, args=(self.proc, self._errq),
                         daemon=True).start()

    @staticmethod
    def _drain(proc, q):
        for raw in iter(proc.stderr.readline, b""):
            q.put(raw.decode("utf-8", "replace").rstrip("\r\n"))
        q.put(None)

    def execute(self, args):
        """Führt einen Aufruf aus. Rückgabe: (stdout-Bytes, stderr-Text)."""
        for a in args:
            if "\n" in a or "\r" in a:
                raise ExifToolError("Zeilenumbruch in Argument nicht erlaubt.")
        with self._lock:
            if self.proc is None or self.proc.poll() is not None:
                self._start()
            self._n += 1
            tok = f"{{ready{self._n}}}".encode()
            etok = f"{{fehlerende{self._n}}}"
            payload = "\n".join([*args, "-echo4", etok,
                                 f"-execute{self._n}"]) + "\n"
            try:
                self.proc.stdin.write(payload.encode("utf-8"))
                self.proc.stdin.flush()
            except OSError as e:
                raise ExifToolError(f"ExifTool nicht erreichbar: {e}")
            fd = self.proc.stdout.fileno()
            buf = bytearray()
            while True:
                chunk = os.read(fd, 1 << 16)
                if not chunk:
                    raise ExifToolError("ExifTool wurde unerwartet beendet.")
                buf += chunk
                if bytes(buf[-(len(tok) + 4):]).rstrip(b"\r\n").endswith(tok):
                    break
            out = bytes(buf).rstrip(b"\r\n")[:-len(tok)]
            errs = []
            while True:
                try:
                    line = self._errq.get(timeout=20)
                except queue.Empty:
                    break
                if line is None or line.strip() == etok:
                    break
                errs.append(line)
            return out, "\n".join(errs).strip()

    def close(self):
        with self._lock:
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.stdin.write(b"-stay_open\nFalse\n")
                    self.proc.stdin.flush()
                    self.proc.wait(timeout=5)
                except Exception:
                    self.proc.kill()
            self.proc = None

    # ---- Lesen ------------------------------------------------------------
    def read(self, paths, extra_tags=()) -> dict:
        """Liest Metadaten; Rückgabe {pfad: {Gruppe:Tag: Wert}}"""
        tags = []
        for f in FIELDS:
            tags += [f"-{t}" for t in f.tags]
        tags += [f"-{t}" for t in INFO_TAGS]
        tags += [f"-{t}" for t in extra_tags
                 if re.fullmatch(r"[\w:\-]+", t)]
        result = {}
        paths = list(paths)
        for i in range(0, len(paths), 100):
            chunk = paths[i:i + 100]
            out, _err = self.execute(["-j", "-G1", *tags, *chunk])
            try:
                data = json.loads(out.decode("utf-8", "replace")) if out.strip() else []
            except json.JSONDecodeError:
                data = []
            norm = {os.path.normcase(os.path.normpath(p)): p for p in chunk}
            for rec in data:
                sf = os.path.normcase(os.path.normpath(str(rec.get("SourceFile", ""))))
                if sf in norm:
                    rec.pop("SourceFile", None)
                    result[norm[sf]] = rec
        return result

    def read_merged(self, paths, extra_tags=()) -> dict:
        """Wie read(), bezieht bei RAW-Dateien vorhandene XMP-Sidecars ein
        (Sidecar-Werte haben Vorrang)."""
        paths = list(paths)
        side = {p: sidecar_path(p) for p in paths if is_raw(p)}
        side = {p: s for p, s in side.items() if os.path.isfile(s)}
        raw = self.read(paths + list(side.values()), extra_tags)
        out = {}
        for p in paths:
            rec = dict(raw.get(p, {}))
            s = side.get(p)
            if s and s in raw:
                for k, v in raw[s].items():
                    if k.lower().startswith("xmp"):
                        rec[k] = v
                rec["_sidecar"] = s
            out[p] = rec
        return out

    def af_info(self, path):
        """Fokuspunkte einer Datei (siehe af_points) oder None."""
        out, _err = self.execute(["-j", *[f"-{t}" for t in AF_TAGS], path])
        try:
            data = json.loads(out.decode("utf-8", "replace")) if out.strip() else []
        except json.JSONDecodeError:
            return None
        return af_points(data[0]) if data else None

    # ---- Vorschaubilder ---------------------------------------------------
    def preview(self, path, large=False):
        """Eingebettetes JPEG einer RAW-Datei, plus EXIF-Orientierung (1–8).
        large=True bevorzugt das größte eingebettete Bild (für die Vollansicht)."""
        data = None
        order = (("-JpgFromRaw", "-PreviewImage", "-OtherImage", "-ThumbnailImage")
                 if large else
                 ("-PreviewImage", "-JpgFromRaw", "-ThumbnailImage", "-OtherImage"))
        for tag in order:
            out, _ = self.execute(["-b", tag, path])
            if len(out) > 500 and out[:2] == b"\xff\xd8":
                data = out
                break
        orient = 1
        if data:
            out, _ = self.execute(["-n", "-s3", "-Orientation", path])
            try:
                orient = int(out.strip() or 1)
            except ValueError:
                orient = 1
        return data, orient

    # ---- Schreiben --------------------------------------------------------
    def write(self, path, values: dict, extras=(), kw_mode="replace",
              raw_mode="sidecar", backup=False, list_ops=()):
        """Schreibt values {feldschlüssel: text}, extras [(tag, text)] und
        list_ops [(tag, "+=" | "-=", wert)] für Listen-Tags.
        Rückgabe (ok, meldung)."""
        targets = []
        if is_raw(path):
            if raw_mode in ("sidecar", "both"):
                targets.append((sidecar_path(path), True))
            if raw_mode in ("embed", "both"):
                targets.append((path, False))
        else:
            targets.append((path, False))
        msgs, ok_all = [], True
        for target, xmp_only in targets:
            assigns = build_assignments(values, extras, kw_mode, xmp_only)
            assigns += list_assignments(list_ops, xmp_only)
            if not assigns:
                continue
            args = ["-E"]
            if any(a.startswith("-IPTC:") for a in assigns):
                args.append("-IPTC:CodedCharacterSet=UTF8")
            if not os.path.exists(target):
                # neues Sidecar: nur Zuweisungen mit Inhalt
                assigns = [a for a in assigns if not a.endswith("=")]
                if not assigns:
                    continue
                args += assigns + ["-o", target]
            else:
                if not backup:
                    args.append("-overwrite_original")
                args += assigns + [target]
            out, err = self.execute(args)
            text = out.decode("utf-8", "replace")
            good = re.search(r"\b1 image files (updated|created|unchanged)", text)
            if not good or "due to errors" in text:
                ok_all = False
                msgs.append((err or text).strip() or "Unbekannter Fehler")
            elif err:
                msgs.append(err)
        return ok_all, " | ".join(m.replace("\n", " ") for m in msgs)


def _esc(v: str) -> str:
    v = v.replace("\r\n", "\n").replace("\r", "\n")
    return html.escape(v, quote=False).replace("\n", "&#xa;")


_NON_XMP = {"exif", "iptc", "gps", "makernotes", "jfif", "file"} | _EXIF_GROUPS


def list_assignments(ops, xmp_only=False):
    """[(tag, "+=" | "-=", wert)] -> ExifTool-Zuweisungen (nach den übrigen)."""
    out = []
    for tag, op, val in ops or ():
        grp = tag.split(":")[0].lower() if ":" in tag else ""
        if xmp_only and grp in _NON_XMP:
            continue
        out.append(f"-{tag}{op}{_esc(val)}")
    return out


# --------------------------------------------------------------------------
# Kennzeichnung „mit AeroTagger getaggt“
# --------------------------------------------------------------------------
MARK_KEYWORD = "AeroTagger"
HIER_TAG = "XMP-lr:HierarchicalSubject"
HIER_LABELS = (("reg", "Registrierung"), ("op", "Operator"), ("type", "Typ"))


def _as_list(v):
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)]


def rating_of(meta) -> int:
    """Sternbewertung 0–5 (XMP bevorzugt, sonst EXIF). Abgelehnt (-1) zählt als 0."""
    if not meta:
        return 0
    v = lookup(meta, "XMP:Rating")
    if v is None:
        v = lookup(meta, "Rating")
    try:
        return max(0, min(5, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


_RATING_PERCENT = {0: 0, 1: 1, 2: 25, 3: 50, 4: 75, 5: 99}   # Windows-Konvention


def rating_extras(n: int):
    """Zuweisungen für eine Sternbewertung: XMP (Lightroom, Bridge …) und
    EXIF Rating/RatingPercent (Windows-Explorer). In XMP-Begleitdateien
    landet nur der XMP-Wert."""
    n = max(0, min(5, int(n)))
    return [("XMP-xmp:Rating", str(n)), ("IFD0:Rating", str(n)),
            ("IFD0:RatingPercent", str(_RATING_PERCENT[n]))]


def tag_info(meta):
    """None, wenn das Bild nicht mit AeroTagger getaggt ist, sonst
    {"reg", "op", "type"} (Werte ggf. leer)."""
    if not meta:
        return None
    vals = {}
    for h in _as_list(lookup(meta, HIER_TAG)):
        parts = h.split("|")
        if len(parts) >= 3 and parts[0].strip().lower() == MARK_KEYWORD.lower():
            vals[parts[1].strip().lower()] = "|".join(parts[2:]).strip()
    kws = split_list(field_value(meta, FIELD_BY_KEY["keywords"]))
    marked = any(k.lower() == MARK_KEYWORD.lower() for k in kws)
    if not marked and not vals:
        return None
    return {key: vals.get(label.lower(), "") for key, label in HIER_LABELS}


def tag_ops(meta, reg="", op="", typ=""):
    """Listen-Operationen: Stichwort „AeroTagger“ setzen und die hierarchischen
    Stichwörter AeroTagger|Registrierung|…, |Operator|…, |Typ|… erneuern."""
    ops = []
    for t in FIELD_BY_KEY["keywords"].tags:
        ops += [(t, "-=", MARK_KEYWORD), (t, "+=", MARK_KEYWORD)]
    for h in _as_list(lookup(meta or {}, HIER_TAG)):
        if h.split("|")[0].strip().lower() == MARK_KEYWORD.lower():
            ops.append((HIER_TAG, "-=", h))
    for (_k, label), val in zip(HIER_LABELS, (reg, op, typ)):
        val = (val or "").replace("|", "/").strip()
        if val:
            ops.append((HIER_TAG, "+=", f"{MARK_KEYWORD}|{label}|{val}"))
    return ops


def build_assignments(values, extras=(), kw_mode="replace", xmp_only=False):
    """Erzeugt die ExifTool-Zuweisungen (mit -E maskiert)."""
    args = []
    for key, text in values.items():
        f = FIELD_BY_KEY.get(key)
        if not f:
            continue
        text = text.strip()
        if key == "rating":                 # Sterne: XMP + EXIF Rating/RatingPercent
            try:
                n = int(round(float(text or 0)))
            except ValueError:
                continue
            for tag, val in rating_extras(n):
                if xmp_only and not tag.startswith("XMP"):
                    continue
                args.append(f"-{tag}={val}")
            continue
        for tag in f.tags:
            if xmp_only and not tag.startswith("XMP"):
                continue
            if f.is_list:
                items = split_list(text)
                if not items:
                    if kw_mode == "replace":
                        args.append(f"-{tag}=")
                elif kw_mode == "append":
                    for it in items:   # erst entfernen, dann anfügen = keine Dubletten
                        args.append(f"-{tag}-={_esc(it)}")
                        args.append(f"-{tag}+={_esc(it)}")
                else:
                    args += [f"-{tag}={_esc(it)}" for it in items]
            else:
                args.append(f"-{tag}={_esc(text)}")
    for tag, text in extras:
        grp = tag.split(":")[0].lower() if ":" in tag else ""
        if xmp_only and grp in _NON_XMP:
            continue
        args.append(f"-{tag}={_esc(text.strip())}")
    return args


def parse_extras(text: str):
    """'TAG = Wert' je Zeile -> [(tag, wertvorlage)], fehler[]"""
    out, errors = [], []
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        tag, sep, val = ln.partition("=")
        tag = tag.strip().lstrip("-")
        if not sep or not re.fullmatch(r"[A-Za-z][\w\-]*(:[\w\-]+)*[+\-]?", tag):
            errors.append(ln)
            continue
        out.append((tag, val.strip()))
    return out, errors


# --------------------------------------------------------------------------
# Fokuspunkte (Canon: AFInfo/AFInfo2 und Motivverfolgung der EOS R)
# --------------------------------------------------------------------------
# '#' = Zahlenwert statt Klartext
AF_TAGS = ["Make", "Model", "CameraType#", "AFAreaMode", "NumAFPoints#",
           "AFImageWidth#", "AFImageHeight#", "CanonImageWidth#", "CanonImageHeight#",
           "ExifImageWidth#", "ExifImageHeight#",
           "AFAreaWidths#", "AFAreaHeights#", "AFAreaWidth#", "AFAreaHeight#",
           "AFAreaXPositions#", "AFAreaYPositions#",
           "AFPointsInFocus#", "AFPointsSelected#", "Orientation#",
           # Seitenverhältnis-Beschnitt (1:1, 4:3, 16:9 im Kameramenü)
           "CroppedImageWidth#", "CroppedImageHeight#", "CroppedImageLeft#", "CroppedImageTop#",
           # Motivverfolgung: R1, R5 Mark II, R6 Mark III, R8 Mark II …
           "AFTrackingArea#", "AFDetectedSubject", "AFTrackingTarget", "AFEyeUsed",
           # … und als Verlauf: R3, R5, R6, R6 Mark II, R8, R50, R7, R10
           "AFTrackingHistory"]

AF_INACTIVE, AF_SELECTED, AF_FOCUS = 0, 1, 2

_AF_SUBJECT = {"person": "Person", "animal (cat)": "Tier (Katze)",
               "animal (dog or bird)": "Tier (Hund/Vogel)", "animal (horse)": "Tier (Pferd)",
               "vehicle": "Fahrzeug"}
_AF_TARGET = {"head": "Kopf", "body": "Körper", "face": "Gesicht", "eye": "Auge"}
_AF_EYE = {"left": "linkes Auge", "right": "rechtes Auge"}


def _nums(v) -> list:
    if v is None or v == "":
        return []
    if isinstance(v, (list, tuple)):
        v = " ".join(str(x) for x in v)
    out = []
    for x in str(v).replace(",", " ").split():
        try:
            out.append(int(float(x)))
        except ValueError:
            pass
    return out


def _bits(v) -> set:
    """Bitmaske aus 16-Bit-Wörtern („8192 0 0“) → Menge der Punktnummern."""
    found = set()
    for k, word in enumerate(_nums(v)):
        word &= 0xFFFF
        for j in range(16):
            if word >> j & 1:
                found.add(k * 16 + j)
    return found


def _orient_box(cx, cy, w, h, orient):
    """Rechnet ein Feld (normiert 0–1, Sensorlage) in die gedrehte Bildlage um –
    genauso wie die Vorschau gedreht wird (erst spiegeln, dann im Uhrzeigersinn drehen)."""
    rot, mirror = {3: (180, False), 6: (90, False), 8: (270, False), 2: (0, True),
                   4: (180, True), 5: (90, True), 7: (270, True)}.get(orient, (0, False))
    if mirror:
        cx = 1 - cx
    if rot == 90:
        cx, cy, w, h = 1 - cy, cx, h, w
    elif rot == 180:
        cx, cy = 1 - cx, 1 - cy
    elif rot == 270:
        cx, cy, w, h = cy, 1 - cx, h, w
    return cx, cy, w, h


def _af_tracking(meta, iw, ih):
    """Motivverfolgung → {"box": (cx, cy, w, h) | None, "pt": (cx, cy) | None,
    "label": text} normiert auf das AF-Bild, oder None."""
    sub = _AF_SUBJECT.get(str(meta.get("AFDetectedSubject", "")).strip().lower(), "")
    tgt = str(meta.get("AFTrackingTarget", "")).strip().lower()
    eye = _AF_EYE.get(str(meta.get("AFEyeUsed", "")).strip().lower(), "")
    box = pt = None
    area = _nums(meta.get("AFTrackingArea"))          # Mitte X, Mitte Y, Breite, Höhe; 0,0 = links oben
    if len(area) == 4 and area[2] > 0 and area[3] > 0:
        box = (area[0] / iw, area[1] / ih, area[2] / iw, area[3] / ih)
    else:
        hist = meta.get("AFTrackingHistory")
        if isinstance(hist, str):
            hist = [hist]
        for rec in hist or []:                         # neuester Eintrag zuerst
            rec = str(rec)
            m = re.search(r"(\d+)x(\d+) at \((\d+) (\d+)\)", rec)
            if m:
                w, h, x, y = map(int, m.groups())
                if w > 0 and h > 0:
                    box = (x / iw, y / ih, w / iw, h / ih)
                    t = re.search(r"ms: ([A-Za-z]+) \d+x\d+", rec)
                    if t and not tgt:
                        tgt = t.group(1).lower()
                    break
            m = re.search(r"raw centre ([+-]?\d+) ([+-]?\d+)", rec)
            if m:                                      # R7/R10: nur der Mittelpunkt
                x, y = map(int, m.groups())
                pt = (0.5 + x / iw, 0.5 + y / ih)
                break
    if box is None and pt is None:
        return None
    if box and not (-0.05 <= box[0] <= 1.05 and -0.05 <= box[1] <= 1.05):
        return None
    if pt and not (0 <= pt[0] <= 1 and 0 <= pt[1] <= 1):
        return None
    parts = [x for x in (sub, _AF_TARGET.get(tgt, ""), eye) if x]
    return {"box": box, "pt": pt, "label": "Verfolgt" + (": " + " · ".join(parts) if parts else "")}


def af_points(meta: dict):
    """Wertet die Canon-Fokusdaten eines ExifTool-Datensatzes (AF_TAGS, ohne -G) aus.
    Rückgabe None (keine Daten) oder ein Datensatz in Sensorlage (normiert 0–1),
    den af_layout() in die Lage des angezeigten Bildes umrechnet."""
    if not meta or "canon" not in str(meta.get("Make", "")).lower():
        return None
    model = str(meta.get("Model", "")).lower()
    # Bildgröße im AF-Koordinatensystem (wie digiKam / FocusPoints)
    if model.endswith("eos 5d"):
        iw, ih = meta.get("CanonImageWidth"), meta.get("CanonImageHeight")
    else:
        iw, ih = meta.get("AFImageWidth"), meta.get("AFImageHeight")
    iw = _nums(iw or meta.get("ExifImageWidth"))
    ih = _nums(ih or meta.get("ExifImageHeight"))
    if not iw or not ih or iw[0] <= 0 or ih[0] <= 0:
        return None
    iw, ih = iw[0], ih[0]
    xs, ys = _nums(meta.get("AFAreaXPositions")), _nums(meta.get("AFAreaYPositions"))
    n = min(len(xs), len(ys))
    ws = _nums(meta.get("AFAreaWidths")) or _nums(meta.get("AFAreaWidth")) * n
    hs = _nums(meta.get("AFAreaHeights")) or _nums(meta.get("AFAreaHeight")) * n or ws
    # Richtung der Y-Achse hängt vom Kameratyp ab („EOS High-end“ 248, „Compact“ 250;
    # alle EOS R melden 248)
    ydir = -1 if _nums(meta.get("CameraType"))[:1] in ([248], [250]) else 1
    focus = _bits(meta.get("AFPointsInFocus"))
    selected = _bits(meta.get("AFPointsSelected")) - focus
    raw = []
    for i in range(n):
        w = ws[i] if i < len(ws) else 0
        h = hs[i] if i < len(hs) else w
        if w <= 0 or h <= 0:
            continue                       # ungenutzter Eintrag (z. B. EOS R mit 1 Feld)
        state = AF_FOCUS if i in focus else AF_SELECTED if i in selected else AF_INACTIVE
        raw.append((xs[i] / iw, ys[i] / ih, w / iw, h / ih, state))
    track = _af_tracking(meta, iw, ih)
    # Gegenprobe: liegt das aktive AF-Feld nur mit gespiegelter Y-Achse auf dem
    # verfolgten Motiv, gilt für dieses Modell die andere Richtung
    if track and track["box"] and raw:
        act = [r for r in raw if r[4] != AF_INACTIVE]
        if len(act) == 1:
            tx, ty = track["box"][0], track["box"][1]
            ax, ay = 0.5 + act[0][0], act[0][1]
            d_now = abs(ax - tx) + abs(0.5 + ay * ydir - ty)
            d_flip = abs(ax - tx) + abs(0.5 - ay * ydir - ty)
            if d_flip < 0.06 and d_now > 0.12:
                ydir = -ydir
    pts = []
    for x, y, w, h, state in raw:
        cx, cy = 0.5 + x, 0.5 + y * ydir
        if -0.1 <= cx <= 1.1 and -0.1 <= cy <= 1.1:
            pts.append((cx, cy, w, h, state))
    if not pts and not track:
        return None
    crop = None
    c = [(_nums(meta.get(k)) or [0])[0] for k in
         ("CroppedImageLeft", "CroppedImageTop", "CroppedImageWidth", "CroppedImageHeight")]
    if c[2] > 0 and c[3] > 0 and (c[2], c[3]) != (iw, ih) \
            and c[0] + c[2] <= iw * 1.02 and c[1] + c[3] <= ih * 1.02:
        crop = (c[0] / iw, c[1] / ih, c[2] / iw, c[3] / ih)
    return {"mode": str(meta.get("AFAreaMode", "") or ""), "points": pts, "track": track,
            "orient": (_nums(meta.get("Orientation")) or [1])[0], "crop": crop,
            "aspect": iw / ih}


def af_layout(info, shown_aspect=None):
    """Rechnet af_points() in die Lage des angezeigten Bildes um (Drehung, und
    Beschnitt, wenn das Bild das Seitenverhältnis des Beschnitts hat).
    Rückgabe (punkte [(cx, cy, w, h, zustand)], verfolgung {"box", "pt", "label"} | None)."""
    orient = info.get("orient", 1)
    crop = info.get("crop")
    if crop and shown_aspect:
        a = shown_aspect if orient not in (5, 6, 7, 8) else 1 / shown_aspect
        ca = crop[2] / crop[3] * info.get("aspect", 1.5)
        if abs(a - ca) + 0.01 >= abs(a - info.get("aspect", 1.5)):
            crop = None                    # Bild zeigt den ganzen Sensor
    else:
        crop = None

    def tf(cx, cy, w, h):
        if crop:
            cx, cy = (cx - crop[0]) / crop[2], (cy - crop[1]) / crop[3]
            w, h = w / crop[2], h / crop[3]
        return _orient_box(cx, cy, w, h, orient)

    pts = [(*tf(*p[:4]), p[4]) for p in info.get("points", [])]
    track = info.get("track")
    if track:
        track = dict(track)
        if track.get("box"):
            track["box"] = tf(*track["box"])
        if track.get("pt"):
            track["pt"] = tf(*track["pt"], 0, 0)[:2]
    return pts, track


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------
def read_csv_rows(path) -> list:
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("latin-1")
    first = text.split("\n", 1)[0]
    delim = max((";", ",", "\t", "|"), key=first.count)
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return [[c.strip() for c in r] for r in rows if any(c.strip() for c in r)]


class CodeTable:
    """Kürzel-Tabelle: Spalte 1 = Kürzel, Spalte 2 ff. = Ersetzungen.
    Verwendung im Text: =kürzel=  bzw. =kürzel#3= für Spalte 3."""

    def __init__(self, path=None):
        self.path = path
        self.codes = {}
        if path:
            for r in read_csv_rows(path):
                if r[0].startswith("#") or len(r) < 2:
                    continue
                self.codes[r[0]] = r
                self.codes.setdefault(r[0].lower(), r)

    def __len__(self):
        return len({id(v) for v in self.codes.values()})

    def get(self, code, col=2):
        row = self.codes.get(code) or self.codes.get(code.lower())
        if row is None or col < 2 or col > len(row):
            return None
        return row[col - 1]


class AircraftTable:
    """AircraftTags-CSV: Kopfzeile, eine Spalte mit der Registrierung.
    Zeilen, die mit # beginnen, werden übersprungen. Die Suche ignoriert
    Groß-/Kleinschreibung, Bindestriche und Leerzeichen (OE-LBA = oelba)."""
    KEY_NAMES = ("registration", "registrierung", "reg", "kennzeichen",
                 "tail", "tailnumber", "tail number", "immatriculation",
                 "kennung", "luftfahrzeugkennzeichen")

    def __init__(self, path=None, key_column=None):
        self.path = path
        self.columns, self.rows = [], []
        self.key_column = None
        self._index = {}
        if path:
            rows = [r for r in read_csv_rows(path) if not r[0].startswith("#")]
            if rows:
                self.columns = rows[0]
                n = len(self.columns)
                self.rows = [tuple((r + [""] * n)[:n]) for r in rows[1:]]
            self.set_key(key_column)

    def __len__(self):
        return len(self.rows)

    @staticmethod
    def norm(reg: str) -> str:
        return re.sub(r"[^A-Z0-9]", "", (reg or "").upper())

    def guess_key(self):
        for c in self.columns:
            if c.strip().lower() in self.KEY_NAMES:
                return c
        return self.columns[0] if self.columns else None

    def set_key(self, col=None):
        if col not in self.columns:
            col = self.guess_key()
        self.key_column = col
        self._index = {}
        if col:
            i = self.columns.index(col)
            for n, r in enumerate(self.rows):
                k = self.norm(r[i])
                if k:
                    self._index.setdefault(k, n)

    def column(self, name):
        for c in self.columns:
            if c.lower() == name.strip().lower():
                return c
        return None

    def find(self, reg):
        """Datensatz als dict {Spalte: Wert} oder None."""
        n = self._index.get(self.norm(reg))
        return dict(zip(self.columns, self.rows[n])) if n is not None else None

    def registrations(self):
        if not self.key_column:
            return []
        i = self.columns.index(self.key_column)
        return [r[i] for r in self.rows if r[i]]

    def find_in_text(self, text):
        """Erste bekannte Registrierung in einem Text (z. B. Stichwörtern)."""
        if not self.key_column:
            return None
        i = self.columns.index(self.key_column)
        for tok in re.split(r"[\s,;/()\[\]\"„“]+", text or ""):
            tok = tok.strip(".:!?'")
            k = self.norm(tok)
            n = self._index.get(k)
            if n is None or len(k) < 3:
                continue
            reg = self.rows[n][i]
            # genau so geschrieben (z. B. „14+06“) – oder ohne Bindestrich, dann
            # aber nur bei Kennzeichen mit Buchstaben; rein numerische Kennungen
            # würden sonst auf Datums- und Zeitangaben passen („14.06.“).
            if tok.upper() == reg.upper() or re.search(r"[A-Z]", k):
                return reg
        return None


# --------------------------------------------------------------------------
# Online-Abfrage adsbdb.com (Ersatz: hexdb.io) + lokaler Cache
# --------------------------------------------------------------------------
ADSBDB_URL = "https://api.adsbdb.com/v0/aircraft/"
HEXDB_URL = "https://hexdb.io/api/v2/aircraft?registration="
ONLINE_COLUMNS = ["Registration", "Type", "Manufacturer", "Model", "ICAO-Typ",
                  "Airline", "Operator-ICAO", "Country", "CountryCode", "ModeS",
                  "PhotoURL", "Abgefragt", "Quelle"]


class OnlineError(Exception):
    pass


def _type_name(manu, model):
    return (model if (not manu or model.lower().startswith(manu.lower()))
            else f"{manu} {model}").strip()


def adsbdb_record(ac: dict) -> dict:
    """Antwort von adsbdb.com -> Datensatz mit den Spalten ONLINE_COLUMNS."""
    def g(k):
        return str(ac.get(k) or "").strip()
    manu, model = g("manufacturer"), g("type")
    return {
        "Registration": g("registration").upper(),
        "Type": _type_name(manu, model),
        "Manufacturer": manu,
        "Model": model,
        "ICAO-Typ": g("icao_type"),
        "Airline": g("registered_owner"),
        "Operator-ICAO": g("registered_owner_operator_flag_code"),
        "Country": g("registered_owner_country_name"),
        "CountryCode": g("registered_owner_country_iso_name"),
        "ModeS": g("mode_s").upper(),
        "PhotoURL": g("url_photo"),
        "Abgefragt": dt.date.today().isoformat(),
        "Quelle": "adsbdb.com",
    }


def hexdb_record(ac: dict) -> dict:
    """Antwort von hexdb.io (v2) -> Datensatz mit den Spalten ONLINE_COLUMNS.
    hexdb.io liefert kein Registrierungsland."""
    def g(k):
        return str(ac.get(k) or "").strip()
    manu, model = g("manufacturer"), g("type")
    img = ac.get("images") if isinstance(ac.get("images"), dict) else {}
    return {
        "Registration": g("registration").upper(),
        "Type": _type_name(manu, model),
        "Manufacturer": manu,
        "Model": model,
        "ICAO-Typ": g("icao_type_code"),
        "Airline": g("registered_owner"),
        "Operator-ICAO": g("operator_flag_code"),
        "Country": "",
        "CountryCode": "",
        "ModeS": g("hex").upper(),
        "PhotoURL": str(img.get("full") or "").strip(),
        "Abgefragt": dt.date.today().isoformat(),
        "Quelle": "hexdb.io",
    }


def _get_json(url, service, timeout):
    """GET -> JSON; 400/404 -> None; sonst OnlineError mit Dienstnamen."""
    req = urllib.request.Request(url, headers={
        "User-Agent": f"{APP_NAME}/{APP_VERSION}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        if e.code in (400, 404):
            return None
        if e.code == 429:
            raise OnlineError(f"{service}: zu viele Abfragen in kurzer Zeit – bitte etwas warten.")
        raise OnlineError(f"{service} antwortet mit HTTP {e.code}.")
    except urllib.error.URLError as e:
        raise OnlineError(f"Keine Verbindung zu {service} ({e.reason}).")
    except (TimeoutError, OSError) as e:
        raise OnlineError(f"Keine Antwort von {service} ({e}).")
    except ValueError:
        raise OnlineError(f"Ungültige Antwort von {service}.")


def fetch_adsbdb(query: str, timeout=12):
    """Fragt adsbdb.com nach Registrierung (oder Mode-S-Hexcode) ab.
    Rückgabe: Datensatz-dict, None (unbekannt) oder OnlineError."""
    q = urllib.parse.quote(query.strip().upper(), safe="")
    if not q:
        return None
    data = _get_json(ADSBDB_URL + q, "adsbdb.com", timeout)
    resp = data.get("response") if isinstance(data, dict) else None
    ac = resp.get("aircraft") if isinstance(resp, dict) else None
    if not isinstance(ac, dict) or not ac.get("registration"):
        return None
    return adsbdb_record(ac)


def fetch_hexdb(query: str, timeout=12):
    """Fragt hexdb.io nach der Registrierung ab: HEXDB_URL + Registrierung.
    Liefert hexdb.io mehrere Flugzeuge (Kennzeichen wiederverwendet), wird das
    passende genommen, sonst das erste."""
    reg = query.strip().upper()
    if not reg:
        return None
    data = _get_json(HEXDB_URL + urllib.parse.quote(reg, safe=""), "hexdb.io", timeout)
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return None
    hits = [r for r in results if isinstance(r, dict) and r.get("registration")]
    if not hits:
        return None
    k = AircraftTable.norm(reg)
    best = next((r for r in hits if AircraftTable.norm(r["registration"]) == k), hits[0])
    return hexdb_record(best)


def fetch_online(query: str, timeout=12):
    """adsbdb.com, ersatzweise hexdb.io. Rückgabe: Datensatz oder None
    (bei beiden unbekannt). Fehler nur, wenn kein Dienst ein Ergebnis liefert
    und mindestens einer nicht erreichbar war."""
    err1 = None
    try:
        rec = fetch_adsbdb(query, timeout)
        if rec:
            return rec
    except OnlineError as e:
        err1 = str(e)
    try:
        rec = fetch_hexdb(query, timeout)
    except OnlineError as e:
        raise OnlineError(f"{err1} {e}" if err1 else str(e))
    if rec:
        return rec
    if err1:
        raise OnlineError(f"{err1} hexdb.io kennt die Registrierung nicht.")
    return None


class AircraftCache:
    """Lokale Cache-Tabelle der Online-Abfragen als CSV (Semikolon, UTF-8),
    lässt sich in Excel ansehen und bearbeiten."""

    def __init__(self, path):
        self.file = Path(path)
        self.table = AircraftTable()
        if self.file.is_file():
            try:
                self.table = AircraftTable(str(self.file), "Registration")
            except Exception:
                self.table = AircraftTable()
        if not self.table.columns:
            self.table.columns = list(ONLINE_COLUMNS)
            self.table.set_key("Registration")
        self.table.path = str(self.file)
        self._index_modes()

    def __len__(self):
        return len(self.table)

    @property
    def columns(self):
        return self.table.columns

    def _index_modes(self):
        self._modes = {}
        col = self.table.column("ModeS")
        if col:
            i = self.table.columns.index(col)
            for n, r in enumerate(self.table.rows):
                if r[i]:
                    self._modes.setdefault(AircraftTable.norm(r[i]), n)

    def find(self, reg):
        rec = self.table.find(reg)
        if rec is None:
            n = self._modes.get(AircraftTable.norm(reg))
            if n is not None:
                rec = dict(zip(self.table.columns, self.table.rows[n]))
        return rec

    def find_in_text(self, text):
        return self.table.find_in_text(text)

    def registrations(self):
        return self.table.registrations()

    def add(self, rec: dict) -> bool:
        t = self.table
        new_cols = [c for c in rec if c not in t.columns]
        if new_cols:
            t.columns = t.columns + new_cols
            t.rows = [r + ("",) * len(new_cols) for r in t.rows]
        row = tuple(rec.get(c, "") for c in t.columns)
        n = t._index.get(AircraftTable.norm(rec.get("Registration", "")))
        if n is None:
            t.rows.append(row)
        else:
            t.rows[n] = row
        t.set_key(t.key_column or "Registration")
        self._index_modes()
        return self.save()

    def clear(self) -> bool:
        self.table.rows = []
        self.table.set_key("Registration")
        self._index_modes()
        return self.save()

    def save(self) -> bool:
        try:
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(self.table.columns)
                w.writerows(self.table.rows)
            os.replace(tmp, self.file)
            return True
        except OSError:
            return False


class DataTable:
    """Datentabelle mit Kopfzeile; eine Schlüsselspalte enthält den Dateinamen
    (mit oder ohne Endung). Verwendung: {csv:Spaltenname}"""

    def __init__(self, path=None, key_column=None):
        self.path = path
        self.columns, self.rows = [], []
        self.key_column = None
        self._index = {}
        if path:
            rows = read_csv_rows(path)
            if rows:
                self.columns = rows[0]
                for r in rows[1:]:
                    r = r + [""] * (len(self.columns) - len(r))
                    self.rows.append(dict(zip(self.columns, r)))
            self.set_key(key_column)

    def set_key(self, col=None):
        if col not in self.columns:
            col = self.columns[0] if self.columns else None
        self.key_column = col
        self._index = {}
        if col:
            for r in self.rows:
                k = r[col].strip().lower()
                if k:
                    self._index.setdefault(k, r)

    def row_for(self, path):
        p = Path(path)
        return (self._index.get(p.name.lower())
                or self._index.get(p.stem.lower()))

    def column(self, name):
        for c in self.columns:
            if c.lower() == name.lower():
                return c
        return None


# --------------------------------------------------------------------------
# Variablen
# --------------------------------------------------------------------------
MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
DAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag",
        "Sonntag"]

VARIABLES = [
    ("Datei", [
        ("{filename}", "Dateiname mit Endung"),
        ("{filenamebase}", "Dateiname ohne Endung"),
        ("{extension}", "Endung"),
        ("{folder}", "Name des Ordners"),
        ("{folderpath}", "vollständiger Ordnerpfad"),
        ("{path}", "vollständiger Dateipfad"),
        ("{frame}", "Bildnummer (Ziffern am Ende des Dateinamens)"),
    ]),
    ("Aufnahmedatum", [
        ("{date}", "Datum, z. B. 10.11.2026"),
        ("{isodate}", "Datum, z. B. 2026-11-10"),
        ("{time}", "Uhrzeit, z. B. 18:13:05"),
        ("{year4}", "Jahr vierstellig"), ("{year2}", "Jahr zweistellig"),
        ("{month2}", "Monat zweistellig"), ("{day2}", "Tag zweistellig"),
        ("{monthname}", "Monatsname"), ("{dayname}", "Wochentag"),
        ("{hour24}", "Stunde"), ("{minute}", "Minute"), ("{second}", "Sekunde"),
        ("{date:%d. %B %Y}", "eigenes Format (strftime)"),
        ("{today}", "heutiges Datum"),
    ]),
    ("Kamera", [
        ("{make}", "Hersteller"), ("{model}", "Kameramodell"),
        ("{lens}", "Objektiv"), ("{serial}", "Seriennummer"),
        ("{focallength}", "Brennweite"), ("{aperture}", "Blende"),
        ("{shutter}", "Belichtungszeit"), ("{iso}", "ISO"),
        ("{width}", "Bildbreite"), ("{height}", "Bildhöhe"),
    ]),
    ("Zähler", [
        ("{seq}", "laufende Nummer in der Auswahl"),
        ("{seq:3}", "laufende Nummer, dreistellig"),
        ("{count}", "Anzahl ausgewählter Bilder"),
    ]),
    ("Vorhandene Metadaten", [(f"{{{f.key}}}", f.label) for f in FIELDS]),
    ("CSV und ExifTool", [
        ("{csv:Spalte}", "Wert aus der Daten-CSV (Zeile des Bildes)"),
        ("=kürzel=", "Ersetzung aus der Kürzel-CSV (Spalte 2)"),
        ("=kürzel#3=", "Ersetzung aus Spalte 3 der Kürzel-CSV"),
        ("{tag:XMP-dc:Title}", "beliebiger ExifTool-Tag"),
        ("{ac}", "Registrierung aus dem Reiter AircraftTag"),
        ("{ac:Spalte}", "Wert aus der AircraftTags-CSV"),
        ("{airport}", "Airport aus dem Reiter AircraftTag"),
        ("{fotograf}", "Fotograf aus dem Reiter AircraftTag"),
        ("{aufnahme}", "Aufnahmedatum aus dem Reiter AircraftTag"),
        ("{aufnahme:%d. %B %Y}", "Aufnahmedatum, eigenes Format (nur automatisch aus EXIF)"),
    ]),
    ("Zusätze", [
        ("{city|upper}", "GROSSBUCHSTABEN"),
        ("{city|lower}", "kleinbuchstaben"),
        ("{filenamebase|title}", "Wortanfänge groß"),
        ("{city?unbekannt}", "Ersatztext, falls leer"),
    ]),
]

_VAR_RE = re.compile(r"\{([^{}\n]+)\}")
_CODE_RE = re.compile(r"=([^=\s{}#][^={}\n#]*?)(?:#(\d+))?=")
_INFO_VARS = {
    "make": ("Make",), "model": ("Model",),
    "lens": ("LensModel", "LensID", "Lens"), "serial": ("SerialNumber",),
    "focallength": ("FocalLength",), "aperture": ("FNumber",),
    "shutter": ("ExposureTime",), "iso": ("ISO",),
    "width": ("ImageWidth",), "height": ("ImageHeight",),
}


def parse_date(meta):
    for tag in ("DateTimeOriginal", "CreateDate", "FileModifyDate"):
        v = lookup(meta, tag)
        if v:
            m = re.match(r"(\d{4})[:\-](\d\d)[:\-](\d\d)[ T](\d\d):(\d\d):(\d\d)", str(v))
            if m:
                try:
                    return dt.datetime(*map(int, m.groups()))
                except ValueError:
                    pass
    return None


def _fmt_date(d: dt.datetime, fmt: str) -> str:
    fmt = fmt.replace("%B", MONTHS[d.month - 1]).replace("%A", DAYS[d.weekday()])
    fmt = fmt.replace("%b", MONTHS[d.month - 1][:3]).replace("%a", DAYS[d.weekday()][:2])
    return d.strftime(fmt)


def template_tags(texts) -> set:
    """Alle über {tag:…} angeforderten ExifTool-Tags."""
    tags = set()
    for t in texts:
        for m in _VAR_RE.finditer(t or ""):
            body = m.group(1).split("|")[0].split("?")[0].strip()
            if body.lower().startswith("tag:"):
                tags.add(body[4:].strip())
    return tags


class Context:
    """Alles, was zum Auflösen der Variablen für EINE Datei nötig ist."""

    def __init__(self, path, meta=None, index=0, total=1, seq_start=1,
                 codes: CodeTable = None, data: DataTable = None,
                 aircraft: dict = None, ac_columns=(), ac_key=None, ac_vars=None):
        self.path = Path(path)
        self.meta = meta or {}
        self.aircraft = aircraft          # Datensatz aus AircraftTags oder None
        self.ac_columns = list(ac_columns or (aircraft or {}).keys())
        self.ac_key = ac_key
        # Aufnahmedaten aus dem Reiter AircraftTag; aufnahme=None -> aus EXIF
        self.ac_vars = ac_vars or {}
        self.index, self.total, self.seq_start = index, total, seq_start
        self.codes = codes or CodeTable()
        self.data = data or DataTable()
        self.date = parse_date(self.meta)

    def value(self, name: str, arg: str):
        """Wert einer Variablen oder None, wenn unbekannt."""
        n = name.lower()
        p, d = self.path, self.date
        if n == "filename":
            return p.name
        if n == "filenamebase":
            return p.stem
        if n == "extension":
            return p.suffix.lstrip(".")
        if n == "folder":
            return p.parent.name
        if n == "folderpath":
            return str(p.parent)
        if n == "path":
            return str(p)
        if n == "frame":
            m = re.search(r"(\d+)\D*$", p.stem)
            return m.group(1) if m else ""
        if n == "seq":
            num = self.seq_start + self.index
            return str(num).zfill(int(arg)) if arg.isdigit() else str(num)
        if n == "count":
            return str(self.total)
        if n == "today":
            return _fmt_date(dt.datetime.now(), arg or "%d.%m.%Y")
        if n in ("date", "isodate", "time", "year4", "year2", "month2", "day2",
                 "monthname", "dayname", "hour24", "minute", "second"):
            if d is None:
                return ""
            fmt = {"date": arg or "%d.%m.%Y", "isodate": "%Y-%m-%d",
                   "time": "%H:%M:%S", "year4": "%Y", "year2": "%y",
                   "month2": "%m", "day2": "%d", "monthname": "%B",
                   "dayname": "%A", "hour24": "%H", "minute": "%M",
                   "second": "%S"}[n]
            return _fmt_date(d, fmt)
        if n in _INFO_VARS:
            for t in _INFO_VARS[n]:
                v = lookup(self.meta, t)
                if v is not None:
                    return _to_text(v)
            return ""
        if n in FIELD_BY_KEY:
            return field_value(self.meta, FIELD_BY_KEY[n])
        if n == "csv":
            col = self.data.column(arg)
            if col is None:
                return None
            row = self.data.row_for(self.path)
            return row[col] if row else ""
        if n == "tag":
            return _to_text(lookup(self.meta, arg))
        if n in ("airport", "fotograf"):
            return self.ac_vars.get(n, "")
        if n == "aufnahme":
            v = self.ac_vars.get("aufnahme")
            if v is None:
                return _fmt_date(self.date, arg or "%d.%m.%Y") if self.date else ""
            return v
        if n == "ac":
            cols = self.ac_columns
            if not arg:   # {ac} = Registrierung
                if not self.aircraft:
                    return ""
                return (self.aircraft.get(self.ac_key) or self.aircraft.get("Registration")
                        or next(iter(self.aircraft.values()), ""))
            col = next((c for c in cols if c.lower() == arg.lower()), None)
            if col is None:
                return None
            return (self.aircraft or {}).get(col, "")
        return None

    def resolve(self, template: str):
        """Löst Kürzel und Variablen auf. Rückgabe (text, warnungen[])."""
        warnings = []

        def code_sub(m):
            col = int(m.group(2)) if m.group(2) else 2
            rep = self.codes.get(m.group(1).strip(), col)
            if rep is None:
                if len(self.codes):
                    warnings.append(f"Kürzel {m.group(0)} nicht gefunden")
                return m.group(0)
            return rep

        def var_sub(m):
            body = m.group(1)
            parts = body.split("|")
            head, mods = parts[0], [x.strip().lower() for x in parts[1:]]
            head, qm, fallback = head.partition("?")
            name, _, arg = head.strip().partition(":")
            val = self.value(name.strip(), arg.strip())
            if val is None:
                warnings.append(f"Unbekannte Variable {m.group(0)}")
                return m.group(0)
            if val == "" and qm:
                val = fallback
            for mod in mods:
                if mod == "upper":
                    val = val.upper()
                elif mod == "lower":
                    val = val.lower()
                elif mod == "title":
                    val = val.title()
                elif mod == "trim":
                    val = val.strip()
                else:
                    warnings.append(f"Unbekannter Zusatz |{mod}")
            return val

        text = _CODE_RE.sub(code_sub, template or "")
        text = _VAR_RE.sub(var_sub, text)
        return text, warnings


def list_images(folder, recursive=False) -> list:
    out = []
    try:
        if recursive:
            for root, dirs, files in os.walk(folder):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for fn in sorted(files, key=str.lower):
                    if not fn.startswith(".") and is_supported(fn):
                        out.append(os.path.join(root, fn))
        else:
            with os.scandir(folder) as it:
                for e in it:
                    if e.is_file() and not e.name.startswith(".") and is_supported(e.name):
                        out.append(e.path)
            out.sort(key=lambda s: os.path.basename(s).lower())
    except OSError:
        pass
    return out
