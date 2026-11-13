"""Update über GitHub-Releases (ohne Qt, damit es sich einzeln testen lässt).

Ablauf: latest_release() fragt das neueste Release ab, download() lädt die passende
Datei, install_source() bzw. install_frozen() spielen sie ein.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from . import core

API = os.environ.get("AEROTAGGER_GITHUB_API", "https://api.github.com")
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "aerotagger" / "resources"
REPO_FILE = RES_DIR / "github_repo.txt"        # schreibt publish_github.bat
# beim Einspielen des Quellcodes nie überschreiben
SKIP = {".git", ".venv", ".venv-build", "build", "dist", "__pycache__"}


class UpdateError(Exception):
    pass


def default_repo() -> str:
    try:
        return REPO_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def parse_version(s) -> tuple:
    nums = re.findall(r"\d+", str(s or ""))
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_newer(remote, local=core.APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def _request(url, token="", accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={
        "Accept": accept, "User-Agent": f"{core.APP_NAME}/{core.APP_VERSION}",
        "X-GitHub-Api-Version": "2022-11-28"})
    if token:
        # nicht an Weiterleitungen (Download-Server) mitschicken, die lehnen das ab
        req.add_unredirected_header("Authorization", f"Bearer {token}")
    return req


def latest_release(repo: str, token: str = "", timeout=15) -> dict:
    repo = repo.strip().strip("/")
    if repo.startswith("https://github.com/"):
        repo = repo[len("https://github.com/"):].removesuffix(".git")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise UpdateError("Kein GitHub-Repository eingestellt (Form: benutzer/AeroTagger).")
    try:
        with urllib.request.urlopen(_request(f"{API}/repos/{repo}/releases/latest", token),
                                    timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpdateError(
                f"Kein Release in {repo} gefunden.\n\nEntweder wurde noch kein Release "
                "veröffentlicht, oder das Repository ist privat – dann braucht AeroTagger "
                "einen GitHub-Token (Einstellungen).") from None
        if e.code in (401, 403):
            raise UpdateError(f"GitHub verweigert den Zugriff ({e.code}). "
                              "Ist der Token gültig und für dieses Repository freigegeben?") from None
        raise UpdateError(f"GitHub antwortet mit Fehler {e.code}.") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise UpdateError(f"GitHub ist nicht erreichbar: {getattr(e, 'reason', e)}") from None
    tag = data.get("tag_name") or ""
    return {
        "repo": repo, "tag": tag, "version": ".".join(map(str, parse_version(tag))),
        "name": data.get("name") or tag, "notes": (data.get("body") or "").strip(),
        "url": data.get("html_url") or f"https://github.com/{repo}/releases",
        "zipball": data.get("zipball_url") or f"{API}/repos/{repo}/zipball/{tag}",
        "assets": [{"name": a.get("name", ""), "url": a.get("url", ""),
                    "size": a.get("size", 0)} for a in data.get("assets") or []],
    }


def windows_asset(rel: dict):
    for a in rel["assets"]:
        if re.fullmatch(r"AeroTagger-.*-windows\.zip", a["name"], re.I):
            return a
    return None


def plan(rel: dict, frozen=None, platform=None):
    """Was lässt sich einspielen? → ("source"|"frozen", url, größe) oder (None, grund)."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    platform = platform or sys.platform
    if not frozen:
        if (core.APP_DIR / ".git").exists():
            return None, ("Dieser Ordner ist ein Git-Arbeitsordner. Hier aktualisierst du mit "
                          "„git pull“ bzw. publish_github.bat, nicht über die Update-Funktion.")
        return "source", rel["zipball"], 0
    if platform != "win32":
        return None, "Für diese Installation gibt es kein automatisches Update."
    a = windows_asset(rel)
    if not a:
        return None, ("Das Release enthält keine Windows-Zip (AeroTagger-…-windows.zip). "
                      "Bitte auf der Release-Seite nachsehen.")
    return "frozen", a["url"], a["size"]


def download(url, dest: Path, token="", progress=None, cancelled=None, timeout=30):
    """Lädt url nach dest. progress(geladen, gesamt); cancelled() → True bricht ab."""
    accept = "application/octet-stream" if "/releases/assets/" in url else "*/*"
    try:
        with urllib.request.urlopen(_request(url, token, accept), timeout=timeout) as r, \
                open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if cancelled and cancelled():
                    raise UpdateError("Abgebrochen.")
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except urllib.error.HTTPError as e:
        raise UpdateError(f"Download fehlgeschlagen (Fehler {e.code}).") from None
    except (urllib.error.URLError, OSError) as e:
        if isinstance(e, UpdateError):
            raise
        raise UpdateError(f"Download fehlgeschlagen: {getattr(e, 'reason', e)}") from None
    if not zipfile.is_zipfile(dest):
        raise UpdateError("Die geladene Datei ist kein gültiges Zip-Archiv.")


def _extract(zip_path: Path) -> Path:
    out = Path(tempfile.mkdtemp(prefix="aerotagger-update-"))
    with zipfile.ZipFile(zip_path) as z:
        for m in z.namelist():                     # nichts außerhalb des Zielordners
            target = (out / m).resolve()
            if not str(target).startswith(str(out.resolve())):
                raise UpdateError("Ungültiger Pfad im Zip-Archiv.")
        z.extractall(out)
    return out


def _find_root(base: Path, marker: str) -> Path:
    """Ordner im entpackten Archiv, der marker enthält (Zips haben einen Oberordner)."""
    if (base / marker).exists():
        return base
    for p in sorted(base.rglob(marker), key=lambda p: len(p.parts)):
        return p.parent
    raise UpdateError(f"{marker} fehlt im Update-Archiv.")


def install_source(zip_path: Path, app_dir: Path = None) -> bool:
    """Spielt den Quellcode ein. Rückgabe: True, wenn sich requirements.txt geändert hat."""
    app_dir = Path(app_dir or core.APP_DIR)
    base = _extract(zip_path)
    src = _find_root(base, "AeroTagger.pyw")
    req_old = (app_dir / "requirements.txt").read_bytes() if (app_dir / "requirements.txt").exists() else b""
    try:
        for root, dirs, files in os.walk(src):
            dirs[:] = [d for d in dirs if d not in SKIP]
            rel = Path(root).relative_to(src)
            (app_dir / rel).mkdir(parents=True, exist_ok=True)
            for fn in files:
                shutil.copy2(Path(root) / fn, app_dir / rel / fn)
                if fn == "exiftool" and rel == Path("vendor/exiftool"):
                    os.chmod(app_dir / rel / fn, 0o755)
                if fn.endswith(".command"):
                    os.chmod(app_dir / rel / fn, 0o755)
    except OSError as e:
        raise UpdateError(f"Dateien konnten nicht ersetzt werden: {e}") from None
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return (app_dir / "requirements.txt").read_bytes() != req_old


def update_requirements(app_dir: Path = None):
    """Installiert geänderte Abhängigkeiten in die laufende Python-Umgebung."""
    app_dir = Path(app_dir or core.APP_DIR)
    py = Path(sys.executable)
    if py.name.lower() == "pythonw.exe":
        py = py.with_name("python.exe")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([str(py), "-m", "pip", "install", "-q", "-r",
                        str(app_dir / "requirements.txt")],
                       capture_output=True, text=True, creationflags=flags)
    if r.returncode:
        raise UpdateError("Abhängigkeiten konnten nicht installiert werden:\n" + r.stderr[-800:])


def restart_command(app_dir: Path = None) -> list:
    app_dir = Path(app_dir or core.APP_DIR)
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, str(app_dir / "AeroTagger.pyw")]


def install_frozen(zip_path: Path, app_dir: Path = None, pid: int = None) -> Path:
    """Windows-EXE: entpackt das Update und schreibt ein Hilfsskript, das wartet, bis
    AeroTagger beendet ist, die Dateien ersetzt und AeroTagger neu startet.
    Rückgabe: Pfad des Skripts (mit run_helper starten, danach AeroTagger beenden)."""
    app_dir = Path(app_dir or core.APP_DIR)
    base = _extract(zip_path)
    src = _find_root(base, "AeroTagger.exe")
    pid = pid or os.getpid()
    bat = Path(tempfile.gettempdir()) / f"aerotagger-update-{pid}.bat"
    lines = [
        "@echo off",
        "chcp 65001 >nul",
        "title AeroTagger - Update",
        "echo AeroTagger wird aktualisiert - bitte warten ...",
        ":wait",
        f'tasklist /fi "PID eq {pid}" /nh 2>nul | find "{pid}" >nul && '
        '(timeout /t 1 /nobreak >nul & goto wait)',
        f'robocopy "{src}" "{app_dir}" /e /r:5 /w:1 /njh /njs /nfl /ndl /np >nul',
        "if errorlevel 8 (",
        "  echo.",
        "  echo Die Dateien konnten nicht ersetzt werden. Liegt AeroTagger in einem",
        "  echo geschuetzten Ordner wie C:\\Programme? Dann das Update von Hand entpacken.",
        "  pause",
        "  exit /b 1",
        ")",
        f'start "" "{app_dir / "AeroTagger.exe"}"',
        f'rmdir /s /q "{base}"',
        '(goto) 2>nul & del "%~f0"',
    ]
    bat.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return bat


def run_helper(bat: Path):
    subprocess.Popen(["cmd", "/c", str(bat)],
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                     close_fds=True)
