"""AeroTagger – Oberfläche (PySide6)."""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import (QDir, QEvent, QObject, QPointF, QRect, QRectF, QRunnable, QSize,
                            QStringListModel, Qt,
                            QProcess, QThread, QThreadPool, QTimer, QUrl, Signal)
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QImage,
                           QImageReader, QKeySequence, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap, QPolygonF, QTransform)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QFileDialog, QFileSystemModel, QFormLayout, QGridLayout, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListView, QListWidget,
    QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
    QProgressDialog, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
    QFrame, QTextBrowser,
    QStyle, QStyledItemDelegate, QTableWidget, QTableWidgetItem, QTabWidget,
    QToolButton, QTreeView, QVBoxLayout, QWidget, QInputDialog)

from . import core
from . import update as upd
from .core import FIELDS, FIELD_BY_KEY

CONFIG_FILE = core.CONFIG_DIR / "einstellungen.json"
TEMPLATE_DIR = core.CONFIG_DIR / "vorlagen"
RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "aerotagger" / "resources"


def _star(cx, cy, r):
    import math
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append(QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return QPolygonF(pts)


def draw_stars(p, x, y, size, n, total=5, gap=2, on=None, off=None):
    """Zeichnet total Sterne ab (x, y); die ersten n gefüllt. Rückgabe: Breite."""
    on = on or QColor("#F5A524")
    off = off or QColor(255, 255, 255, 60)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    for i in range(total):
        p.setBrush(on if i < n else off)
        p.drawPolygon(_star(x + i * (size + gap) + size / 2, y + size / 2, size / 2))
    p.restore()
    return total * size + (total - 1) * gap


def app_icon() -> QIcon:
    """Programmsymbol (Logo „Anhänger“) in allen Größen."""
    icon = QIcon()
    for n in (16, 24, 32, 48, 64, 128, 256):
        f = RES_DIR / f"icon_{n}.png"
        if f.is_file():
            icon.addFile(str(f), QSize(n, n))
    return icon


def lockup_icon() -> QIcon:
    """Logo mit Schriftzug für die Werkzeugleiste (1×, 2×, 3× für HiDPI)."""
    icon = QIcon()
    for d in (1, 2, 3):
        f = RES_DIR / f"lockup@{d}x.png"
        if f.is_file():
            pm = QPixmap(str(f))
            pm.setDevicePixelRatio(d)
            icon.addPixmap(pm)
    return icon
CACHE_DIR = core.CONFIG_DIR / "vorschau"
THUMB_PX = 360
PREVIEW_PX = 2560        # Kantenlänge der großen Vorschau
PREVIEW_CACHE = 6        # so viele große Vorschauen bleiben im Speicher
AC_FIELDS = ("headline", "title", "caption", "keywords", "location", "creator", "event")
AC_DEFAULTS = {
    "headline": ("{ac:Airline} {ac:Type} {ac}", True),
    "title": ("{ac}", True),
    "caption": ("{ac:Airline} – {ac:Type}, Registrierung {ac}, fotografiert am {aufnahme} "
                "in {airport} von {fotograf}.", False),
    "location": ("{airport}", True),
    "creator": ("{fotograf}", True),
    "keywords": ("Aviation; {ac}; {ac:Type}; {ac:Airline}", True),
    "event": ("", False),
}
RAW_MODES = [("sidecar", "XMP-Begleitdatei (.xmp) neben der RAW-Datei"),
             ("embed", "direkt in die RAW-Datei"),
             ("both", "Begleitdatei und RAW-Datei")]


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                          encoding="utf-8")


# --------------------------------------------------------------------------
# Vorschaubilder (Hintergrund)
# --------------------------------------------------------------------------
class ThumbSignals(QObject):
    loaded = Signal(int, str, QImage)


_ORIENT = {3: (180, False), 6: (90, False), 8: (270, False),
           2: (0, True), 4: (180, True), 5: (90, True), 7: (270, True)}


def _scaled_read(reader: QImageReader, max_px: int) -> QImage:
    reader.setAutoTransform(True)
    sz = reader.size()
    if sz.isValid() and max(sz.width(), sz.height()) > max_px:
        sz.scale(max_px, max_px, Qt.KeepAspectRatio)
        reader.setScaledSize(sz)
    return reader.read()


def load_image(path: str, et: core.ExifTool, max_px: int, large=False) -> QImage:
    """Liest ein Bild (bei RAW das eingebettete JPEG), gedreht und auf
    höchstens max_px Kantenlänge verkleinert."""
    img = QImage()
    if core.is_raw(path):
        try:
            data, orient = et.preview(path, large=large)
        except core.ExifToolError:
            data, orient = None, 1
        if data:
            img = QImage.fromData(data)
            if not img.isNull():
                if max(img.width(), img.height()) > max_px:
                    img = img.scaled(max_px, max_px, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
                rot, mirror = _ORIENT.get(orient, (0, False))
                if mirror:
                    img = img.mirrored(True, False)
                if rot:
                    img = img.transformed(QTransform().rotate(rot))
        if img.isNull():   # z. B. unkomprimierte DNG ohne eingebettetes JPEG
            r = QImageReader(path)
            r.setDecideFormatFromContent(True)
            img = _scaled_read(r, max_px)
    else:
        img = _scaled_read(QImageReader(path), max_px)
    return img


def make_thumb(path: str, et: core.ExifTool) -> QImage:
    try:
        st = os.stat(path)
        key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode()).hexdigest()
    except OSError:
        return QImage()
    cfile = CACHE_DIR / key[:2] / f"{key}.jpg"
    if cfile.exists():
        img = QImage(str(cfile))
        if not img.isNull():
            return img
    img = load_image(path, et, THUMB_PX)
    if not img.isNull():
        try:
            cfile.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(cfile), "JPG", 85)
        except OSError:
            pass
    return img


class ThumbTask(QRunnable):
    def __init__(self, win, gen, path):
        super().__init__()
        self.win, self.gen, self.path = win, gen, path

    def run(self):
        if self.gen != self.win.generation:
            return
        img = make_thumb(self.path, self.win.et_thumb)
        try:
            self.win.thumb_signals.loaded.emit(self.gen, self.path, img)
        except RuntimeError:
            pass


class NetSignals(QObject):
    done = Signal(str, object, str)      # Anfrage, Datensatz oder None, Fehlertext


class AcFetchTask(QRunnable):
    """Fragt adsbdb.com (ersatzweise hexdb.io) im Hintergrund ab."""

    def __init__(self, win, query):
        super().__init__()
        self.win, self.query = win, query

    def run(self):
        rec, err = None, ""
        try:
            rec = core.fetch_online(self.query)
        except core.OnlineError as e:
            err = str(e)
        except Exception as e:  # noqa
            err = f"Unerwarteter Fehler: {e}"
        try:
            self.win.net_signals.done.emit(self.query, rec, err)
        except RuntimeError:
            pass


class UpdateSignals(QObject):
    checked = Signal(object, str)        # Release oder None, Fehlertext
    progress = Signal(int, int)
    downloaded = Signal(str, str)        # Datei, Fehlertext


class UpdateCheckTask(QRunnable):
    def __init__(self, sig, repo, token):
        super().__init__()
        self.sig, self.repo, self.token = sig, repo, token

    def run(self):
        try:
            rel, err = upd.latest_release(self.repo, self.token), ""
        except upd.UpdateError as e:
            rel, err = None, str(e)
        try:
            self.sig.checked.emit(rel, err)
        except RuntimeError:
            pass


class UpdateDownloadTask(QRunnable):
    def __init__(self, sig, url, dest, token):
        super().__init__()
        self.sig, self.url, self.dest, self.token = sig, url, dest, token
        self.cancel = False

    def run(self):
        err = ""
        try:
            upd.download(self.url, Path(self.dest), self.token,
                         progress=lambda a, b: self.sig.progress.emit(a, b),
                         cancelled=lambda: self.cancel)
        except upd.UpdateError as e:
            err = str(e)
        try:
            self.sig.downloaded.emit(self.dest, err)
        except RuntimeError:
            pass


class AfSignals(QObject):
    done = Signal(str, object)        # Pfad, Fokuspunkte oder None


class AfTask(QRunnable):
    """Liest die Fokuspunkte eines Bildes im Hintergrund."""

    def __init__(self, win, path):
        super().__init__()
        self.win, self.path = win, path

    def run(self):
        data = None
        if self.path == self.win.preview.path:
            try:
                data = self.win.et_af.af_info(self.path)
            except Exception:  # noqa
                data = None
        try:
            self.win.af_signals.done.emit(self.path, data)
        except RuntimeError:
            pass


class PreviewSignals(QObject):
    loaded = Signal(str, QImage)
    full = Signal(str, QImage)        # volle Auflösung für die Lupe


class FullTask(QRunnable):
    """Lädt das Bild in voller Auflösung (für die Lupe)."""

    def __init__(self, win, path):
        super().__init__()
        self.win, self.path = win, path

    def run(self):
        img = QImage()
        if self.path == self.win.preview.path:      # noch aktuell?
            img = load_image(self.path, self.win.et_preview, 30000, large=True)
        try:
            self.win.prev_signals.full.emit(self.path, img)
        except RuntimeError:
            pass


class PreviewTask(QRunnable):
    """Lädt die große Vorschau eines Bildes im Hintergrund."""

    def __init__(self, win, path):
        super().__init__()
        self.win, self.path = win, path

    def run(self):
        img = QImage()
        if self.path in self.win.prev_wanted:     # inzwischen weitergeblättert?
            img = load_image(self.path, self.win.et_preview, PREVIEW_PX, large=True)
        try:
            self.win.prev_signals.loaded.emit(self.path, img)
        except RuntimeError:
            pass


class PreviewView(QWidget):
    """Große Bildvorschau mit Infozeile und Lupe (rechte Maustaste)."""
    BAR = 46
    LOUPE_R = 140                         # Radius der Lupe in Bildschirmpunkten
    LOUPE_ZOOMS = (0.5, 1.0, 2.0, 4.0)    # 1.0 = 100 % (1 Bildpixel = 1 Bildschirmpixel)

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.path = None
        self.pm = None
        self.final = False
        self.title = self.counter = self.info = ""
        self._scaled = None          # (Zielgröße, skalierte Pixmap)
        self._img_rect = None        # wo das Bild gerade gezeichnet ist
        self.full_path, self.full_pm = None, None
        self.loupe_pos = None
        self.loupe_zoom = 1.0
        self.tag = None              # Kennzeichnung „mit AeroTagger getaggt“
        self.af_on = False           # Fokuspunkte einblenden
        self.af_path, self.af, self.af_loading = None, None, False
        self.setMinimumHeight(160)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setToolTip("Rechte Maustaste gedrückt halten: Lupe (Mausrad ändert die Vergrößerung)\n"
                        "Doppelklick öffnet das Bild im Standardprogramm")

    def set_full(self, path, pm):
        self.full_path, self.full_pm = path, pm
        if self.loupe_pos is not None:
            self.update()

    TAG_LINE = 26

    def set_af(self, on, path=None, data=None, loading=False):
        """Fokuspunkte für path (data aus core.af_points, None = keine Daten)."""
        self.af_on, self.af_path, self.af, self.af_loading = on, path, data, loading
        self.update()

    def _draw_af(self, p, r):
        """Fokusfelder über das Bild r zeichnen; ohne Daten ein kurzer Hinweis."""
        if not self.af_on or self.af_path != self.path:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setClipRect(r)
        if self.af:
            pts, track = core.af_layout(self.af, r.width() / max(1, r.height()))
            colors = {core.AF_INACTIVE: (QColor(255, 255, 255, 70), 1.0),
                      core.AF_SELECTED: (QColor(255, 255, 255, 230), 1.6),
                      core.AF_FOCUS: (QColor("#ff3b30"), 2.4)}
            focus = 0
            for cx, cy, w, h, state in sorted(pts, key=lambda t: t[4]):
                col, width = colors[state]
                focus += state == core.AF_FOCUS
                bw, bh = max(6.0, w * r.width()), max(6.0, h * r.height())
                box = QRectF(r.x() + cx * r.width() - bw / 2, r.y() + cy * r.height() - bh / 2, bw, bh)
                if state == core.AF_FOCUS:        # dunkler Rand für Kontrast auf hellem Himmel
                    p.setPen(QPen(QColor(0, 0, 0, 120), width + 2))
                    p.drawRect(box)
                p.setPen(QPen(col, width))
                p.drawRect(box)
            amber = QColor("#F5A524")
            if track and track.get("box"):        # verfolgtes Motiv (EOS R)
                cx, cy, w, h = track["box"]
                bw, bh = max(8.0, w * r.width()), max(8.0, h * r.height())
                box = QRectF(r.x() + cx * r.width() - bw / 2, r.y() + cy * r.height() - bh / 2, bw, bh)
                p.setPen(QPen(QColor(0, 0, 0, 120), 4))
                p.drawRect(box)
                pen = QPen(amber, 2)
                pen.setStyle(Qt.DashLine)
                p.setPen(pen)
                p.drawRect(box)
            elif track and track.get("pt"):       # nur Mittelpunkt (R7, R10)
                x = r.x() + track["pt"][0] * r.width()
                y = r.y() + track["pt"][1] * r.height()
                for col, wd in ((QColor(0, 0, 0, 120), 4), (amber, 2)):
                    p.setPen(QPen(col, wd))
                    p.drawEllipse(QPointF(x, y), 11, 11)
                    p.drawLine(QPointF(x - 18, y), QPointF(x - 6, y))
                    p.drawLine(QPointF(x + 6, y), QPointF(x + 18, y))
                    p.drawLine(QPointF(x, y - 18), QPointF(x, y - 6))
                    p.drawLine(QPointF(x, y + 6), QPointF(x, y + 18))
            label = "AF" + (f": {self.af['mode']}" if self.af["mode"] else "")
            if focus:
                label += f"  ·  {focus} im Fokus"
            if track:
                label += "  ·  " + track["label"]
        else:
            label = "Fokuspunkte werden gelesen …" if self.af_loading else \
                "Keine Fokuspunkte (nur Canon-Kameras)"
        f = p.font()
        f.setPointSizeF(f.pointSizeF() * 0.9)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(label) + 14
        lab = QRectF(r.x() + 8, r.y() + 8, tw, p.fontMetrics().height() + 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(lab, 4, 4)
        p.setPen(QColor("#e4e6e9"))
        p.drawText(lab, Qt.AlignCenter, label)
        p.restore()

    def show_image(self, path, pm, final, title="", counter="", info="", tag=None, rating=0):
        self.rating = rating
        if path != self.path:
            self.full_path, self.full_pm = None, None
        if path != self.path or pm is not self.pm or (tag is None) != (getattr(self, "tag", None) is None):
            self._scaled = None
        self.path, self.pm, self.final = path, pm, final
        self.title, self.counter, self.info = title, counter, info
        self.tag = tag
        self.update()

    def _bar_h(self):
        return self.BAR + (self.TAG_LINE if getattr(self, "tag", None) is not None else 0)

    def _image_rect(self):
        return self.rect().adjusted(10, 10, -10, -10 - self._bar_h())

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#151618"))
        area = self._image_rect()
        if not self.path:
            p.setPen(QColor("#6d737b"))
            p.drawText(self.rect(), Qt.AlignCenter, "Kein Bild ausgewählt")
            return
        if self.pm and not self.pm.isNull() and area.width() > 10 and area.height() > 10:
            dpr = self.devicePixelRatioF()
            native = QSize(int(self.pm.width() / dpr), int(self.pm.height() / dpr))
            size = native.scaled(area.size(), Qt.KeepAspectRatio)
            if self.final and native.width() <= area.width() and native.height() <= area.height():
                size = native            # kleine Bilder nicht hochskalieren
            if not self._scaled or self._scaled[0] != size:
                spm = self.pm.scaled(int(size.width() * dpr), int(size.height() * dpr),
                                     Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation if self.final else Qt.FastTransformation)
                spm.setDevicePixelRatio(dpr)
                self._scaled = (size, spm)
            spm = self._scaled[1]
            x = area.x() + (area.width() - size.width()) // 2
            y = area.y() + (area.height() - size.height()) // 2
            p.drawPixmap(x, y, spm)
            self._img_rect = QRect(x, y, size.width(), size.height())
            self._draw_af(p, self._img_rect)
        elif not self.pm:
            p.setPen(QColor("#6d737b"))
            p.drawText(area, Qt.AlignCenter, "Vorschau wird geladen …")
        # Infozeile
        bh = self._bar_h()
        bar = QRect(0, self.height() - bh, self.width(), bh)
        p.fillRect(bar, QColor("#1d1f22"))
        f = p.font()
        fb = p.font()
        fb.setBold(True)
        y0 = bar.y()
        if self.tag is not None:
            self._draw_tag_line(p, QRect(12, y0 + 6, self.width() - 24, 20))
            y0 += self.TAG_LINE
        p.setFont(fb)
        p.setPen(QColor("#e4e6e9"))
        top = QRect(12, y0 + 5, self.width() - 24, 18)
        p.drawText(top, Qt.AlignLeft | Qt.AlignVCenter, self.title)
        p.setFont(f)
        p.setPen(QColor("#9aa1a9"))
        ctext = self.counter + ("" if self.final else "   ·  lädt …")
        p.drawText(top, Qt.AlignRight | Qt.AlignVCenter, ctext)
        sw = draw_stars(p, 0, -100, 12, 0)                 # nur Breite ermitteln
        draw_stars(p, top.right() - p.fontMetrics().horizontalAdvance(ctext) - 16 - sw,
                   top.y() + 3, 12, getattr(self, "rating", 0),
                   off=QColor(255, 255, 255, 45))
        bottom = QRect(12, y0 + 24, self.width() - 24, 18)
        p.drawText(bottom, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.info, Qt.ElideRight, bottom.width()))
        if self.loupe_pos is not None:
            self._draw_loupe(p)

    def _draw_tag_line(self, p, r):
        """Getaggt: Logo, Registrierung (fett, bernstein), Operator, Typ."""
        p.save()
        icon = app_icon().pixmap(QSize(18, 18), self.devicePixelRatioF())
        p.drawPixmap(r.x(), r.y() + 1, icon)
        x = r.x() + 26
        t = self.tag
        f = p.font()
        f.setPointSizeF(f.pointSizeF() * 1.15)
        fb = QFont(f)
        fb.setBold(True)
        if t.get("reg"):
            p.setFont(fb)
            p.setPen(QColor("#F5A524"))
            p.drawText(QRect(x, r.y(), r.width(), r.height()), Qt.AlignLeft | Qt.AlignVCenter, t["reg"])
            x += p.fontMetrics().horizontalAdvance(t["reg"]) + 4
        rest = [v for v in (t.get("op"), t.get("type")) if v]
        p.setFont(f)
        if rest:
            p.setPen(QColor("#e4e6e9"))
            txt = "  ·  " + "  ·  ".join(rest) if t.get("reg") else "  ·  ".join(rest)
        elif not t.get("reg"):
            p.setPen(QColor("#9aa1a9"))
            txt = "mit AeroTagger getaggt"
        else:
            txt = ""
        w = r.right() - x
        if txt and w > 20:
            p.drawText(QRect(x, r.y(), w, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(txt, Qt.ElideRight, w))
        p.restore()

    # ---- Lupe -------------------------------------------------------------
    def _draw_loupe(self, p):
        r, pos = self._img_rect, self.loupe_pos
        full = self.full_pm if (self.full_pm is not None and self.full_path == self.path) else None
        src = full or self.pm
        if r is None or r.width() < 2 or src is None or src.isNull():
            return
        dpr = self.devicePixelRatioF()
        u = min(max((pos.x() - r.x()) / r.width(), 0.0), 1.0)
        v = min(max((pos.y() - r.y()) / r.height(), 0.0), 1.0)
        sw, sh = src.width(), src.height()
        disp = r.width() * dpr / sw                  # Bildschirmpixel je Quellpixel in der Vorschau
        if full is not None:
            zoom = max(self.loupe_zoom, disp * 2)    # immer mindestens doppelt so groß wie die Vorschau
        else:
            zoom = disp * 3                          # bis die volle Auflösung da ist
        R = self.LOUPE_R
        side = 2 * R * dpr / zoom                    # Ausschnitt in Quellpixeln
        srect = QRectF(u * sw - side / 2, v * sh - side / 2, side, side)
        target = QRectF(pos.x() - R, pos.y() - R, 2 * R, 2 * R)
        inter = srect.intersected(QRectF(0, 0, sw, sh))
        k = target.width() / srect.width()
        t2 = QRectF(target.x() + (inter.x() - srect.x()) * k, target.y() + (inter.y() - srect.y()) * k,
                    inter.width() * k, inter.height() * k)
        circle = QPainterPath()
        circle.addEllipse(target)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform, zoom < 1.9)
        p.setClipPath(circle)
        p.fillRect(target, QColor("#151618"))
        if not inter.isEmpty():
            p.drawPixmap(t2, src, inter)
        label = f"{round(zoom * 100)} %" if full is not None else "lädt volle Auflösung …"
        fm = p.fontMetrics()
        lw = fm.horizontalAdvance(label) + 14
        lab = QRectF(pos.x() - lw / 2, pos.y() + R - 30, lw, 19)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(lab, 9, 9)
        p.setPen(QColor("#e4e6e9"))
        p.drawText(lab, Qt.AlignCenter, label)
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 150), 5))
        p.drawEllipse(target)
        p.setPen(QPen(QColor("#e4e6e9"), 1.6))
        p.drawEllipse(target)
        p.restore()

    def _loupe_area(self, pos):
        R = self.LOUPE_R + 6
        return QRect(pos.x() - R, pos.y() - R, 2 * R, 2 * R)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton and self.path and self.pm:
            self.loupe_pos = ev.position().toPoint()
            self.setCursor(Qt.BlankCursor)
            self.win.request_full(self.path)
            self.update(self._loupe_area(self.loupe_pos))
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self.loupe_pos is not None:
            old = self._loupe_area(self.loupe_pos)
            self.loupe_pos = ev.position().toPoint()
            self.update(old.united(self._loupe_area(self.loupe_pos)))
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.RightButton and self.loupe_pos is not None:
            area = self._loupe_area(self.loupe_pos)
            self.loupe_pos = None
            self.unsetCursor()
            self.update(area)
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def wheelEvent(self, ev):
        if self.loupe_pos is None:
            ev.ignore()
            return
        z = list(self.LOUPE_ZOOMS)
        i = min(range(len(z)), key=lambda n: abs(z[n] - self.loupe_zoom))
        i = min(len(z) - 1, i + 1) if ev.angleDelta().y() > 0 else max(0, i - 1)
        self.loupe_zoom = z[i]
        self.update(self._loupe_area(self.loupe_pos))
        ev.accept()

    def contextMenuEvent(self, ev):
        ev.accept()          # kein Kontextmenü – die rechte Taste gehört der Lupe

    def mouseDoubleClickEvent(self, _ev):
        if self.path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.path))

    def keyPressEvent(self, ev):
        # Pfeiltasten usw. an den Filmstreifen weiterreichen
        self.win.lst.setFocus()
        QApplication.sendEvent(self.win.lst, ev)


class MetaPanel(QTextBrowser):
    """Zeigt die vorhandenen IPTC-/XMP-Metadaten des aktuellen Bildes
    unter der Vorschau. Die Höhe passt sich dem Inhalt an (begrenzt)."""
    MAX_H = 260

    def __init__(self):
        super().__init__()
        self.setOpenLinks(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet("QTextBrowser { background:#1d1f22; color:#e4e6e9;"
                           " border-top:1px solid #2c2f33; padding:2px 8px 4px 8px; }")
        self._fitting = False

    def show_meta(self, m: dict):
        esc = lambda s: html.escape(str(s)).replace("\n", "<br>")   # noqa: E731
        fv = lambda k: core.field_value(m, FIELD_BY_KEY[k])        # noqa: E731
        rows = []

        def add(label, value, raw_html=False):
            if value:
                rows.append((label, value if raw_html else esc(value)))

        add("Überschrift", f"<b>{esc(fv('headline'))}</b>" if fv("headline") else "", True)
        add("Beschreibung", fv("caption"))
        kws = core.split_list(fv("keywords"))
        add("Stichwörter", " ".join(
            f"<span style='background:#34383e;'>&nbsp;{esc(k)}&nbsp;</span>" for k in kws), True)
        add("Personen", fv("persons"))
        add("Ereignis", fv("event"))
        add("Titel", fv("title"))
        place = ", ".join(x for x in (fv("location"), fv("city"), fv("state"), fv("country")) if x)
        if place and fv("countrycode"):
            place += f" ({fv('countrycode')})"
        add("Ort", place)
        creator = fv("creator") + (f" – {fv('creatortitle')}" if fv("creatortitle") else "")
        add("Fotograf", creator)
        add("Copyright", fv("copyright"))
        add("Bildnachweis", " · ".join(x for x in (fv("credit"), fv("source")) if x))
        add("Nutzung", fv("usage"))
        add("Kontakt", " · ".join(x for x in (fv("email"), fv("url")) if x))
        add("Anweisungen", fv("instructions"))
        add("Auftrag", fv("jobid"))
        add("Beschreibung von", fv("captionwriter"))
        add("EXIF-Kommentar", fv("usercomment"))
        r = core.rating_of(m)
        if r:
            add("Bewertung", f"<span style='color:#ffcc66;'>{'★' * r}</span>"
                             f"<span style='color:#555a61;'>{'★' * (5 - r)}</span>", True)
        add("Markierung", core.lookup(m, "Label") or "")

        if rows:
            body = "".join(
                "<tr><td width='118' style='color:#8b929a; padding:1px 12px 1px 0;' valign='top' nowrap>"
                f"{lab}</td><td style='padding:1px 0;'>{val}</td></tr>" for lab, val in rows)
            doc = f"<table cellspacing='0' cellpadding='0' width='100%'>{body}</table>"
        else:
            doc = ("<span style='color:#7d838b;'>Keine IPTC-/XMP-Metadaten vorhanden.</span>")
        if m.get("_sidecar"):
            doc += (f"<div style='color:#7d838b; font-size:small; margin-top:3px;'>"
                    f"inkl. Begleitdatei {esc(os.path.basename(m['_sidecar']))}</div>")
        self.setHtml(doc)
        QTimer.singleShot(0, self._fit)

    def clear_meta(self):
        self.setHtml("")
        QTimer.singleShot(0, self._fit)

    def _fit(self):
        if self._fitting:
            return
        self._fitting = True
        try:
            d = self.document()
            d.setTextWidth(self.viewport().width())
            h = int(d.size().height()) + 10
            self.setFixedHeight(max(30, min(self.MAX_H, h)))
        finally:
            self._fitting = False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if ev.oldSize().width() != ev.size().width():
            QTimer.singleShot(0, self._fit)


class StarEdit(QWidget):
    """Eingabefeld für die Sternbewertung (Feld „Bewertung“): Klick auf einen
    Stern setzt ihn, erneuter Klick auf denselben = keine Sterne. Tasten 0–5.
    Verhält sich nach außen wie ein Textfeld (text/setText/textEdited)."""
    textEdited = Signal(str)
    SIZE, GAP = 16, 4

    def __init__(self):
        super().__init__()
        self._v, self.hover = 0, 0
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(26)
        self.setToolTip("Klick setzt die Sterne – erneuter Klick auf denselben Stern: keine Sterne (0).\n"
                        "Mit Fokus auch Tasten 0–5.")

    def text(self):
        return str(self._v)

    def setText(self, t):
        try:
            v = int(round(float(t)))
        except (TypeError, ValueError):
            v = 0
        self._v = max(0, min(5, v))
        self.update()

    def _set(self, v):
        self._v = v
        self.update()
        self.textEdited.emit(self.text())

    def _index(self, x):
        return max(1, min(5, int((x - 4) // (self.SIZE + self.GAP)) + 1))

    def paintEvent(self, _ev):
        p = QPainter(self)
        if self.hasFocus():
            p.setPen(QColor("#2f6fb3"))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 4, 4)
        n = self.hover or self._v
        w = draw_stars(p, 4, (self.height() - self.SIZE) / 2, self.SIZE, n, gap=self.GAP,
                       on=QColor("#F5A524") if not self.hover else QColor(245, 165, 36, 170),
                       off=QColor(255, 255, 255, 55))
        p.setPen(QColor("#9aa1a9"))
        label = "keine Sterne (0)" if self._v == 0 else f"{self._v} Stern" + ("e" if self._v > 1 else "")
        p.drawText(QRect(4 + w + 12, 0, self.width() - w - 16, self.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, label)

    def mouseMoveEvent(self, ev):
        x = ev.position().x()
        h = self._index(x) if x < 4 + 5 * (self.SIZE + self.GAP) else 0
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, _ev):
        self.hover = 0
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and ev.position().x() < 4 + 5 * (self.SIZE + self.GAP):
            i = self._index(ev.position().x())
            self._set(0 if i == self._v else i)

    def keyPressEvent(self, ev):
        k = ev.key()
        if Qt.Key_0 <= k <= Qt.Key_5:
            self._set(k - Qt.Key_0)
        else:
            super().keyPressEvent(ev)


class StarFilter(QWidget):
    """Fünf anklickbare Sterne für den Bewertungsfilter (wie in Lightroom):
    Klick setzt die Stufe, erneuter Klick auf dieselbe hebt den Filter auf."""
    changed = Signal(int)
    SIZE, GAP = 15, 4

    def __init__(self):
        super().__init__()
        self.value, self.hover = 0, 0
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(5 * self.SIZE + 4 * self.GAP + 4, 24)
        self.setToolTip("Klick auf einen Stern setzt den Filter – erneuter Klick hebt ihn auf")

    def _index(self, x):
        return max(1, min(5, int((x - 2) // (self.SIZE + self.GAP)) + 1))

    def set_value(self, v):
        self.value = max(0, min(5, int(v)))
        self.update()

    def paintEvent(self, _ev):
        p = QPainter(self)
        n = self.hover or self.value
        on = QColor("#F5A524") if (not self.hover or self.hover == self.value) else QColor(245, 165, 36, 160)
        draw_stars(p, 2, (self.height() - self.SIZE) / 2, self.SIZE, n, gap=self.GAP,
                   on=on, off=QColor(255, 255, 255, 55))

    def mouseMoveEvent(self, ev):
        h = self._index(ev.position().x())
        if h != self.hover:
            self.hover = h
            self.update()

    def leaveEvent(self, _ev):
        self.hover = 0
        self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            i = self._index(ev.position().x())
            self.set_value(0 if i == self.value else i)
            self.changed.emit(self.value)


class ThumbDelegate(QStyledItemDelegate):
    """Zeichnet eine Bildkachel: Vorschau, Dateiname, RAW-Kennzeichen."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def sizeHint(self, _opt, _idx):
        v = self.win.tile
        return QSize(v + 16, v + 32)

    def paint(self, p, opt, idx):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = opt.rect.adjusted(3, 3, -3, -3)
        selected = bool(opt.state & QStyle.State_Selected)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2f6fb3") if selected else QColor("#2b2d31"))
        p.drawRoundedRect(r, 5, 5)
        path = idx.data(Qt.UserRole)
        area = QRect(r.left() + 6, r.top() + 6, r.width() - 12, r.height() - 32)
        pm = self.win.pixmaps.get(path)
        if pm:
            sz = pm.size().scaled(area.size(), Qt.KeepAspectRatio)
            target = QRect(area.center().x() - sz.width() // 2,
                           area.center().y() - sz.height() // 2,
                           sz.width(), sz.height())
            p.drawPixmap(target, pm)
        else:
            p.setBrush(QColor("#3a3d41"))
            p.drawRect(area.adjusted(10, 20, -10, -20))
        trect = QRect(r.left() + 4, r.bottom() - 22, r.width() - 8, 20)
        if core.is_raw(path):              # RAW-Kennzeichen rechts unter dem Bild
            f = QFont(opt.font)
            f.setPointSizeF(f.pointSizeF() * 0.8)
            f.setBold(True)
            p.setFont(f)
            bw = p.fontMetrics().horizontalAdvance("RAW") + 10
            br = QRect(r.right() - 6 - bw, trect.center().y() - 8, bw, 17)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(br, 3, 3)
            p.setPen(QColor("#ffcc66"))
            p.drawText(br, Qt.AlignCenter, "RAW")
            p.setFont(opt.font)
            trect.setRight(br.left() - 4)
        p.setPen(QColor("#ffffff") if selected else QColor("#c9cdd2"))
        name = opt.fontMetrics.elidedText(idx.data(Qt.DisplayRole), Qt.ElideMiddle, trect.width())
        p.drawText(trect, Qt.AlignCenter, name)
        y, h = r.top() + 6, 18
        left, right = r.left() + 6, r.right() - 6
        rating = self.win.ratings.get(path, 0)
        if rating > 0:                     # links oben: Sterne
            sz = 10 if r.width() < 150 else 11
            w = 5 * sz + 4 * 2 + 10
            if left + w <= right:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 170))
                p.drawRoundedRect(QRect(left, y, w, h), 4, 4)
                draw_stars(p, left + 5, y + (h - sz) / 2, sz, rating)
                left += w + 4
        info = self.win.tagged.get(path)
        if info is not None and right - left >= 22:   # rechts oben: Registrierung
            f = QFont(opt.font)
            f.setPointSizeF(f.pointSizeF() * 0.85)
            f.setBold(True)
            p.setFont(f)
            fm = p.fontMetrics()
            label = fm.elidedText(info.get("reg") or "✓", Qt.ElideRight, right - left - 12)
            w = fm.horizontalAdvance(label) + 12
            tb = QRect(right - w, y, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#F5A524"))
            p.drawRoundedRect(tb, 4, 4)
            p.setPen(QColor("#0B2540"))
            p.drawText(tb, Qt.AlignCenter, label)
        p.restore()


class LogoLabel(QLabel):
    """Logo mit Schriftzug in der Werkzeugleiste; Klick öffnet „Über AeroTagger“."""
    SIZE = QSize(141, 28)

    def __init__(self, on_click):
        super().__init__()
        self._on_click = on_click
        self._icon = lockup_icon()
        self.setCursor(Qt.PointingHandCursor)
        self.setContentsMargins(6, 0, 10, 0)
        self._refresh()

    def _refresh(self):
        self.setPixmap(self._icon.pixmap(self.SIZE, self.devicePixelRatioF()))

    def event(self, ev):
        if ev.type() in (QEvent.DevicePixelRatioChange, QEvent.ScreenChangeInternal):
            self._refresh()
        return super().event(ev)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self._on_click()
        super().mouseReleaseEvent(ev)


class ScanSignals(QObject):
    done = Signal(int, object)


class MetaScanTask(QRunnable):
    """Liest die Metadaten des ganzen Ordners im Hintergrund – für die
    AeroTagger-Markierung im Filmstreifen (und schnelleres Blättern)."""

    def __init__(self, win, gen, paths):
        super().__init__()
        self.win, self.gen, self.paths = win, gen, list(paths)

    def run(self):
        for i in range(0, len(self.paths), 40):
            if self.gen != self.win.generation:
                return
            try:
                data = self.win.et_scan.read_merged(self.paths[i:i + 40])
            except core.ExifToolError:
                continue
            try:
                self.win.scan_signals.done.emit(self.gen, data)
            except RuntimeError:
                return


class WriteWorker(QThread):
    progress = Signal(int, str)
    finished_all = Signal(list)

    def __init__(self, et, jobs, opts):
        super().__init__()
        self.et, self.jobs, self.opts = et, jobs, opts
        self.cancel = False

    def run(self):
        results = []
        for i, job in enumerate(self.jobs):
            path, values, extras = job[:3]
            new_stem = job[3] if len(job) > 3 else None
            list_ops = job[4] if len(job) > 4 else ()
            if self.cancel:
                break
            self.progress.emit(i, os.path.basename(path))
            try:
                ok, msg = self.et.write(path, values, extras, list_ops=list_ops, **self.opts)
            except Exception as e:  # noqa
                ok, msg = False, str(e)
            new_path, rmsg = path, ""
            if ok and new_stem is not None:
                try:
                    new_path = core.rename_file(path, new_stem)
                except OSError as e:
                    rmsg = f"Umbenennen fehlgeschlagen: {e}"
            results.append((path, ok, msg, new_path, rmsg))
        self.finished_all.emit(results)


# --------------------------------------------------------------------------
# Dialoge
# --------------------------------------------------------------------------
TEMPLATE_FORMAT = "aerotagger-metadaten-template"
TEMPLATE_KEYS = ("name", "fields", "extra", "extra_on", "kw_mode", "seq_start", "rename",
                 "rename_on", "codes_csv", "data_csv", "data_key")


def template_to_file(parent, state, start_dir=""):
    """Template als JSON speichern (Datei-Dialog)."""
    name = "".join(ch for ch in (state.get("name") or "Template") if ch not in '\\/:*?"<>|').strip()
    fn, _ = QFileDialog.getSaveFileName(parent, "Template exportieren",
                                        os.path.join(start_dir or str(Path.home()), f"{name or 'Template'}.json"),
                                        "JSON (*.json)")
    if not fn:
        return False
    if not fn.lower().endswith(".json"):
        fn += ".json"
    data = {"format": TEMPLATE_FORMAT, "version": 1, "app": f"{core.APP_NAME} {core.APP_VERSION}"}
    data.update({k: state.get(k) for k in TEMPLATE_KEYS if k in state})
    try:
        save_json(fn, data)
    except OSError as e:
        QMessageBox.warning(parent, "Template exportieren", f"Datei konnte nicht gespeichert werden:\n{e}")
        return False
    return True


def template_from_file(parent, start_dir=""):
    """Template aus JSON laden; liest auch Vorlagen aus dem Reiter „Metadaten schreiben“."""
    fn, _ = QFileDialog.getOpenFileName(parent, "Template importieren", start_dir or str(Path.home()),
                                        "JSON (*.json);;Alle Dateien (*)")
    if not fn:
        return None
    try:
        data = json.loads(Path(fn).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        QMessageBox.warning(parent, "Template importieren", f"Datei ist kein gültiges JSON:\n{e}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
        QMessageBox.warning(parent, "Template importieren",
                            "Die Datei enthält kein AeroTagger-Template (Abschnitt „fields“ fehlt).")
        return None
    st = {k: data[k] for k in TEMPLATE_KEYS if k in data}
    st["fields"] = {k: {"text": str((v or {}).get("text", "")), "on": bool((v or {}).get("on"))}
                    for k, v in data["fields"].items() if k in FIELD_BY_KEY and isinstance(v, dict)}
    st.setdefault("name", Path(fn).stem)
    return st


class TemplateDialog(QDialog):
    """„Metadaten Template“: dieselben Felder wie im Reiter „Metadaten schreiben“,
    als dauerhaft gespeicherte Vorlage mit Import/Export (JSON)."""

    def __init__(self, win, state):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Metadaten Template")
        self.resize(780, 860)
        self.last_editor = None
        ol = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Name"))
        self.ed_name = QLineEdit()
        self.ed_name.setPlaceholderText("z. B. Spotting Innsbruck")
        row.addWidget(self.ed_name, 1)
        ol.addLayout(row)
        hint = QLabel("Nur angehakte Felder werden geschrieben – ein angehaktes leeres Feld löscht den "
                      "Inhalt im Bild. Variablen und =Kürzel= wie im Reiter „Metadaten schreiben“. "
                      "Anwenden: Menü Metadaten › Template auf Auswahl anwenden (Strg+Umschalt+M).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9aa1a9;")
        ol.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        self.checks, self.edits = {}, {}
        groups = []
        for f in FIELDS:
            if f.group not in groups:
                groups.append(f.group)
        for g in groups:
            box = QGroupBox(g)
            grid = QGridLayout(box)
            grid.setColumnStretch(1, 1)
            grid.setColumnMinimumWidth(0, 190)
            for r, f in enumerate([x for x in FIELDS if x.group == g]):
                cb = QCheckBox(f.label)
                cb.setToolTip("Angehakt = Feld wird geschrieben\nZiel: " + ", ".join(f.tags))
                if f.key == "rating":
                    ed = StarEdit()
                    ed.textEdited.connect(lambda _t, k=f.key: self.checks[k].setChecked(True))
                elif f.multiline:
                    ed = QPlainTextEdit()
                    ed.setFixedHeight(64)
                    ed.setTabChangesFocus(True)
                    ed.textChanged.connect(lambda k=f.key: self._edited(k))
                else:
                    ed = QLineEdit()
                    ed.textEdited.connect(lambda _t, k=f.key: self._edited(k))
                if f.hint and not isinstance(ed, StarEdit):
                    ed.setPlaceholderText(f.hint)
                if not isinstance(ed, StarEdit):
                    ed.installEventFilter(self)
                grid.addWidget(cb, r, 0, Qt.AlignTop)
                grid.addWidget(ed, r, 1)
                self.checks[f.key], self.edits[f.key] = cb, ed
            il.addWidget(box)

        box = QGroupBox("Weitere Tags (ExifTool-Namen)")
        bl = QVBoxLayout(box)
        self.chk_extra = QCheckBox("schreiben – je Zeile  TAG = Wert")
        self.ed_extra = QPlainTextEdit()
        self.ed_extra.setFixedHeight(64)
        self.ed_extra.setPlaceholderText("XMP-xmp:Rating = 5")
        self.ed_extra.installEventFilter(self)
        bl.addWidget(self.chk_extra)
        bl.addWidget(self.ed_extra)
        il.addWidget(box)

        box = QGroupBox("CSV-Dateien und Optionen")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.ed_codes, self.ed_data = QLineEdit(), QLineEdit()
        self.ed_codes.setPlaceholderText("Kürzel;Ersetzung  →  =kürzel=")
        self.ed_data.setPlaceholderText("Tabelle mit Kopfzeile  →  {csv:Spaltenname}")
        for r, (label, ed, title) in enumerate((("Kürzel-CSV", self.ed_codes, "Kürzel-CSV wählen"),
                                                ("Daten-CSV", self.ed_data, "Daten-CSV wählen"))):
            ed.setReadOnly(True)
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(ed, r, 1)
            b = QPushButton("…")
            b.setFixedWidth(32)
            b.clicked.connect(lambda _=False, e=ed, t=title: self._pick_csv(e, t))
            grid.addWidget(b, r, 2)
            b = QPushButton("✕")
            b.setFixedWidth(32)
            b.clicked.connect(lambda _=False, e=ed: self._set_csv(e, ""))
            grid.addWidget(b, r, 3)
        grid.addWidget(QLabel("Schlüsselspalte"), 2, 0)
        self.cmb_key = QComboBox()
        self.cmb_key.setToolTip("Spalte der Daten-CSV mit dem Dateinamen")
        grid.addWidget(self.cmb_key, 2, 1, 1, 3)
        grid.addWidget(QLabel("Stichwörter"), 3, 0)
        orow = QHBoxLayout()
        self.cmb_kw = QComboBox()
        self.cmb_kw.addItem("vorhandene ersetzen", "replace")
        self.cmb_kw.addItem("zu vorhandenen hinzufügen", "append")
        orow.addWidget(self.cmb_kw, 1)
        orow.addWidget(QLabel("  {seq} beginnt bei"))
        self.spn_seq = QSpinBox()
        self.spn_seq.setRange(0, 999999)
        orow.addWidget(self.spn_seq)
        grid.addLayout(orow, 3, 1, 1, 3)
        il.addWidget(box)

        box = QGroupBox("Datei umbenennen")
        bl = QVBoxLayout(box)
        self.chk_rename = QCheckBox("beim Schreiben umbenennen")
        self.ed_rename = QLineEdit()
        self.ed_rename.setPlaceholderText("z. B. {isodate}_{filenamebase}")
        self.ed_rename.setToolTip("Neuer Dateiname mit Variablen, ohne Endung")
        self.ed_rename.installEventFilter(self)
        bl.addWidget(self.chk_rename)
        bl.addWidget(self.ed_rename)
        il.addWidget(box)
        il.addStretch(1)
        scroll.setWidget(inner)
        ol.addWidget(scroll, 1)

        brow = QHBoxLayout()
        b = QToolButton()
        b.setText("Variable einfügen")
        b.setPopupMode(QToolButton.InstantPopup)
        b.setMenu(win.build_var_menu(False, inserter=self.insert_token))
        brow.addWidget(b)
        b = QPushButton("Aus Reiter übernehmen")
        b.setToolTip("Felder aus dem Reiter „Metadaten schreiben“ übernehmen")
        b.clicked.connect(self.from_tab)
        brow.addWidget(b)
        brow.addStretch(1)
        b = QPushButton("Importieren…")
        b.setToolTip("Template aus einer JSON-Datei laden")
        b.clicked.connect(self.do_import)
        brow.addWidget(b)
        b = QPushButton("Exportieren…")
        b.setToolTip("Template als JSON-Datei speichern")
        b.clicked.connect(lambda: template_to_file(self, self.state(), win.folder))
        brow.addWidget(b)
        ol.addLayout(brow)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("Speichern")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        ol.addWidget(bb)
        self.set_state(state)

    # -- Bearbeiten --
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.FocusIn:
            self.last_editor = obj
        return super().eventFilter(obj, ev)

    def _edited(self, key):
        if self.edits[key].hasFocus():
            self.checks[key].setChecked(True)

    def insert_token(self, token):
        ed = self.last_editor or self.edits["caption"]
        if isinstance(ed, QPlainTextEdit):
            ed.insertPlainText(token)
        else:
            ed.insert(token)
        for k, e in self.edits.items():
            if e is ed:
                self.checks[k].setChecked(True)
        if ed is self.ed_extra:
            self.chk_extra.setChecked(True)
        ed.setFocus()

    def _pick_csv(self, ed, title):
        fn, _ = QFileDialog.getOpenFileName(self, title, os.path.dirname(ed.text()) or self.win.folder,
                                            "CSV/Text (*.csv *.txt *.tsv);;Alle Dateien (*)")
        if fn:
            self._set_csv(ed, fn)

    def _set_csv(self, ed, path, key=None):
        ed.setText(path)
        ed.setToolTip(path)
        if ed is self.ed_data:
            cols = []
            if path and os.path.isfile(path):
                try:
                    cols = core.DataTable(path).columns
                except Exception:  # noqa
                    cols = []
            cur = key or self.cmb_key.currentText()
            self.cmb_key.clear()
            self.cmb_key.addItems(cols)
            if cur in cols:
                self.cmb_key.setCurrentText(cur)

    # -- Zustand --
    def _text(self, k):
        ed = self.edits[k]
        return ed.toPlainText() if isinstance(ed, QPlainTextEdit) else ed.text()

    def state(self):
        return {"name": self.ed_name.text().strip() or "Standard",
                "fields": {k: {"text": self._text(k), "on": self.checks[k].isChecked()} for k in self.edits},
                "extra": self.ed_extra.toPlainText(), "extra_on": self.chk_extra.isChecked(),
                "kw_mode": self.cmb_kw.currentData(), "seq_start": self.spn_seq.value(),
                "rename": self.ed_rename.text(), "rename_on": self.chk_rename.isChecked(),
                "codes_csv": self.ed_codes.text(), "data_csv": self.ed_data.text(),
                "data_key": self.cmb_key.currentText() or None}

    def set_state(self, st):
        self.ed_name.setText(st.get("name") or "Standard")
        flds = st.get("fields") or {}
        for k, ed in self.edits.items():
            v = flds.get(k) or {}
            ed.blockSignals(True)
            if isinstance(ed, QPlainTextEdit):
                ed.setPlainText(v.get("text", ""))
            else:
                ed.setText(v.get("text", ""))
            ed.blockSignals(False)
            self.checks[k].setChecked(bool(v.get("on")))
        self.ed_extra.setPlainText(st.get("extra", ""))
        self.chk_extra.setChecked(bool(st.get("extra_on")))
        self.cmb_kw.setCurrentIndex(1 if st.get("kw_mode") == "append" else 0)
        self.spn_seq.setValue(int(st.get("seq_start", 1) or 0))
        self.ed_rename.setText(st.get("rename", ""))
        self.chk_rename.setChecked(bool(st.get("rename_on")))
        self._set_csv(self.ed_codes, st.get("codes_csv") or "")
        self._set_csv(self.ed_data, st.get("data_csv") or "", st.get("data_key"))

    def from_tab(self):
        w = self.win
        st = dict(w.pad_state(), name=self.ed_name.text(), codes_csv=w.codes.path or "",
                  data_csv=w.data.path or "", data_key=w.data.key_column)
        self.set_state(st)

    def do_import(self):
        st = template_from_file(self, self.win.folder)
        if st is not None:
            self.set_state(st)


class PreviewDialog(QDialog):
    def __init__(self, parent, rows, columns, n_warn, total,
                 empty_note="Leere Zellen bedeuten: Feld wird geleert."):
        super().__init__(parent)
        self.setWindowTitle("Vorschau der Metadaten")
        self.resize(1100, 600)
        lay = QVBoxLayout(self)
        info = f"{total} Datei(en). {empty_note}"
        if total > len(rows):
            info += f" Angezeigt werden die ersten {len(rows)}."
        if n_warn:
            info += f"  ⚠ {n_warn} nicht aufgelöste Variable(n)/Kürzel – orange markiert."
        lay.addWidget(QLabel(info))
        tbl = QTableWidget(len(rows), len(columns) + 1)
        tbl.setHorizontalHeaderLabels(["Datei"] + columns)
        for r, (name, vals, warns) in enumerate(rows):
            tbl.setItem(r, 0, QTableWidgetItem(name))
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setToolTip(v)
                if warns[c]:
                    it.setBackground(QColor("#8a5a00"))
                    it.setToolTip("\n".join(warns[c]))
                tbl.setItem(r, c + 1, it)
        tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        tbl.resizeColumnsToContents()
        for c in range(tbl.columnCount()):
            if tbl.columnWidth(c) > 320:
                tbl.setColumnWidth(c, 320)
        lay.addWidget(tbl)
        bb = QDialogButtonBox()
        bb.addButton(f"In {total} Datei(en) schreiben", QDialogButtonBox.AcceptRole)
        bb.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


class SettingsDialog(QDialog):
    def __init__(self, parent, cfg, et_info):
        super().__init__(parent)
        self.setWindowTitle("Einstellungen")
        self.setMinimumWidth(560)
        form = QFormLayout(self)
        self.raw = QComboBox()
        for k, label in RAW_MODES:
            self.raw.addItem(label, k)
        self.raw.setCurrentIndex([k for k, _ in RAW_MODES].index(cfg.get("raw_mode", "sidecar")))
        form.addRow("RAW-Metadaten schreiben in:", self.raw)
        self.backup = QCheckBox("Sicherungskopie anlegen (Datei_original)")
        self.backup.setChecked(cfg.get("backup", False))
        form.addRow("Vor dem Schreiben:", self.backup)
        row = QHBoxLayout()
        self.et = QLineEdit(cfg.get("exiftool", ""))
        self.et.setPlaceholderText("leer = automatisch suchen")
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(self._pick)
        row.addWidget(self.et)
        row.addWidget(b)
        form.addRow("ExifTool-Programm:", row)
        form.addRow("", QLabel(et_info))
        self.repo = QLineEdit(cfg.get("update_repo", ""))
        self.repo.setPlaceholderText(upd.default_repo() or "benutzer/AeroTagger")
        form.addRow("Updates von GitHub:", self.repo)
        self.token = QLineEdit(cfg.get("github_token", ""))
        self.token.setEchoMode(QLineEdit.Password)
        self.token.setPlaceholderText("nur für private Repositories")
        form.addRow("GitHub-Token:", self.token)
        hint = QLabel("Für ein privates Repository einen „Fine-grained token“ mit Leserecht "
                      "auf „Contents“ anlegen: GitHub → Settings → Developer settings → "
                      "Personal access tokens. Der Token wird unverschlüsselt in den "
                      "Einstellungen gespeichert.")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9aa0a6")
        form.addRow("", hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _pick(self):
        flt = "ExifTool (exiftool*.exe);;Alle Dateien (*)" if sys.platform == "win32" \
            else "Alle Dateien (*)"
        fn, _ = QFileDialog.getOpenFileName(self, "ExifTool auswählen",
                                            os.path.dirname(self.et.text()), flt)
        if fn:
            self.et.setText(fn)


# --------------------------------------------------------------------------
# Hauptfenster
# --------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, cfg, et_cmd, et_ver):
        super().__init__()
        self.cfg = cfg
        self.et_ver = et_ver
        self.et = core.ExifTool(et_cmd)
        self.et_thumb = core.ExifTool(et_cmd)
        self.et_scan = core.ExifTool(et_cmd)
        self.tagged = {}          # pfad -> {"reg","op","type"} für getaggte Bilder
        self.ratings = {}         # pfad -> Sterne 0–5
        self.dirty = set()        # in diesem Ordner geschriebene Dateien (Scan ignoriert sie)
        self.scan_pool = QThreadPool(self)
        self.scan_pool.setMaxThreadCount(1)
        self.scan_signals = ScanSignals()
        self.scan_signals.done.connect(self.on_scan)
        self.et_preview = core.ExifTool(et_cmd)
        self.generation = 0
        self.tile = 170          # aktuelle Kachelgröße
        self.strip_mode = True   # Vorschau + Filmstreifen (sonst Kontaktabzug)
        self.prev_cache = OrderedDict()   # pfad -> große QPixmap
        self.prev_pending = set()
        self.prev_wanted = set()
        self.prev_pool = QThreadPool(self)
        self.prev_pool.setMaxThreadCount(1)
        self.prev_signals = PreviewSignals()
        self.prev_signals.loaded.connect(self.on_preview)
        self.prev_signals.full.connect(self.on_full)
        self.full_pending = None
        self.et_af = None                 # eigener ExifTool-Prozess für Fokuspunkte (bei Bedarf)
        self.af_cache = OrderedDict()     # pfad -> Fokuspunkte oder None
        self.af_pending = set()
        self.af_signals = AfSignals()
        self.af_signals.done.connect(self.on_af)
        self.items = {}          # pfad -> QListWidgetItem
        self.pixmaps = {}        # pfad -> QPixmap
        self.meta = {}           # pfad -> Metadaten
        self.meta_tags = {}      # pfad -> Menge zusätzlich gelesener Tags
        self.codes = core.CodeTable()
        self.data = core.DataTable()
        self.actable = core.AircraftTable()
        self.ac_record = None
        self.ac_origin = ""                 # csv / cache
        self.accache = core.AircraftCache(core.CONFIG_DIR / "aircraft_cache.csv")
        self.ac_misses = {}                 # norm(reg) -> "unknown" oder Fehlertext
        self.ac_pending = set()
        self.ac_apply_pending = None
        self.net_pool = QThreadPool(self)
        self.net_pool.setMaxThreadCount(2)
        self.net_signals = NetSignals()
        self.net_signals.done.connect(self.on_ac_online)
        self.ac_net_timer = QTimer(self)
        self.ac_net_timer.setSingleShot(True)
        self.ac_net_timer.setInterval(700)
        self.ac_net_timer.timeout.connect(self._ac_auto_fetch)
        self.folder = ""
        self.last_editor = None
        self.last_ac_editor = None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, min(6, (os.cpu_count() or 4) - 1)))
        self.thumb_signals = ThumbSignals()
        self.thumb_signals.loaded.connect(self.on_thumb)

        self.setWindowTitle(f"{core.APP_NAME} {core.APP_VERSION}")
        self.resize(*cfg.get("size", [1500, 900]))
        self._build_toolbar()
        self._build_menu()
        self._build_ui()
        self._restore()
        self.tabs.setCurrentWidget(self.ac_tab)   # AircraftTag ist beim Start immer aktiv
        QApplication.instance().focusChanged.connect(self._focus_changed)

    # ---- Aufbau -----------------------------------------------------------
    def _build_toolbar(self):
        tb = self.addToolBar("Hauptleiste")
        tb.setMovable(False)
        self.act_tree = QAction("◧ Ordner", self)
        self.act_tree.setCheckable(True)
        self.act_tree.setChecked(True)
        self.act_tree.setShortcut(QKeySequence("Ctrl+B"))
        self.act_tree.setToolTip("Ordnerspalte ein-/ausklappen (Strg+B)")
        self.act_tree.toggled.connect(self.set_tree_open)
        tb.addAction(self.act_tree)
        tb.addSeparator()
        a = self.act_open = QAction("Ordner öffnen…", self)
        a.setShortcut(QKeySequence.Open)
        a.triggered.connect(self.choose_folder)
        tb.addAction(a)
        a = self.act_refresh = QAction("Aktualisieren", self)
        a.setShortcut(QKeySequence(Qt.Key_F5))
        a.triggered.connect(lambda: self.load_folder(self.folder))
        tb.addAction(a)
        self.chk_recursive = QCheckBox("Unterordner einbeziehen")
        self.chk_recursive.toggled.connect(lambda: self.load_folder(self.folder))
        tb.addWidget(self.chk_recursive)
        tb.addSeparator()
        self.cmb_type = QComboBox()
        self.cmb_type.addItems(["JPEG und RAW", "nur JPEG", "nur RAW"])
        self.cmb_type.currentIndexChanged.connect(self.apply_filter)
        tb.addWidget(self.cmb_type)
        self.ed_filter = QLineEdit()
        self.ed_filter.setPlaceholderText("Dateiname filtern …")
        self.ed_filter.setClearButtonEnabled(True)
        self.ed_filter.setMaximumWidth(220)
        self.ed_filter.textChanged.connect(self.apply_filter)
        tb.addWidget(self.ed_filter)
        tb.addSeparator()
        tb.addWidget(QLabel(" Ansicht "))
        self.cmb_view = QComboBox()
        self.cmb_view.addItems(["Vorschau + Filmstreifen", "Kontaktabzug"])
        self.cmb_view.setToolTip("Strg+1 / Strg+2")
        self.cmb_view.currentIndexChanged.connect(lambda i: self.set_view(i == 0))
        tb.addWidget(self.cmb_view)
        for n in (0, 1):
            a = QAction(self)
            a.setShortcut(QKeySequence(f"Ctrl+{n + 1}"))
            a.triggered.connect(lambda _=False, n=n: self.cmb_view.setCurrentIndex(n))
            self.addAction(a)
        self.lbl_size = QLabel(" Größe ")
        self.act_lbl_size = tb.addWidget(self.lbl_size)
        self.sld = QSlider(Qt.Horizontal)
        self.sld.setRange(90, 320)
        self.sld.setMaximumWidth(140)
        self.sld.valueChanged.connect(self.set_icon_size)
        self.act_sld = tb.addWidget(self.sld)
        tb.addSeparator()
        self.chk_meta = QCheckBox("Metadaten einblenden")
        self.chk_meta.setToolTip("Vorhandene Metadaten unter der Vorschau anzeigen (Strg+I)")
        self.chk_meta.setChecked(self.cfg.get("show_meta", True))
        self.chk_meta.toggled.connect(self.toggle_meta)
        tb.addWidget(self.chk_meta)
        a = QAction(self)
        a.setShortcut(QKeySequence("Ctrl+T"))
        a.triggered.connect(lambda: self.focus_reg())
        self.addAction(a)
        a = QAction(self)
        a.setShortcut(QKeySequence("Ctrl+I"))
        a.triggered.connect(self.chk_meta.toggle)
        self.addAction(a)
        sp = QWidget()
        sp.setSizePolicy(sp.sizePolicy().horizontalPolicy().Expanding,
                         sp.sizePolicy().verticalPolicy())
        tb.addWidget(sp)
        a = self.act_settings = QAction("Einstellungen…", self)
        a.triggered.connect(self.open_settings)
        tb.addAction(a)
        tb.addSeparator()
        logo = LogoLabel(self.show_about)
        logo.setToolTip(f"{core.APP_NAME} {core.APP_VERSION} – Info")
        tb.addWidget(logo)

    def _build_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("&Datei")
        m.addAction(self.act_open)
        m.addAction(self.act_refresh)
        m.addSeparator()
        m.addAction(self.act_settings)
        m.addSeparator()
        a = m.addAction("Beenden")
        a.setShortcut(QKeySequence.Quit)
        a.triggered.connect(self.close)

        m = mb.addMenu("&Metadaten")
        a = m.addAction("Metadaten Template…")
        a.setShortcut(QKeySequence("Ctrl+M"))
        a.triggered.connect(self.open_template_dialog)
        self.act_tpl_apply = m.addAction("Template auf Auswahl anwenden")
        self.act_tpl_apply.setShortcut(QKeySequence("Ctrl+Shift+M"))
        self.act_tpl_apply.triggered.connect(self.apply_template)
        m.addSeparator()
        a = m.addAction("Template importieren…")
        a.triggered.connect(self.import_template)
        a = m.addAction("Template exportieren…")
        a.triggered.connect(self.export_template)
        self._update_tpl_menu()

        m = mb.addMenu("&Ansicht")
        self.act_af = m.addAction("Fokuspunkte anzeigen")
        self.act_af.setCheckable(True)
        self.act_af.setShortcut(QKeySequence("F"))
        self.act_af.setToolTip("Zeigt in der Vorschau die AF-Felder von Canon-Kameras (Taste F)")
        self.act_af.setChecked(bool(self.cfg.get("show_af", False)))
        self.act_af.toggled.connect(lambda _on: self._update_af())

        m = mb.addMenu("&Hilfe")
        a = m.addAction("Nach Updates suchen …")
        a.triggered.connect(self.check_updates)
        m.addSeparator()
        a = m.addAction(f"Über {core.APP_NAME}")
        a.triggered.connect(self.show_about)

    # ---- Metadaten Template -------------------------------------------------
    def template(self):
        tpl = self.cfg.get("meta_template")
        if not isinstance(tpl, dict) or "fields" not in tpl:
            tpl = dict(self.pad_state(), name="Standard", codes_csv=self.codes.path or "",
                       data_csv=self.data.path or "", data_key=self.data.key_column)
        return tpl

    def _update_tpl_menu(self):
        name = (self.cfg.get("meta_template") or {}).get("name") or "Standard"
        self.act_tpl_apply.setText(f"Template „{name}“ auf Auswahl anwenden")

    def open_template_dialog(self):
        d = TemplateDialog(self, self.template())
        if d.exec() == QDialog.Accepted:
            self.cfg["meta_template"] = d.state()
            self._save_cfg()
            self._update_tpl_menu()
            self.statusBar().showMessage(f"Template „{d.state().get('name')}“ gespeichert", 5000)

    def _save_cfg(self):
        try:
            save_json(CONFIG_FILE, self.cfg)
        except OSError:
            pass

    def import_template(self):
        st = template_from_file(self, self.folder)
        if st is not None:
            self.cfg["meta_template"] = st
            self._save_cfg()
            self._update_tpl_menu()
            self.statusBar().showMessage(f"Template „{st.get('name')}“ importiert", 5000)

    def export_template(self):
        template_to_file(self, self.template(), self.folder)

    def apply_template(self):
        paths = self.selected_paths()
        if not paths:
            QMessageBox.information(self, "Metadaten Template", "Bitte zuerst Bilder auswählen.")
            return
        tpl = self.template()
        name = tpl.get("name") or "Standard"
        fields = {k: v.get("text", "") for k, v in (tpl.get("fields") or {}).items()
                  if k in FIELD_BY_KEY and v.get("on")}
        extras, errors = (core.parse_extras(tpl.get("extra", "")) if tpl.get("extra_on") else ([], []))
        rename = (tpl.get("rename") or "").strip() if tpl.get("rename_on") else None
        if errors:
            QMessageBox.warning(self, "Metadaten Template", "Ungültige Zeilen unter „Weitere Tags“:\n\n"
                                + "\n".join(errors))
            return
        if not fields and not extras and not rename:
            QMessageBox.information(self, "Metadaten Template",
                                    f"Im Template „{name}“ ist kein Feld angehakt.")
            return
        missing = [f for f in (tpl.get("codes_csv"), tpl.get("data_csv")) if f and not os.path.isfile(f)]
        if missing and QMessageBox.question(
                self, "Metadaten Template", "Diese CSV-Datei(en) des Templates fehlen:\n\n"
                + "\n".join(missing) + "\n\nTrotzdem fortfahren?") != QMessageBox.Yes:
            return
        try:
            codes = core.CodeTable(tpl["codes_csv"]) if tpl.get("codes_csv") and \
                os.path.isfile(tpl["codes_csv"]) else core.CodeTable()
            data = core.DataTable(tpl["data_csv"], tpl.get("data_key")) if tpl.get("data_csv") and \
                os.path.isfile(tpl["data_csv"]) else core.DataTable()
        except Exception as e:  # noqa
            QMessageBox.warning(self, "Metadaten Template", f"CSV-Datei nicht lesbar:\n{e}")
            return
        ctx_kw = {"codes": codes, "data": data, "seq_start": int(tpl.get("seq_start", 1))}
        jobs, rows, n_warn, cols = self.build_jobs(paths, fields, extras, rename=rename, ctx_kw=ctx_kw)
        if n_warn:
            if PreviewDialog(self, rows, cols, n_warn, len(paths)).exec() != QDialog.Accepted:
                return
        elif QMessageBox.question(
                self, "Metadaten Template",
                f"Template „{name}“ auf {len(paths)} Datei(en) anwenden"
                + (" und die Dateien umbenennen?" if rename else "?")) != QMessageBox.Yes:
            return
        self.run_write(jobs, kw_mode=tpl.get("kw_mode") or "replace")

    # ---- Update über GitHub --------------------------------------------------
    def _update_repo(self):
        return self.cfg.get("update_repo") or upd.default_repo()

    def check_updates(self):
        repo = self._update_repo()
        if not repo:
            QMessageBox.information(
                self, "Updates", "Es ist noch kein GitHub-Repository eingestellt.\n\n"
                "Trage es unter Einstellungen → „Updates von GitHub“ ein, "
                "z. B. benutzer/AeroTagger.")
            return
        self.upd_sig = UpdateSignals()
        self.upd_sig.checked.connect(self._on_update_checked)
        self.statusBar().showMessage(f"Suche Updates in {repo} …")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self.net_pool.start(UpdateCheckTask(self.upd_sig, repo, self.cfg.get("github_token", "")))

    def _on_update_checked(self, rel, err):
        QApplication.restoreOverrideCursor()
        self.statusBar().clearMessage()
        if rel is None:
            QMessageBox.warning(self, "Updates", err)
            return
        if not upd.is_newer(rel["version"]):
            QMessageBox.information(
                self, "Updates", f"{core.APP_NAME} {core.APP_VERSION} ist aktuell.\n\n"
                f"Neueste Version auf GitHub: {rel['version']}")
            return
        kind, *rest = upd.plan(rel)
        box = QMessageBox(self)
        box.setWindowTitle("Update verfügbar")
        box.setIcon(QMessageBox.Information)
        box.setText(f"<b>{html.escape(rel['name'])}</b> ist verfügbar.<br>"
                    f"Installiert ist {core.APP_VERSION}.")
        info = rel["notes"] or "(keine Beschreibung)"
        if not kind:
            info += "\n\n" + rest[0]
        box.setInformativeText(info[:1500])
        b_now = box.addButton("Jetzt aktualisieren", QMessageBox.AcceptRole) if kind else None
        b_web = box.addButton("Auf GitHub ansehen", QMessageBox.ActionRole)
        box.addButton("Später", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() == b_web:
            QDesktopServices.openUrl(QUrl(rel["url"]))
        elif b_now is not None and box.clickedButton() == b_now:
            self._download_update(rel, kind, rest[0], rest[1])

    def _download_update(self, rel, kind, url, size):
        import tempfile
        dest = os.path.join(tempfile.gettempdir(), f"aerotagger-{rel['version']}-{kind}.zip")
        dlg = QProgressDialog(f"Lade {core.APP_NAME} {rel['version']} …", "Abbrechen", 0, 0, self)
        dlg.setWindowTitle("Update")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        task = UpdateDownloadTask(self.upd_sig, url, dest, self.cfg.get("github_token", ""))
        task.setAutoDelete(False)

        def prog(done, total):
            total = total or size
            if total:
                dlg.setMaximum(100)
                dlg.setValue(min(99, done * 100 // total))
            dlg.setLabelText(f"Lade {core.APP_NAME} {rel['version']} … {done / 1e6:.1f} MB")

        def finished(path, err):
            for s_, f_ in ((self.upd_sig.progress, prog), (self.upd_sig.downloaded, finished)):
                s_.disconnect(f_)
            dlg.close()
            if err:
                if not task.cancel:
                    QMessageBox.warning(self, "Update", err)
                return
            self._install_update(rel, kind, Path(path))

        self.upd_sig.progress.connect(prog)
        self.upd_sig.downloaded.connect(finished)
        dlg.canceled.connect(lambda: setattr(task, "cancel", True))
        self._upd_task = task
        self.net_pool.start(task)

    def _install_update(self, rel, kind, zip_path):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if kind == "frozen":
                bat = upd.install_frozen(zip_path)
            else:
                if upd.install_source(zip_path):
                    self.statusBar().showMessage("Installiere geänderte Abhängigkeiten …")
                    QApplication.processEvents()
                    upd.update_requirements()
        except upd.UpdateError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Update", str(e))
            return
        finally:
            try:
                zip_path.unlink()
            except OSError:
                pass
        QApplication.restoreOverrideCursor()
        if kind == "frozen":
            QMessageBox.information(self, "Update", f"{core.APP_NAME} wird jetzt beendet, "
                                    f"auf {rel['version']} aktualisiert und neu gestartet.")
            upd.run_helper(bat)
            self.close()
            return
        r = QMessageBox.question(self, "Update", f"{core.APP_NAME} {rel['version']} ist "
                                 "installiert. Jetzt neu starten?")
        if r == QMessageBox.Yes:
            cmd = upd.restart_command()
            if self.close():
                QProcess.startDetached(cmd[0], cmd[1:], str(core.APP_DIR))

    def show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"Über {core.APP_NAME}")
        box.setIconPixmap(app_icon().pixmap(QSize(64, 64)))
        box.setTextFormat(Qt.RichText)
        box.setText(f"<b style='font-size:15px'>{core.APP_NAME} {core.APP_VERSION}</b>")
        box.setInformativeText(
            "Metadaten für JPEG- und RAW-Dateien schreiben – mit Variablen, CSV-Tabellen "
            "und dem AircraftTag-Modus für Flugzeugfotos.<br><br>"
            f"ExifTool {self.et_ver} von Phil Harvey<br>"
            "Flugzeugdaten: <a href='https://www.adsbdb.com' style='color:#6fb3ff;'>adsbdb.com</a>, "
            "<a href='https://hexdb.io' style='color:#6fb3ff;'>hexdb.io</a>")
        box.exec()

    def _build_ui(self):
        split = QSplitter()
        self.setCentralWidget(split)
        self.split = split

        # Ordnerbaum
        self.fs = QFileSystemModel(self)
        self.fs.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)
        self.fs.setRootPath("")
        self.tree = QTreeView()
        self.tree.setModel(self.fs)
        for c in (1, 2, 3):
            self.tree.hideColumn(c)
        self.tree.setHeaderHidden(True)
        self.tree.selectionModel().currentChanged.connect(
            lambda idx, _old: self.load_folder(self.fs.filePath(idx), from_tree=True))
        self.tree_box = QWidget()
        tbl = QVBoxLayout(self.tree_box)
        tbl.setContentsMargins(0, 0, 0, 0)
        tbl.setSpacing(0)
        hdr = QWidget()
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(8, 2, 2, 2)
        lab = QLabel("Ordner")
        lab.setStyleSheet("color:#9aa1a9;")
        hl.addWidget(lab)
        hl.addStretch(1)
        b = QToolButton()
        b.setText("«")
        b.setAutoRaise(True)
        b.setToolTip("Ordnerspalte einklappen (Strg+B)")
        b.clicked.connect(lambda: self.set_tree_open(False))
        hl.addWidget(b)
        tbl.addWidget(hdr)
        tbl.addWidget(self.tree, 1)
        split.addWidget(self.tree_box)
        split.splitterMoved.connect(self._split_moved)

        # Bilder
        self.lst = QListWidget()
        self.lst.setViewMode(QListView.IconMode)
        self.lst.setResizeMode(QListView.Adjust)
        self.lst.setMovement(QListView.Static)
        self.lst.setSelectionMode(QListWidget.ExtendedSelection)
        self.lst.setUniformItemSizes(True)
        self.lst.setWordWrap(False)
        self.lst.setItemDelegate(ThumbDelegate(self))
        self.lst.currentItemChanged.connect(lambda *_: self.info_timer.start(60))
        self.lst.currentItemChanged.connect(
            lambda it, _old: it and self.lst.scrollToItem(it, QListView.EnsureVisible))
        self.lst.itemSelectionChanged.connect(self.update_counts)
        self.lst.itemDoubleClicked.connect(
            lambda it: QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.UserRole))))
        self.lst.viewport().installEventFilter(self)
        self.lst.installEventFilter(self)          # Tasten 0–5 = Sternbewertung

        # Mitte: große Vorschau + Metadaten oben, Filmstreifen unten
        self.preview = PreviewView(self)
        self.meta_panel = MetaPanel()
        self.meta_panel.setVisible(self.cfg.get("show_meta", True))
        self.preview_box = QWidget()
        pb = QVBoxLayout(self.preview_box)
        pb.setContentsMargins(0, 0, 0, 0)
        pb.setSpacing(0)
        pb.addWidget(self.preview, 1)
        pb.addWidget(self.meta_panel)
        self.mid = QSplitter(Qt.Vertical)
        self.mid.addWidget(self.preview_box)
        # Filterzeile über dem Filmstreifen
        fbar = QWidget()
        fl = QHBoxLayout(fbar)
        fl.setContentsMargins(10, 2, 10, 2)
        fl.setSpacing(6)
        lab = QLabel("Filter")
        lab.setStyleSheet("color:#9aa1a9;")
        fl.addWidget(lab)
        self.cmb_rop = QComboBox()
        for sym, key, tip in (("≥", "ge", "mindestens"), ("=", "eq", "genau"), ("≤", "le", "höchstens")):
            self.cmb_rop.addItem(sym, key)
            self.cmb_rop.setItemData(self.cmb_rop.count() - 1, f"Bewertung {tip}", Qt.ToolTipRole)
        self.cmb_rop.setToolTip("Bewertung mindestens / genau / höchstens")
        self.cmb_rop.currentIndexChanged.connect(lambda _i: self.apply_filter())
        fl.addWidget(self.cmb_rop)
        self.star_filter = StarFilter()
        self.star_filter.changed.connect(lambda _v: self.apply_filter())
        fl.addWidget(self.star_filter)
        self.btn_rf_clear = QToolButton()
        self.btn_rf_clear.setText("✕")
        self.btn_rf_clear.setAutoRaise(True)
        self.btn_rf_clear.setToolTip("Filter aufheben")
        self.btn_rf_clear.clicked.connect(lambda: (self.star_filter.set_value(0), self.apply_filter()))
        fl.addWidget(self.btn_rf_clear)
        fl.addStretch(1)
        self.lbl_filter = QLabel()
        self.lbl_filter.setStyleSheet("color:#9aa1a9;")
        fl.addWidget(self.lbl_filter)
        strip_box = QWidget()
        sb = QVBoxLayout(strip_box)
        sb.setContentsMargins(0, 0, 0, 0)
        sb.setSpacing(0)
        sb.addWidget(fbar)
        sb.addWidget(self.lst, 1)
        self.mid.addWidget(strip_box)
        self.mid.setStretchFactor(0, 1)
        self.mid.setStretchFactor(1, 0)
        self.mid.setCollapsible(0, False)
        self.mid.setCollapsible(1, False)
        self.mid.setSizes(self.cfg.get("mid", [620, 210]))
        split.addWidget(self.mid)
        self.info_timer = QTimer(self)
        self.info_timer.setSingleShot(True)
        self.info_timer.timeout.connect(self.show_info)

        # rechte Seite
        self.tabs = QTabWidget()
        pad = self._build_pad()
        self.ac_tab = self._build_ac()
        self.tabs.addTab(self.ac_tab, "AircraftTag")      # immer erster Reiter
        self.tabs.addTab(pad, "Metadaten schreiben")
        self.tabs.addTab(self._build_info(), "Bild-Info")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.tabs.addTab(self.log, "Protokoll")
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes(self.cfg.get("split", [250, 730, 520]))
        split.setCollapsible(1, False)
        split.setCollapsible(2, False)
        self.statusBar().showMessage(f"ExifTool {self.et_ver}")
        self.lbl_count = QLabel()
        self.statusBar().addPermanentWidget(self.lbl_count)

    def _build_pad(self):
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(6, 6, 6, 6)

        top = QHBoxLayout()
        top.addWidget(QLabel("Vorlage:"))
        self.cmb_tpl = QComboBox()
        self.cmb_tpl.setMinimumWidth(140)
        self.cmb_tpl.activated.connect(self.load_template)
        top.addWidget(self.cmb_tpl, 1)
        for text, fn in (("Speichern…", self.save_template),
                         ("Löschen", self.delete_template)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            top.addWidget(b)
        ol.addLayout(top)

        row = QHBoxLayout()
        self.btn_var = QToolButton()
        self.btn_var.setText("Variable einfügen")
        self.btn_var.setPopupMode(QToolButton.InstantPopup)
        self.btn_var.setMenu(self.build_var_menu(False))
        row.addWidget(self.btn_var)
        b = QPushButton("Aus Bild übernehmen")
        b.setToolTip("Füllt die Felder mit den Metadaten des aktuellen Bildes")
        b.clicked.connect(self.pad_from_image)
        row.addWidget(b)
        b = QPushButton("Leeren")
        b.clicked.connect(self.pad_clear)
        row.addWidget(b)
        row.addStretch(1)
        ol.addLayout(row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)
        self.checks, self.edits = {}, {}
        groups = []
        for f in FIELDS:
            if f.group not in groups:
                groups.append(f.group)
        for g in groups:
            box = QGroupBox(g)
            grid = QGridLayout(box)
            grid.setColumnStretch(1, 1)
            grid.setColumnMinimumWidth(0, 168)
            for r, f in enumerate([x for x in FIELDS if x.group == g]):
                cb = QCheckBox(f.label)
                cb.setToolTip("Angehakt = Feld wird geschrieben\nZiel: " + ", ".join(f.tags))
                if f.key == "rating":
                    ed = StarEdit()
                    ed.textEdited.connect(lambda _t, k=f.key: (self.checks[k].setChecked(True),
                                                               self.update_live()))
                elif f.multiline:
                    ed = QPlainTextEdit()
                    ed.setFixedHeight(74)
                    ed.setMinimumWidth(120)
                    ed.setTabChangesFocus(True)
                    ed.textChanged.connect(lambda k=f.key: self._edited(k))
                else:
                    ed = QLineEdit()
                    ed.textEdited.connect(lambda _t, k=f.key: self._edited(k))
                if f.hint and not isinstance(ed, StarEdit):
                    ed.setPlaceholderText(f.hint)
                grid.addWidget(cb, r, 0, Qt.AlignTop)
                grid.addWidget(ed, r, 1)
                self.checks[f.key], self.edits[f.key] = cb, ed
            il.addWidget(box)

        box = QGroupBox("Weitere Tags (ExifTool-Namen)")
        bl = QVBoxLayout(box)
        self.chk_extra = QCheckBox("schreiben – je Zeile  TAG = Wert")
        self.ed_extra = QPlainTextEdit()
        self.ed_extra.setFixedHeight(64)
        self.ed_extra.setMinimumWidth(120)
        self.ed_extra.setPlaceholderText("XMP-xmp:Rating = 5\nIPTC:Category = SPO\nEXIF:OwnerName = {creator}")
        self.ed_extra.textChanged.connect(lambda: self.chk_extra.setChecked(
            bool(self.ed_extra.toPlainText().strip())) if self.ed_extra.hasFocus() else None)
        bl.addWidget(self.chk_extra)
        bl.addWidget(self.ed_extra)
        il.addWidget(box)

        box = QGroupBox("CSV-Dateien und Optionen")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.ed_codes = QLineEdit()
        self.ed_codes.setReadOnly(True)
        self.ed_codes.setPlaceholderText("Kürzel;Ersetzung  →  im Text als =kürzel=")
        self.ed_data = QLineEdit()
        self.ed_data.setReadOnly(True)
        self.ed_data.setPlaceholderText("Tabelle mit Kopfzeile  →  {csv:Spaltenname}")
        for r, (label, ed, pick, clear) in enumerate((
                ("Kürzel-CSV", self.ed_codes, self.pick_codes, lambda: self.set_codes("")),
                ("Daten-CSV", self.ed_data, self.pick_data, lambda: self.set_data("")))):
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(ed, r, 1)
            b = QPushButton("…")
            b.setFixedWidth(32)
            b.clicked.connect(pick)
            grid.addWidget(b, r, 2)
            b = QPushButton("✕")
            b.setFixedWidth(32)
            b.clicked.connect(clear)
            grid.addWidget(b, r, 3)
        grid.addWidget(QLabel("Schlüsselspalte"), 2, 0)
        krow = QHBoxLayout()
        self.cmb_key = QComboBox()
        self.cmb_key.setToolTip("Spalte der Daten-CSV, die den Dateinamen enthält (mit oder ohne Endung)")
        self.cmb_key.activated.connect(lambda: (self.data.set_key(self.cmb_key.currentText()), self.update_counts()))
        krow.addWidget(self.cmb_key, 1)
        b = QPushButton("Spalten den Feldern zuordnen")
        b.setToolTip("Trägt {csv:Spalte} in alle Felder ein, deren Name einer CSV-Spalte entspricht")
        b.clicked.connect(self.map_csv_columns)
        krow.addWidget(b)
        grid.addLayout(krow, 2, 1, 1, 3)
        grid.addWidget(QLabel("Stichwörter"), 3, 0)
        orow = QHBoxLayout()
        self.cmb_kw = QComboBox()
        self.cmb_kw.addItem("vorhandene ersetzen", "replace")
        self.cmb_kw.addItem("zu vorhandenen hinzufügen", "append")
        orow.addWidget(self.cmb_kw, 1)
        orow.addWidget(QLabel("  {seq} beginnt bei"))
        self.spn_seq = QSpinBox()
        self.spn_seq.setRange(0, 999999)
        self.spn_seq.setValue(1)
        orow.addWidget(self.spn_seq)
        grid.addLayout(orow, 3, 1, 1, 3)
        il.addWidget(box)

        box, self.chk_rename, self.ed_rename = self._rename_box(
            "{isodate}_{filenamebase}", self.update_live)
        il.addWidget(box)
        il.addStretch(1)
        scroll.setWidget(inner)
        ol.addWidget(scroll, 1)

        self.lbl_live = QLabel()
        self.lbl_live.setWordWrap(True)
        self.lbl_live.setStyleSheet("color:#9fb4c7;")
        ol.addWidget(self.lbl_live)
        brow = QHBoxLayout()
        self.btn_preview = QPushButton("Vorschau…")
        self.btn_preview.clicked.connect(lambda: self.apply(preview=True))
        self.btn_apply = QPushButton("Auf Auswahl anwenden")
        self.btn_apply.setDefault(True)
        self.btn_apply.setShortcut(QKeySequence("Ctrl+Return"))
        self.btn_apply.setStyleSheet("font-weight:bold; padding:7px;")
        self.btn_apply.clicked.connect(lambda: self.apply(preview=False))
        brow.addWidget(self.btn_preview)
        brow.addWidget(self.btn_apply, 1)
        ol.addLayout(brow)
        return outer

    def _rename_box(self, default, on_change):
        """Gruppe „Umbenennen“: Checkbox + Vorlage für den neuen Dateinamen."""
        box = QGroupBox("Datei umbenennen")
        v = QVBoxLayout(box)
        chk = QCheckBox("beim Schreiben umbenennen")
        chk.setToolTip("Nach dem Schreiben der Metadaten erhält die Datei den unten definierten Namen.")
        ed = QLineEdit(default)
        ed.setPlaceholderText("z. B. {isodate}_{ac}_{frame}")
        ed.setToolTip("Neuer Dateiname mit Variablen, ohne Endung – die Endung bleibt erhalten.\n"
                      "Unerlaubte Zeichen werden zu „-“. Ist der Name schon vergeben, wird _2, _3 … "
                      "angehängt. Bei RAW-Dateien wird die XMP-Begleitdatei mit umbenannt.")
        ed.textChanged.connect(lambda _t: on_change())
        chk.toggled.connect(lambda _b: on_change())
        v.addWidget(chk)
        v.addWidget(ed)
        return box, chk, ed

    def rename_template(self, ac):
        chk, ed = (self.chk_ac_rename, self.ed_ac_rename) if ac else (self.chk_rename, self.ed_rename)
        return ed.text().strip() if chk.isChecked() and ed.text().strip() else None

    def build_var_menu(self, ac: bool, inserter=None):
        menu = QMenu(self)
        ins = inserter or (lambda t: self.insert_token(t, ac))
        for cat, entries in core.VARIABLES:
            sub = menu.addMenu(cat)
            for token, desc in entries:
                act = sub.addAction(f"{token}   –   {desc}")
                act.triggered.connect(lambda _=False, t=token: ins(t))
        sub = menu.addMenu("AircraftTags")
        cols = self.ac_columns()
        entries = [("{ac}", "Registrierung")] + [(f"{{ac:{c}}}", c) for c in cols]
        for token, desc in entries:
            act = sub.addAction(f"{token}   –   {desc}")
            act.triggered.connect(lambda _=False, t=token: ins(t))
        if ac:
            menu.insertMenu(menu.actions()[0], sub)   # im Flugzeugmodus ganz oben
        return menu

    # ---- Reiter AircraftTag -----------------------------------------------
    def _build_ac(self):
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(6, 6, 6, 6)

        box = QGroupBox("Registrierung")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        self.ed_reg = QLineEdit()
        f = self.ed_reg.font()
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        self.ed_reg.setFont(f)
        self.ed_reg.setPlaceholderText("z. B. OE-LBA")
        self.ed_reg.setToolTip("Registrierung eingeben und mit Enter in die ausgewählten Bilder "
                               "schreiben. Strg+T springt von überall hierher.")
        self.ac_model = QStringListModel(self)
        comp = QCompleter(self.ac_model, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setMaxVisibleItems(12)
        self.ed_reg.setCompleter(comp)
        self.ed_reg.textChanged.connect(self.ac_lookup)
        self.ed_reg.returnPressed.connect(self.ac_apply)
        row.addWidget(self.ed_reg, 1)
        self.btn_ac_apply = QPushButton("Schreiben")
        self.btn_ac_apply.setStyleSheet("font-weight:bold; padding:7px 12px;")
        self.btn_ac_apply.clicked.connect(self.ac_apply)
        row.addWidget(self.btn_ac_apply)
        v.addLayout(row)
        self.lbl_ac_status = QLabel()
        self.lbl_ac_status.setWordWrap(True)
        self.lbl_ac_status.setTextFormat(Qt.RichText)
        self.lbl_ac_status.linkActivated.connect(
            lambda href: self.ac_fetch(self.ed_reg.text(), force=True) if href == "refresh" else None)
        v.addWidget(self.lbl_ac_status)
        self.lbl_ac_detect = QLabel()
        self.lbl_ac_detect.setTextFormat(Qt.RichText)
        self.lbl_ac_detect.linkActivated.connect(
            lambda reg: (self.ed_reg.setText(reg), self.ed_reg.setFocus(), self.ed_reg.selectAll()))
        v.addWidget(self.lbl_ac_detect)
        self.tbl_ac = QTableWidget(0, 3)
        self.tbl_ac.setHorizontalHeaderLabels(["Feld", "Wert", "Variable"])
        hh = self.tbl_ac.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_ac.verticalHeader().hide()
        self.tbl_ac.verticalHeader().setDefaultSectionSize(22)
        self.tbl_ac.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl_ac.setToolTip("Klick auf die Variable (oder Doppelklick auf die Zeile) fügt sie in "
                               "das zuletzt bearbeitete Feld ein")
        self.tbl_ac.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tbl_ac.setSelectionMode(QTableWidget.NoSelection)
        self.tbl_ac.setFocusPolicy(Qt.NoFocus)
        self.tbl_ac.cellClicked.connect(lambda r, c: self._ac_table_insert(r) if c == 2 else None)
        self.tbl_ac.cellDoubleClicked.connect(lambda r, _c: self._ac_table_insert(r))
        self.ac_data_open = True
        self.btn_ac_data = QToolButton()
        self.btn_ac_data.setArrowType(Qt.DownArrow)
        self.btn_ac_data.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.btn_ac_data.setAutoRaise(True)
        self.btn_ac_data.setIconSize(QSize(10, 10))
        self.btn_ac_data.setStyleSheet("QToolButton { color:#9aa1a9; border:none; padding:1px 2px; }")
        self.btn_ac_data.setToolTip("Flugzeugdaten in der Tabelle ein- oder ausklappen")
        self.btn_ac_data.clicked.connect(self.toggle_ac_data)
        v.addWidget(self.btn_ac_data, 0, Qt.AlignLeft)
        v.addWidget(self.tbl_ac)
        ol.addWidget(box)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 6, 0)

        box = QGroupBox("Aufnahmedaten")
        form = QGridLayout(box)
        form.setColumnStretch(1, 1)
        form.addWidget(QLabel("Airport"), 0, 0)
        self.cmb_airport = QComboBox()
        self.cmb_airport.setEditable(True)
        self.cmb_airport.setInsertPolicy(QComboBox.NoInsert)
        self.cmb_airport.lineEdit().setPlaceholderText("z. B. Innsbruck (INN / LOWI)")
        self.cmb_airport.setToolTip("Variable {airport}. Bleibt gespeichert; zuletzt verwendete "
                                    "Airports stehen in der Liste.")
        self.cmb_airport.currentTextChanged.connect(lambda _t: self.update_ac_live())
        form.addWidget(self.cmb_airport, 0, 1, 1, 2)
        form.addWidget(QLabel("Fotograf"), 1, 0)
        self.ed_fotograf = QLineEdit()
        self.ed_fotograf.setPlaceholderText("Name des Fotografen")
        self.ed_fotograf.setToolTip("Variable {fotograf}. Bleibt gespeichert; ist das Feld leer, "
                                    "wird der Fotograf aus dem Bild übernommen.")
        self.ed_fotograf.textChanged.connect(lambda _t: self.update_ac_live())
        form.addWidget(self.ed_fotograf, 1, 1, 1, 2)
        form.addWidget(QLabel("Aufnahmedatum"), 2, 0)
        self.ed_aufnahme = QLineEdit()
        self.ed_aufnahme.setToolTip(
            "Variable {aufnahme}. Kommt automatisch aus den EXIF-Daten des jeweiligen Bildes – "
            "beim Schreiben mehrerer Bilder bekommt jedes sein eigenes Datum. Wer hier tippt, "
            "setzt ein festes Datum für alle; ↺ schaltet zurück auf automatisch.")
        self.ed_aufnahme.textEdited.connect(self._aufnahme_edited)
        form.addWidget(self.ed_aufnahme, 2, 1)
        self.btn_aufnahme = QPushButton("↺ aus Bild")
        self.btn_aufnahme.setToolTip("Aufnahmedatum wieder automatisch aus dem Bild nehmen")
        self.btn_aufnahme.clicked.connect(lambda: self._aufnahme_auto(True))
        form.addWidget(self.btn_aufnahme, 2, 2)
        self.lbl_aufnahme = QLabel()
        self.lbl_aufnahme.setStyleSheet("color:#8b929a;")
        form.addWidget(self.lbl_aufnahme, 3, 1, 1, 2)
        self.aufnahme_manual = False
        il.addWidget(box)

        box = QGroupBox("Beim Taggen schreiben")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        grid.setColumnMinimumWidth(0, 130)
        self.ac_checks, self.ac_edits = {}, {}
        for r, k in enumerate(AC_FIELDS):
            fdef = FIELD_BY_KEY[k]
            cb = QCheckBox(fdef.label)
            cb.setToolTip("Ziel: " + ", ".join(fdef.tags))
            if fdef.multiline:
                ed = QPlainTextEdit()
                ed.setFixedHeight(58)
                ed.setTabChangesFocus(True)
                ed.textChanged.connect(lambda k=k: self._ac_edited(k))
            else:
                ed = QLineEdit()
                ed.textEdited.connect(lambda _t, k=k: self._ac_edited(k))
            ed.setMinimumWidth(120)
            grid.addWidget(cb, r, 0, Qt.AlignTop)
            grid.addWidget(ed, r, 1)
            self.ac_checks[k], self.ac_edits[k] = cb, ed
        r = len(AC_FIELDS)
        self.chk_ac_extra = QCheckBox("Weitere Tags")
        self.chk_ac_extra.setToolTip("je Zeile  TAG = Wert")
        self.ed_ac_extra = QPlainTextEdit()
        self.ed_ac_extra.setFixedHeight(50)
        self.ed_ac_extra.setMinimumWidth(120)
        self.ed_ac_extra.setPlaceholderText("XMP-iptcExt:Event = {ac:Airline}")
        self.ed_ac_extra.textChanged.connect(lambda: (self.chk_ac_extra.setChecked(
            bool(self.ed_ac_extra.toPlainText().strip())) if self.ed_ac_extra.hasFocus() else None,
            self.update_ac_live()))
        grid.addWidget(self.chk_ac_extra, r, 0, Qt.AlignTop)
        grid.addWidget(self.ed_ac_extra, r, 1)
        orow = QHBoxLayout()
        self.btn_ac_var = QToolButton()
        self.btn_ac_var.setText("Variable einfügen")
        self.btn_ac_var.setPopupMode(QToolButton.InstantPopup)
        self.btn_ac_var.setMenu(self.build_var_menu(True))
        orow.addWidget(self.btn_ac_var)
        b = QPushButton("Standard")
        b.setToolTip("Feldvorlagen auf die Voreinstellung zurücksetzen")
        b.clicked.connect(lambda: self.set_ac_state({"fields": {}}, fields_only=True))
        orow.addWidget(b)
        orow.addStretch(1)
        grid.addLayout(orow, r + 1, 0, 1, 2)
        grid.addWidget(QLabel("Stichwörter"), r + 2, 0)
        self.cmb_ac_kw = QComboBox()
        self.cmb_ac_kw.addItem("zu vorhandenen hinzufügen", "append")
        self.cmb_ac_kw.addItem("vorhandene ersetzen", "replace")
        grid.addWidget(self.cmb_ac_kw, r + 2, 1)
        self.chk_ac_next = QCheckBox("nach dem Schreiben zum nächsten Bild springen")
        self.chk_ac_next.setToolTip("Gilt, wenn genau ein Bild ausgewählt ist. Die Registrierung "
                                    "bleibt stehen – Enter schreibt sie ins nächste Bild, "
                                    "Tippen ersetzt sie.")
        grid.addWidget(self.chk_ac_next, r + 3, 0, 1, 2)
        il.addWidget(box)

        box, self.chk_ac_rename, self.ed_ac_rename = self._rename_box(
            "{isodate}_{ac}_{frame}", self.update_ac_live)
        il.addWidget(box)

        box = QGroupBox("Flugzeugdaten-Quelle")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        grid.addWidget(QLabel("Quelle"), 0, 0)
        self.cmb_ac_src = QComboBox()
        self.cmb_ac_src.addItem("CSV-Datei (AircraftTags)", "csv")
        self.cmb_ac_src.addItem("Online: adsbdb.com / hexdb.io (mit lokalem Cache)", "online")
        self.cmb_ac_src.addItem("CSV-Datei, sonst online", "both")
        self.cmb_ac_src.setToolTip(
            "Online: Registrierung wird bei api.adsbdb.com nachgeschlagen, kennt adsbdb.com sie "
            "nicht, bei hexdb.io. Jedes Ergebnis landet "
            "im lokalen Cache und wird danach ohne Internet verwendet.")
        self.cmb_ac_src.currentIndexChanged.connect(self._ac_source_changed)
        grid.addWidget(self.cmb_ac_src, 0, 1, 1, 4)
        self.ed_ac_csv = QLineEdit()
        self.ed_ac_csv.setReadOnly(True)
        self.ed_ac_csv.setPlaceholderText("CSV mit Kopfzeile und einer Spalte für die Registrierung")
        self.ac_csv_widgets = []
        lab = QLabel("CSV-Datei")
        grid.addWidget(lab, 1, 0)
        grid.addWidget(self.ed_ac_csv, 1, 1)
        self.ac_csv_widgets += [lab, self.ed_ac_csv]
        for col, (text, tip, fn) in enumerate((
                ("…", "CSV-Datei wählen", self.pick_ac_csv),
                ("⟳", "Datei neu einlesen (nach Änderungen an der CSV)",
                 lambda: self.set_ac_csv(self.actable.path or "", self.actable.key_column)),
                ("✕", "CSV-Datei entfernen", lambda: self.set_ac_csv("")))):
            b = QPushButton(text)
            b.setFixedWidth(32)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            grid.addWidget(b, 1, 2 + col)
            self.ac_csv_widgets.append(b)
        lab = QLabel("Registrierung in")
        grid.addWidget(lab, 2, 0)
        self.cmb_ac_key = QComboBox()
        self.cmb_ac_key.setToolTip("Spalte, in der die Registrierung steht")
        self.cmb_ac_key.activated.connect(lambda: (self.actable.set_key(self.cmb_ac_key.currentText()),
                                                   self._ac_after_load()))
        grid.addWidget(self.cmb_ac_key, 2, 1, 1, 4)
        self.ac_csv_widgets += [lab, self.cmb_ac_key]
        lab = QLabel("Online-Cache")
        grid.addWidget(lab, 3, 0)
        self.lbl_ac_cache = QLabel()
        self.lbl_ac_cache.setToolTip(str(self.accache.file))
        grid.addWidget(self.lbl_ac_cache, 3, 1)
        b1 = QPushButton("Öffnen")
        b1.setToolTip("Cache-Tabelle (CSV) im Standardprogramm öffnen, z. B. Excel")
        b1.clicked.connect(self.open_ac_cache)
        b2 = QPushButton("Leeren")
        b2.setToolTip("Alle zwischengespeicherten Online-Ergebnisse löschen")
        b2.clicked.connect(self.clear_ac_cache)
        crow = QHBoxLayout()
        crow.addWidget(b1)
        crow.addWidget(b2)
        grid.addLayout(crow, 3, 2, 1, 3)
        self.ac_online_widgets = [lab, self.lbl_ac_cache, b1, b2]
        self.lbl_ac_note = QLabel("Daten: <a href='https://www.adsbdb.com' style='color:#6fb3ff;'>"
                                  "adsbdb.com</a>, ersatzweise <a href='https://hexdb.io' "
                                  "style='color:#6fb3ff;'>hexdb.io</a> – „Airline“ ist der "
                                  "eingetragene Halter.")
        self.lbl_ac_note.setWordWrap(True)
        self.lbl_ac_note.setOpenExternalLinks(True)
        self.lbl_ac_note.setStyleSheet("color:#8b929a;")
        grid.addWidget(self.lbl_ac_note, 4, 0, 1, 5)
        self.ac_online_widgets.append(self.lbl_ac_note)
        il.addWidget(box)
        il.addStretch(1)
        scroll.setWidget(inner)
        ol.addWidget(scroll, 1)

        self.lbl_ac_live = QLabel()
        self.lbl_ac_live.setWordWrap(True)
        self.lbl_ac_live.setStyleSheet("color:#9fb4c7;")
        ol.addWidget(self.lbl_ac_live)
        self.set_ac_state({})
        return outer

    # ---- Quelle: CSV / online -------------------------------------------
    def ac_source(self):
        return self.cmb_ac_src.currentData() if hasattr(self, "cmb_ac_src") else "csv"

    def ac_columns(self):
        """Spalten, die als {ac:…} gelten – je nach Quelle."""
        src = self.ac_source()
        if src == "csv":
            return list(self.actable.columns) or ["Registration"]
        if src == "online":
            return list(self.accache.columns)
        cols = list(self.actable.columns)
        low = {c.lower() for c in cols}
        return cols + [c for c in self.accache.columns if c.lower() not in low]

    def ac_keycol(self):
        if self.ac_source() != "online" and self.actable.key_column:
            return self.actable.key_column
        return "Registration"

    def _ac_source_changed(self):
        src = self.ac_source()
        for w in self.ac_csv_widgets:
            w.setEnabled(src != "online")
        for w in self.ac_online_widgets:
            w.setEnabled(src != "csv")
        self.btn_var.setMenu(self.build_var_menu(False))
        self.btn_ac_var.setMenu(self.build_var_menu(True))
        self._ac_after_load()

    def refresh_ac_completer(self):
        src = self.ac_source()
        regs = set()
        if src != "online":
            regs |= set(self.actable.registrations())
        if src != "csv":
            regs |= set(self.accache.registrations())
        self.ac_model.setStringList(sorted(regs, key=str.upper))
        self.lbl_ac_cache.setText(f"{len(self.accache)} Flugzeug{'e' if len(self.accache) != 1 else ''} gespeichert")

    def open_ac_cache(self):
        if not self.accache.file.exists():
            self.accache.save()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.accache.file)))

    def clear_ac_cache(self):
        if not len(self.accache):
            return
        if QMessageBox.question(self, "Online-Cache",
                                f"{len(self.accache)} zwischengespeicherte Flugzeuge löschen?") != QMessageBox.Yes:
            return
        if not self.accache.clear():
            QMessageBox.warning(self, "Online-Cache", "Die Cache-Datei konnte nicht geschrieben werden "
                                "(evtl. in Excel geöffnet?).")
        self.ac_misses.clear()
        self.refresh_ac_completer()
        self.ac_lookup()

    def ac_fetch(self, reg, force=False):
        reg = (reg or "").strip()
        k = core.AircraftTable.norm(reg)
        if not k or k in self.ac_pending:
            return
        self.ac_net_timer.stop()
        self.ac_misses.pop(k, None)
        self.ac_pending.add(k)
        self.net_pool.start(AcFetchTask(self, reg))
        self.ac_lookup()

    def _ac_auto_fetch(self):
        reg = self.ed_reg.text().strip()
        k = core.AircraftTable.norm(reg)
        if (self.ac_source() != "csv" and not self.ac_record and len(k) >= 4
                and k not in self.ac_misses and k not in self.ac_pending):
            self.ac_fetch(reg)

    def on_ac_online(self, query, rec, err):
        k = core.AircraftTable.norm(query)
        self.ac_pending.discard(k)
        if rec:
            if not self.accache.add(rec):
                self.logmsg("Online-Cache konnte nicht gespeichert werden "
                            f"({self.accache.file}) – evtl. in Excel geöffnet?")
            self.logmsg(f"{rec.get('Quelle') or 'online'}: {rec.get('Registration')} – {rec.get('Type')} "
                        f"({rec.get('Airline')})")
            self.refresh_ac_completer()
            self.btn_var.setMenu(self.build_var_menu(False))
            self.btn_ac_var.setMenu(self.build_var_menu(True))
        else:
            self.ac_misses[k] = err or "unknown"
            self.logmsg(f"Online-Abfrage {query}: " + (err or "weder bei adsbdb.com noch bei hexdb.io bekannt"))
        if core.AircraftTable.norm(self.ed_reg.text()) == k:
            self.ac_lookup()
        self.ac_detect()
        if self.ac_apply_pending == k:
            self.ac_apply_pending = None
            QTimer.singleShot(0, lambda: self.ac_apply(after_fetch=True))

    # ---- Aufnahmedaten ----------------------------------------------------
    def _aufnahme_edited(self, _text):
        self.aufnahme_manual = True
        self._aufnahme_label()
        self.update_ac_live()

    def _aufnahme_auto(self, on):
        self.aufnahme_manual = not on
        self.refresh_aufnahme()
        self.update_ac_live()

    def _aufnahme_label(self):
        self.lbl_aufnahme.setText("fest eingetragen – gilt für alle Bilder" if self.aufnahme_manual
                                  else "automatisch aus EXIF – je Bild")
        self.btn_aufnahme.setEnabled(self.aufnahme_manual)

    def refresh_aufnahme(self):
        """Füllt Aufnahmedatum (und leeren Fotografen) aus dem aktuellen Bild."""
        if not hasattr(self, "ed_aufnahme"):
            return
        p = self.current_path()
        m = self.meta.get(p, {}) if p else {}
        if not self.aufnahme_manual:
            d = core.parse_date(m) if m else None
            self.ed_aufnahme.setText(core._fmt_date(d, "%d.%m.%Y") if d else "")
        if p and not self.ed_fotograf.text().strip():
            cr = core.field_value(m, FIELD_BY_KEY["creator"])
            if cr:
                self.ed_fotograf.setText(cr)
        self._aufnahme_label()

    def ac_vars(self):
        if not hasattr(self, "ed_aufnahme"):
            return {}
        return {"airport": self.cmb_airport.currentText().strip(),
                "fotograf": self.ed_fotograf.text().strip(),
                "aufnahme": self.ed_aufnahme.text().strip() if self.aufnahme_manual else None}

    def remember_airport(self):
        a = self.cmb_airport.currentText().strip()
        if not a:
            return
        items = [self.cmb_airport.itemText(i) for i in range(self.cmb_airport.count())]
        items = [a] + [x for x in items if x.lower() != a.lower()][:19]
        self.cmb_airport.blockSignals(True)
        self.cmb_airport.clear()
        self.cmb_airport.addItems(items)
        self.cmb_airport.setCurrentText(a)
        self.cmb_airport.blockSignals(False)

    def ac_state(self):
        return {"source": self.ac_source(),
                "airport": self.cmb_airport.currentText().strip(),
                "airports": [self.cmb_airport.itemText(i) for i in range(self.cmb_airport.count())],
                "fotograf": self.ed_fotograf.text().strip(),
                "csv": self.actable.path or "", "key": self.actable.key_column,
                "reg": self.ed_reg.text(),
                "fields": {k: {"text": self.ac_text(k), "on": self.ac_checks[k].isChecked()}
                           for k in AC_FIELDS},
                "extra": self.ed_ac_extra.toPlainText(), "extra_on": self.chk_ac_extra.isChecked(),
                "kw_mode": self.cmb_ac_kw.currentData(), "next": self.chk_ac_next.isChecked(),
                "rename": self.ed_ac_rename.text(), "rename_on": self.chk_ac_rename.isChecked(),
                "data_open": self.ac_data_open}

    def set_ac_state(self, st, fields_only=False):
        flds = st.get("fields") or {}
        for k in AC_FIELDS:
            text, on = AC_DEFAULTS[k]
            if k in flds:
                text, on = flds[k].get("text", ""), bool(flds[k].get("on"))
            self.set_ac_text(k, text)
            self.ac_checks[k].setChecked(on)
        if not fields_only:
            self.ed_ac_extra.setPlainText(st.get("extra", ""))
            self.chk_ac_extra.setChecked(bool(st.get("extra_on", False)))
            self.cmb_ac_kw.setCurrentIndex(1 if st.get("kw_mode") == "replace" else 0)
            self.chk_ac_next.setChecked(st.get("next", True))
            self.ed_ac_rename.setText(st.get("rename", "{isodate}_{ac}_{frame}"))
            self.chk_ac_rename.setChecked(bool(st.get("rename_on", False)))
            self.ac_data_open = bool(st.get("data_open", True))
            self.cmb_airport.blockSignals(True)
            self.cmb_airport.clear()
            self.cmb_airport.addItems(st.get("airports", []))
            self.cmb_airport.setCurrentText(st.get("airport", ""))
            self.cmb_airport.blockSignals(False)
            self.ed_fotograf.setText(st.get("fotograf", ""))
            i = self.cmb_ac_src.findData(st.get("source", "csv"))
            self.cmb_ac_src.blockSignals(True)
            self.cmb_ac_src.setCurrentIndex(max(0, i))
            self.cmb_ac_src.blockSignals(False)
            for w in self.ac_csv_widgets:
                w.setEnabled(self.ac_source() != "online")
            for w in self.ac_online_widgets:
                w.setEnabled(self.ac_source() != "csv")
        self.update_ac_live()

    def ac_text(self, k):
        ed = self.ac_edits[k]
        return ed.toPlainText() if isinstance(ed, QPlainTextEdit) else ed.text()

    def set_ac_text(self, k, text):
        ed = self.ac_edits[k]
        ed.blockSignals(True)
        ed.setPlainText(text) if isinstance(ed, QPlainTextEdit) else ed.setText(text)
        ed.blockSignals(False)

    def _ac_edited(self, k):
        if self.ac_edits[k].hasFocus():
            self.ac_checks[k].setChecked(True)
        self.update_ac_live()

    def pick_ac_csv(self):
        fn, _ = QFileDialog.getOpenFileName(
            self, "AircraftTags-CSV wählen",
            os.path.dirname(self.actable.path or "") or self.folder,
            "CSV/Text (*.csv *.txt *.tsv);;Alle Dateien (*)")
        if fn:
            self.set_ac_csv(fn)

    def set_ac_csv(self, path, key=None, quiet=False):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.actable = core.AircraftTable(path, key) if path and os.path.isfile(path) \
                else core.AircraftTable()
        except Exception as e:  # noqa
            self.actable = core.AircraftTable()
            if not quiet:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "AircraftTags", f"Datei konnte nicht gelesen werden:\n{e}")
                QApplication.setOverrideCursor(Qt.WaitCursor)
        finally:
            QApplication.restoreOverrideCursor()
        self.cmb_ac_key.clear()
        self.cmb_ac_key.addItems(self.actable.columns)
        if self.actable.key_column:
            self.cmb_ac_key.setCurrentText(self.actable.key_column)
        self.btn_var.setMenu(self.build_var_menu(False))
        self.btn_ac_var.setMenu(self.build_var_menu(True))
        self._ac_after_load()

    def _ac_after_load(self):
        t = self.actable
        self.ed_ac_csv.setText(f"{os.path.basename(t.path)}  ({len(t)} Flugzeuge)" if t.path else "")
        self.ed_ac_csv.setToolTip(t.path or "")
        self.refresh_ac_completer()
        self.ac_lookup(self.ed_reg.text())
        self.ac_detect()

    def ac_lookup(self, text=None):
        reg = (self.ed_reg.text() if text is None else text).strip()
        src = self.ac_source()
        rec, origin = None, ""
        if reg and src in ("csv", "both"):
            rec = self.actable.find(reg)
            origin = "csv" if rec else ""
        if reg and rec is None and src in ("online", "both"):
            rec = self.accache.find(reg)
            origin = "cache" if rec else ""
        self.ac_record, self.ac_origin = rec, origin
        k = core.AircraftTable.norm(reg)
        online = src != "csv"
        if not reg:
            msg = ""
        elif rec:
            key = self.actable.key_column if origin == "csv" else "Registration"
            skip = {key, "Abgefragt", "Quelle", "PhotoURL", "Manufacturer", "Model", "ModeS"}
            info = [v for c, v in rec.items() if c not in skip and v][:3]
            msg = ("<span style='color:#7bd88f;'>✓ " + html.escape(rec.get(key) or reg) + "</span>"
                   + (" &nbsp;" + html.escape(" · ".join(info)) if info else ""))
            if origin == "cache":
                when = rec.get("Abgefragt", "")
                det = ", ".join(x for x in (rec.get("Quelle", ""),
                                            f"abgefragt {when}" if when else "") if x)
                msg += (f"<br><span style='color:#8b929a;'>aus dem Online-Cache"
                        + (f" ({html.escape(det)})" if det else "") + "</span>"
                        + (" &nbsp;⏳ aktualisiere …" if k in self.ac_pending else
                           " &nbsp;<a href='refresh' style='color:#6fb3ff;'>neu abfragen</a>"))
            elif src == "both":
                msg += " <span style='color:#8b929a;'>(CSV)</span>"
        elif online and k in self.ac_pending:
            msg = "<span style='color:#9fb4c7;'>⏳ Frage adsbdb.com / hexdb.io ab …</span>"
        elif online and k in self.ac_misses:
            why = self.ac_misses[k]
            if why == "unknown":
                msg = ("<span style='color:#ffb347;'>⚠ "
                       + ("Weder in der CSV noch bei adsbdb.com oder hexdb.io" if src == "both"
                          else "Weder bei adsbdb.com noch bei hexdb.io")
                       + " bekannt – es wird nur die Registrierung eingesetzt.</span>")
            else:
                msg = ("<span style='color:#ffb347;'>⚠ Online-Abfrage fehlgeschlagen: "
                       f"{html.escape(why)}</span> <a href='refresh' style='color:#6fb3ff;'>erneut versuchen</a>")
        elif online:
            msg = ("<span style='color:#8b929a;'>Wird online nachgeschlagen, sobald die Eingabe "
                   "kurz ruht (oder mit Enter).</span>")
            if len(k) >= 4:
                self.ac_net_timer.start()
        elif len(self.actable):
            msg = ("<span style='color:#ffb347;'>⚠ Nicht in der AircraftTags-Liste – es wird nur "
                   "die Registrierung eingesetzt.</span>")
        else:
            msg = ("<span style='color:#9aa1a9;'>Keine AircraftTags-CSV geladen – es wird nur die "
                   "Registrierung eingesetzt ({ac}).</span>")
        self.lbl_ac_status.setText(msg)
        self.update_ac_live()
        self.update_live()

    def refresh_ac_table(self):
        """Tabelle unter der Registrierung: Datensatz des Flugzeugs plus
        Airport, Fotograf, Aufnahmedatum – jeweils mit Variablenname."""
        if not hasattr(self, "tbl_ac"):
            return
        rows = []
        rec = self.ac_record
        reg = self.ed_reg.text().strip()
        if hasattr(self, "ed_aufnahme"):      # Aufnahmedaten oben – immer sichtbar
            av = self.ac_vars()
            datum = self.ed_aufnahme.text().strip()
            rows += [("Airport", av["airport"], "{airport}", True),
                     ("Fotograf", av["fotograf"], "{fotograf}", True),
                     ("Aufnahmedatum", datum + ("" if self.aufnahme_manual else "  (je Bild)")
                      if datum else "", "{aufnahme}", True)]
        if rec:
            rows += [(c, v, f"{{ac:{c}}}", False) for c, v in rec.items()]
        elif reg:
            rows.append(("Registrierung", reg.upper(), "{ac}", False))
        sb = self.tbl_ac.verticalScrollBar().value()
        self.tbl_ac.setRowCount(len(rows))
        for i, (lab, val, tok, own) in enumerate(rows):
            a = QTableWidgetItem(lab)
            if own:
                a.setForeground(QColor("#9fb4c7"))
            b = QTableWidgetItem(val)
            b.setToolTip(val)
            c = QTableWidgetItem(tok)
            c.setForeground(QColor("#6fb3ff"))
            c.setData(Qt.UserRole, tok)
            c.setToolTip("Klicken fügt " + tok + " ein")
            for col, it in enumerate((a, b, c)):
                self.tbl_ac.setItem(i, col, it)
        # Flugzeugdaten ein-/ausklappen; Airport, Fotograf, Datum bleiben sichtbar
        n_own = sum(1 for r in rows if r[3])
        n_rec = len(rows) - n_own if rec else 0
        for i, r in enumerate(rows):
            self.tbl_ac.setRowHidden(i, bool(rec) and not r[3] and not self.ac_data_open)
        if rec:
            src = "Online-Cache" if self.ac_origin == "cache" else "CSV"
            self.btn_ac_data.setText(f"Flugzeugdaten ({n_rec} Felder, {src})")
            self.btn_ac_data.setArrowType(Qt.DownArrow if self.ac_data_open else Qt.RightArrow)
            self.btn_ac_data.show()
        else:
            self.btn_ac_data.hide()
        self._fit_ac_table()
        self.tbl_ac.verticalScrollBar().setValue(sb)

    def _fit_ac_table(self, max_h=250):
        t = self.tbl_ac
        h = t.horizontalHeader().sizeHint().height() + 2 * t.frameWidth() + 2
        h += sum(t.rowHeight(i) for i in range(t.rowCount()) if not t.isRowHidden(i))
        t.setFixedHeight(min(h, max_h))

    def toggle_ac_data(self):
        self.ac_data_open = not self.ac_data_open
        self.refresh_ac_table()

    def _ac_table_insert(self, row):
        it = self.tbl_ac.item(row, 2)
        if it and it.data(Qt.UserRole):
            self.insert_token(it.data(Qt.UserRole), True)

    def ac_effective(self):
        """Datensatz für die Variablen: gefundener Eintrag oder – bei unbekannter
        Registrierung – nur die Registrierung selbst."""
        reg = self.ed_reg.text().strip() if hasattr(self, "ed_reg") else ""
        if not reg:
            return None
        if self.ac_record:
            return self.ac_record
        rec = {c: "" for c in self.ac_columns()}
        rec[self.ac_keycol()] = reg.upper()
        return rec

    def ac_summary(self):
        """(Registrierung, Operator, Typ) des aktuellen Flugzeugs für die
        Kennzeichnung – Spalten werden auch unter üblichen anderen Namen gefunden."""
        rec = self.ac_effective() or {}
        low = {k.lower(): v for k, v in rec.items()}

        def pick(*names):
            return next((low[n] for n in names if low.get(n)), "")
        reg = (rec.get(self.ac_keycol()) or low.get("registration") or self.ed_reg.text()).strip().upper()
        op = pick("airline", "operator", "betreiber", "halter", "owner", "registered owner",
                  "fluggesellschaft", "eigentümer")
        typ = pick("type", "typ", "muster", "flugzeugtyp", "aircraft", "model", "modell")
        return reg, op.strip(), typ.strip()

    def ac_detect(self):
        """Zeigt eine bereits im Bild stehende Registrierung an."""
        if not hasattr(self, "lbl_ac_detect"):
            return
        p = self.current_path()
        found = None
        src = self.ac_source()
        tables = ([self.actable] if src != "online" else []) + ([self.accache] if src != "csv" else [])
        info = self.tagged.get(p) if p else None
        if info and info.get("reg"):
            found = info["reg"]        # mit AeroTagger getaggt: Registrierung sicher bekannt
        elif p and p in self.meta and any(len(t) for t in tables):
            m = self.meta[p]
            text = " ".join(core.field_value(m, FIELD_BY_KEY[k])
                            for k in ("keywords", "title", "headline"))
            for t in tables:
                found = t.find_in_text(text)
                if found:
                    break
        if found:
            same = core.AircraftTable.norm(found) == core.AircraftTable.norm(self.ed_reg.text())
            self.lbl_ac_detect.setText(
                f"<span style='color:#9aa1a9;'>Im Bild bereits eingetragen:</span> <b>{html.escape(found)}</b>"
                + ("" if same else f" &nbsp;<a href='{html.escape(found)}' style='color:#6fb3ff;'>übernehmen</a>"))
        else:
            self.lbl_ac_detect.setText("")

    def ac_templates(self):
        fields = {k: self.ac_text(k) for k in AC_FIELDS if self.ac_checks[k].isChecked()}
        extras, errors = [], []
        if self.chk_ac_extra.isChecked():
            extras, errors = core.parse_extras(self.ed_ac_extra.toPlainText())
        return fields, extras, errors

    def update_ac_live(self):
        if not hasattr(self, "lbl_ac_live"):
            return
        self.refresh_ac_table()
        p = self.current_path()
        if not p or p not in self.meta or not self.ed_reg.text().strip():
            self.lbl_ac_live.setText("")
            return
        fields, extras, errors = self.ac_templates()
        ctx = self.make_context(p, 0, 1)
        parts, warn = [], []
        for k, t in fields.items():
            v, w = ctx.resolve(t)
            warn += w
            v = core.tidy_line(v) if not FIELD_BY_KEY[k].multiline else v
            if FIELD_BY_KEY[k].is_list:
                v = ", ".join(core.split_list(v))
            parts.append(f"<b>{FIELD_BY_KEY[k].label}:</b> "
                         + (html.escape(v).replace("\n", " ⏎ ") or "<i>bleibt unverändert</i>"))
        rn = self.rename_template(True)
        if rn:
            nm, w = ctx.resolve(rn)
            warn += w
            stem = core.clean_filename(nm, os.path.splitext(p)[1])
            parts.append("<b>Neuer Name:</b> " + (html.escape(stem + os.path.splitext(p)[1]) if stem
                                                  else "<span style='color:#ffb347'>leer – wird nicht umbenannt</span>"))
        text = f"<b>{html.escape(os.path.basename(p))}</b> → " + " · ".join(parts[:8]) if parts else ""
        if warn or errors:
            text += ("<br><span style='color:#ffb347'>⚠ "
                     + html.escape("; ".join(dict.fromkeys(warn + ["Ungültige Zeile: " + e for e in errors])))
                     + "</span>")
        self.lbl_ac_live.setText(text)

    def focus_reg(self):
        self.tabs.setCurrentWidget(self.ac_tab)
        self.ed_reg.setFocus()
        self.ed_reg.selectAll()

    def ac_apply(self, after_fetch=False):
        reg = self.ed_reg.text().strip()
        if not reg:
            self.ed_reg.setFocus()
            return
        paths = self.selected_paths()
        if not paths:
            QMessageBox.information(self, "AircraftTag", "Bitte zuerst ein oder mehrere Bilder auswählen.")
            return
        fields, extras, errors = self.ac_templates()
        if errors:
            QMessageBox.warning(self, "Weitere Tags", "Diese Zeilen sind ungültig "
                                "(erwartet: TAG = Wert):\n\n" + "\n".join(errors))
            return
        rename = self.rename_template(True)
        if not fields and not extras and not rename:
            QMessageBox.information(self, "AircraftTag",
                                    "Unter „Beim Taggen schreiben“ ist kein Feld angehakt.")
            return
        src = self.ac_source()
        k = core.AircraftTable.norm(reg)
        if src != "csv" and not self.ac_record:
            why = self.ac_misses.get(k)
            # noch nicht (erfolgreich) abgefragt: erst online nachschlagen, dann weiter
            if k in self.ac_pending or why is None or (why != "unknown" and not after_fetch):
                self.ac_apply_pending = k
                self.ac_fetch(reg)
                return
        if not self.ac_record and (len(self.actable) or src != "csv"):
            why = self.ac_misses.get(k)
            if src != "csv" and why and why != "unknown":
                head = f"Die Online-Abfrage für „{reg}“ ist fehlgeschlagen:\n{why}"
            elif src == "online":
                head = f"„{reg}“ ist weder bei adsbdb.com noch bei hexdb.io bekannt."
            elif src == "both":
                head = f"„{reg}“ steht weder in der AircraftTags-Liste noch bei adsbdb.com oder hexdb.io."
            else:
                head = f"„{reg}“ steht nicht in der AircraftTags-Liste."
            if QMessageBox.question(
                    self, "AircraftTag", head + "\n\nTrotzdem schreiben? Es wird nur die "
                    "Registrierung eingesetzt, die übrigen Spalten bleiben leer.") != QMessageBox.Yes:
                return
        t_reg, t_op, t_type = self.ac_summary()
        jobs, rows, n_warn, cols = self.build_jobs(
            paths, fields, extras, tidy=True, skip_empty=True, rename=rename,
            ops_fn=lambda p: core.tag_ops(self.meta.get(p, {}), t_reg, t_op, t_type))
        if n_warn:
            if PreviewDialog(self, rows, cols, n_warn, len(paths),
                             empty_note="Leere Zellen werden nicht geschrieben.").exec() != QDialog.Accepted:
                return
        elif len(paths) > 1:
            if QMessageBox.question(
                    self, "AircraftTag",
                    f"{reg.upper()} in {len(paths)} Bilder schreiben"
                    + (" und die Dateien umbenennen?" if rename else "?")) != QMessageBox.Yes:
                return
        self.remember_airport()
        single = len(paths) == 1
        self.run_write(jobs, kw_mode=self.cmb_ac_kw.currentData(),
                       on_done=lambda ok: self._ac_done(ok, single))

    def _ac_done(self, all_ok, single):
        if all_ok and single and self.chk_ac_next.isChecked():
            cur = self.lst.currentRow()
            for r in range(cur + 1, self.lst.count()):
                if not self.lst.item(r).isHidden():
                    self.lst.clearSelection()
                    self.lst.setCurrentRow(r)
                    self.lst.item(r).setSelected(True)
                    break
        self.ed_reg.setFocus()
        self.ed_reg.selectAll()

    def _build_info(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        self.tbl = QTableWidget(0, 2)
        self.tbl.setHorizontalHeaderLabels(["Feld", "Inhalt"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.verticalHeader().hide()
        self.tbl.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tbl.setWordWrap(True)
        lay.addWidget(self.tbl, 1)
        return w

    # ---- Zustand ----------------------------------------------------------
    # ---- Ordnerspalte ein-/ausklappen --------------------------------------
    def set_tree_open(self, on):
        if not hasattr(self, "tree_box"):
            return
        sz = self.split.sizes()
        if not on:
            if self.tree_box.isVisible() and sz[0] > 40:
                self.cfg["tree_w"] = sz[0]
            self.tree_box.hide()
            self.lst.setFocus()
        else:
            self.tree_box.show()
            sz = self.split.sizes()
            if sz[0] < 60:
                w = int(self.cfg.get("tree_w", 250))
                self.split.setSizes([w, max(300, sz[1] - w), sz[2]])
            self.tree.scrollTo(self.tree.currentIndex())
        self.act_tree.blockSignals(True)
        self.act_tree.setChecked(on)
        self.act_tree.blockSignals(False)

    def _split_moved(self, _pos, index):
        """Spalte per Trennlinie ganz zugezogen bzw. wieder aufgezogen."""
        if index != 1:
            return
        w = self.split.sizes()[0]
        if w == 0 and self.act_tree.isChecked():
            self.tree_box.hide()
            self.act_tree.blockSignals(True)
            self.act_tree.setChecked(False)
            self.act_tree.blockSignals(False)
        elif w > 40:
            self.cfg["tree_w"] = w

    def _restore(self):
        c = self.cfg
        self.sld.setValue(c.get("icon", 170))
        strip = c.get("view", "strip") == "strip"
        self.cmb_view.blockSignals(True)
        self.cmb_view.setCurrentIndex(0 if strip else 1)
        self.cmb_view.blockSignals(False)
        self.set_view(strip)
        self.chk_recursive.blockSignals(True)
        self.chk_recursive.setChecked(c.get("recursive", False))
        rf = c.get("rating_filter") or {}
        self.cmb_rop.blockSignals(True)
        self.cmb_rop.setCurrentIndex(max(0, self.cmb_rop.findData(rf.get("op", "ge"))))
        self.cmb_rop.blockSignals(False)
        self.star_filter.set_value(rf.get("n", 0))
        self.chk_recursive.blockSignals(False)
        self.set_pad_state(c.get("pad", {}))
        self.set_codes(c.get("codes_csv", ""), quiet=True)
        self.set_data(c.get("data_csv", ""), c.get("data_key"), quiet=True)
        ac = c.get("ac", {})
        self.set_ac_state(ac)
        self.set_ac_csv(ac.get("csv", ""), ac.get("key"), quiet=True)
        self._ac_source_changed()
        self.ed_reg.setText(ac.get("reg", ""))
        self.refresh_templates()
        start = c.get("folder") or str(Path.home())
        if not os.path.isdir(start):
            start = str(Path.home())
        self.load_folder(start)
        if not c.get("tree_open", True):
            self.set_tree_open(False)

    def closeEvent(self, ev):
        self.generation += 1
        self.pool.clear()
        self.pool.waitForDone(3000)
        self.prev_wanted = set()
        self.prev_pool.clear()
        self.prev_pool.waitForDone(3000)
        self.net_pool.waitForDone(2000)
        self.scan_pool.clear()
        self.scan_pool.waitForDone(3000)
        c = self.cfg
        if self.strip_mode:
            c["mid"] = self.mid.sizes()
        c.update(size=[self.width(), self.height()], split=self.split.sizes(),
                 tree_open=self.act_tree.isChecked(),
                 view="strip" if self.strip_mode else "grid",
                 show_meta=self.chk_meta.isChecked(), ac=self.ac_state(),
                 rating_filter={"n": self.star_filter.value, "op": self.cmb_rop.currentData()},
                 icon=self.sld.value(), show_af=self.act_af.isChecked(), recursive=self.chk_recursive.isChecked(),
                 folder=self.folder, pad=self.pad_state(),
                 codes_csv=self.codes.path or "", data_csv=self.data.path or "",
                 data_key=self.data.key_column)
        try:
            save_json(CONFIG_FILE, c)
        except OSError:
            pass
        self.et.close()
        self.et_thumb.close()
        self.et_preview.close()
        self.et_scan.close()
        if self.et_af is not None:
            self.et_af.close()
        super().closeEvent(ev)

    def pad_state(self):
        return {"fields": {k: {"text": self.field_text(k),
                               "on": self.checks[k].isChecked()} for k in self.edits},
                "extra": self.ed_extra.toPlainText(),
                "extra_on": self.chk_extra.isChecked(),
                "kw_mode": self.cmb_kw.currentData(),
                "seq_start": self.spn_seq.value(),
                "rename": self.ed_rename.text(), "rename_on": self.chk_rename.isChecked()}

    def set_pad_state(self, st):
        for k, ed in self.edits.items():
            v = st.get("fields", {}).get(k, {})
            self.set_field_text(k, v.get("text", ""))
            self.checks[k].setChecked(bool(v.get("on", False)))
        self.ed_extra.setPlainText(st.get("extra", ""))
        self.chk_extra.setChecked(bool(st.get("extra_on", False)))
        self.cmb_kw.setCurrentIndex(1 if st.get("kw_mode") == "append" else 0)
        self.spn_seq.setValue(int(st.get("seq_start", 1)))
        self.ed_rename.setText(st.get("rename", "{isodate}_{filenamebase}"))
        self.chk_rename.setChecked(bool(st.get("rename_on", False)))

    def field_text(self, key):
        ed = self.edits[key]
        return ed.toPlainText() if isinstance(ed, QPlainTextEdit) else ed.text()

    def set_field_text(self, key, text):
        ed = self.edits[key]
        ed.blockSignals(True)
        ed.setPlainText(text) if isinstance(ed, QPlainTextEdit) else ed.setText(text)
        ed.blockSignals(False)

    def _edited(self, key):
        if self.edits[key].hasFocus():
            self.checks[key].setChecked(True)
        self.update_live()

    def _focus_changed(self, _old, new):
        if not isinstance(new, (QLineEdit, QPlainTextEdit)):
            return
        if new in self.edits.values() or new is self.ed_extra or new is self.ed_rename:
            self.last_editor = new
        elif new in self.ac_edits.values() or new in (self.ed_ac_extra, self.ed_ac_rename):
            self.last_ac_editor = new

    def insert_token(self, token, ac=False):
        if ac:
            ed = self.last_ac_editor or self.ac_edits["headline"]
            edits, checks, extra, chk_extra = self.ac_edits, self.ac_checks, self.ed_ac_extra, self.chk_ac_extra
        else:
            ed = self.last_editor or self.edits["caption"]
            edits, checks, extra, chk_extra = self.edits, self.checks, self.ed_extra, self.chk_extra
        if isinstance(ed, QPlainTextEdit):
            ed.insertPlainText(token)
        else:
            ed.insert(token)
        for k, e in edits.items():
            if e is ed:
                checks[k].setChecked(True)
        if ed is extra:
            chk_extra.setChecked(True)
        ed.setFocus()
        self.update_live()
        self.update_ac_live()

    def logmsg(self, text):
        self.log.appendPlainText(text)

    # ---- Ordner und Bilder ------------------------------------------------
    def choose_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Ordner öffnen", self.folder)
        if d:
            self.load_folder(d)

    def load_folder(self, folder, from_tree=False):
        if not folder or not os.path.isdir(folder):
            return
        self.folder = folder
        self.generation += 1
        self.pool.clear()
        if not from_tree:
            idx = self.fs.index(folder)
            self.tree.selectionModel().blockSignals(True)
            self.tree.setCurrentIndex(idx)
            self.tree.selectionModel().blockSignals(False)
            self.tree.scrollTo(idx)
        self.lst.clear()
        self.items.clear()
        self.pixmaps.clear()
        self.meta.clear()
        self.meta_tags.clear()
        self.prev_cache.clear()
        self.tagged.clear()
        self.ratings.clear()
        self.dirty.clear()
        self.scan_pool.clear()
        self.prev_wanted = set()
        self.prev_pool.clear()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            paths = core.list_images(folder, self.chk_recursive.isChecked())
        finally:
            QApplication.restoreOverrideCursor()
        for p in paths:
            name = os.path.relpath(p, folder) if self.chk_recursive.isChecked() \
                else os.path.basename(p)
            it = QListWidgetItem(name)
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.lst.addItem(it)
            self.items[p] = it
        self.apply_filter()
        if self.lst.count() and self.strip_mode:
            first = next((self.lst.item(i) for i in range(self.lst.count())
                          if not self.lst.item(i).isHidden()), None)
            if first:
                self.lst.setCurrentItem(first)
        for p in paths:
            self.pool.start(ThumbTask(self, self.generation, p))
        if paths:
            self.scan_pool.start(MetaScanTask(self, self.generation, paths))
        self.setWindowTitle(f"{folder} – {core.APP_NAME}")
        self.update_counts()
        self.show_info()

    def on_thumb(self, gen, path, img):
        if gen != self.generation or img.isNull():
            return
        it = self.items.get(path)
        if it is None:
            return
        self.pixmaps[path] = QPixmap.fromImage(img)
        self.lst.update(self.lst.indexFromItem(it))
        cur = self.lst.currentItem()
        if cur is it:
            self.show_info()

    def set_icon_size(self, _v=None):
        self.update_tile()

    def toggle_meta(self, on):
        self.meta_panel.setVisible(on)
        if on:
            self.update_preview()

    # ---- Ansicht: Filmstreifen / Kontaktabzug -----------------------------
    def set_view(self, strip: bool):
        if self.strip_mode and not strip and self.preview_box.isVisible():
            self.cfg["mid"] = self.mid.sizes()
        self.strip_mode = strip
        self.preview_box.setVisible(strip)
        self.lst.setFlow(QListView.LeftToRight)
        self.lst.setWrapping(not strip)
        self.lst.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOn if strip else Qt.ScrollBarAsNeeded)
        self.lst.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if strip else Qt.ScrollBarAsNeeded)
        self.lst.setMinimumHeight(110 if strip else 0)
        # Größenregler nur im Kontaktabzug; im Filmstreifen bestimmt dessen Höhe die Bildgröße
        self.act_sld.setVisible(not strip)
        self.act_lbl_size.setVisible(not strip)
        self.sld.setToolTip("Größe der Bilder im Kontaktabzug")
        if strip:
            self.mid.setSizes(self.cfg.get("mid", [620, 210]))
        self.update_tile(force=True)
        QTimer.singleShot(0, self._scroll_to_current)
        self.show_info()

    def _scroll_to_current(self):
        it = self.lst.currentItem()
        if it:
            self.lst.scrollToItem(it, QListView.PositionAtCenter if self.strip_mode
                                  else QListView.EnsureVisible)

    def update_tile(self, force=False):
        if self.strip_mode:
            h = self.lst.viewport().height()
            v = max(60, min(420, h - 36))
        else:
            v = self.sld.value()
        if v != self.tile or force:
            self.tile = v
            self.lst.setGridSize(QSize(v + 16, v + 32))
            self.lst.doItemsLayout()
            if self.strip_mode:
                QTimer.singleShot(0, self._scroll_to_current)

    _RATING_KEYS = {Qt.Key_0: 0, Qt.Key_1: 1, Qt.Key_2: 2, Qt.Key_3: 3, Qt.Key_4: 4, Qt.Key_5: 5}

    def eventFilter(self, obj, ev):
        if obj is self.lst and ev.type() == QEvent.KeyPress:
            mods = ev.modifiers() & ~Qt.KeypadModifier
            if ev.key() in self._RATING_KEYS and mods == Qt.NoModifier and not ev.isAutoRepeat():
                self.set_rating(self._RATING_KEYS[ev.key()])
                return True
        if obj is self.lst.viewport():
            if ev.type() == QEvent.Resize and self.strip_mode:
                QTimer.singleShot(0, self.update_tile)
            elif ev.type() == QEvent.Wheel and self.strip_mode:
                d = ev.angleDelta()
                delta = d.y() if abs(d.y()) >= abs(d.x()) else d.x()
                bar = self.lst.horizontalScrollBar()
                bar.setValue(bar.value() - int(delta / 120 * (self.tile + 16)))
                return True
        return super().eventFilter(obj, ev)

    # ---- große Vorschau ---------------------------------------------------
    def visible_paths(self):
        return [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())
                if not self.lst.item(i).isHidden()]

    def request_preview(self, path, visible):
        i = visible.index(path) if path in visible else -1
        neighbours = [visible[j] for j in (i + 1, i - 1) if 0 <= j < len(visible)] if i >= 0 else []
        self.prev_wanted = {path, *neighbours}
        for prio, p in ((2, path), *[(1, n) for n in neighbours]):
            if p in self.prev_cache:
                self.prev_cache.move_to_end(p)
            elif p not in self.prev_pending:
                self.prev_pending.add(p)
                self.prev_pool.start(PreviewTask(self, p), prio)

    def request_full(self, path):
        """Volle Auflösung für die Lupe laden (nur für das aktuelle Bild)."""
        pv = self.preview
        if not path or (pv.full_path == path and pv.full_pm is not None) or self.full_pending == path:
            return
        big = self.prev_cache.get(path)
        if big is not None and not core.is_raw(path) and max(big.width(), big.height()) < PREVIEW_PX:
            pv.set_full(path, big)        # kleines JPEG: Vorschau ist schon volle Auflösung
            return
        self.full_pending = path
        self.prev_pool.start(FullTask(self, path), 5)

    def on_full(self, path, img):
        if self.full_pending == path:
            self.full_pending = None
        if not img.isNull() and path == self.preview.path:
            self.preview.set_full(path, QPixmap.fromImage(img))

    def on_preview(self, path, img):
        self.prev_pending.discard(path)
        if img.isNull():
            if path == self.current_path() and path in self.prev_wanted:
                self.update_preview(final_failed=True)
            return
        self.prev_cache[path] = QPixmap.fromImage(img)
        self.prev_cache.move_to_end(path)
        while len(self.prev_cache) > PREVIEW_CACHE:
            victim = next((k for k in self.prev_cache if k not in self.prev_wanted),
                          next(iter(self.prev_cache)))
            self.prev_cache.pop(victim)
        if path == self.current_path():
            self.update_preview()

    def update_preview(self, final_failed=False):
        if not self.strip_mode:
            return
        p = self.current_path()
        if not p:
            self.preview.show_image(None, None, True)
            self.meta_panel.clear_meta()
            return
        visible = self.visible_paths()
        counter = f"{visible.index(p) + 1} / {len(visible)}" if p in visible else ""
        m = self.meta.get(p, {})
        if self.chk_meta.isChecked():
            self.meta_panel.show_meta(m)
        ctx = core.Context(p, m)
        when = ctx.resolve("{date}  {time}")[0].strip()
        title = os.path.basename(p) + (f"   ·   {when}" if when else "")
        expo = []
        if core.lookup(m, "ExposureTime"):
            expo = [ctx.value("shutter", "") + " s", "f/" + ctx.value("aperture", ""),
                    "ISO " + ctx.value("iso", ""), ctx.value("focallength", "")]
        info = " · ".join(x for x in [self._camera(ctx), ctx.value("lens", ""), *expo,
                                      ctx.resolve("{width} × {height} px")[0]
                                      if core.lookup(m, "ImageWidth") else ""] if x.strip())
        big = self.prev_cache.get(p)
        if big is not None:
            self.preview.show_image(p, big, True, title, counter, info, tag=core.tag_info(m),
                                    rating=self.ratings.get(p, core.rating_of(m)))
        else:
            self.preview.show_image(p, self.pixmaps.get(p), final_failed, title, counter, info,
                                    tag=core.tag_info(m), rating=self.ratings.get(p, core.rating_of(m)))
            if not final_failed:
                self.request_preview(p, visible)
        self._update_af()

    # ---- Fokuspunkte ------------------------------------------------------------
    def _update_af(self):
        on = self.act_af.isChecked()
        p = self.preview.path
        if not on or not p:
            self.preview.set_af(on)
            return
        if p in self.af_cache:
            self.preview.set_af(True, p, self.af_cache[p])
            return
        self.preview.set_af(True, p, None, loading=True)
        if p not in self.af_pending:
            if self.et_af is None:
                self.et_af = core.ExifTool(self.et.cmd)
            self.af_pending.add(p)
            self.net_pool.start(AfTask(self, p))

    def on_af(self, path, data):
        self.af_pending.discard(path)
        if path != self.preview.path:
            return                      # weitergeblättert – beim nächsten Mal neu lesen
        self.af_cache[path] = data
        while len(self.af_cache) > 300:
            self.af_cache.popitem(last=False)
        if self.act_af.isChecked():
            self.preview.set_af(True, path, data)

    def apply_filter(self):
        text = self.ed_filter.text().strip().lower()
        mode = self.cmb_type.currentIndex()
        n = self.star_filter.value if hasattr(self, "star_filter") else 0
        op = self.cmb_rop.currentData() if hasattr(self, "cmb_rop") else "ge"
        shown = 0
        for p, it in self.items.items():
            raw = core.is_raw(p)
            hide = (mode == 1 and raw) or (mode == 2 and not raw) or \
                (bool(text) and text not in it.text().lower())
            if n and not hide:
                r = self.ratings.get(p, 0)
                hide = not (r >= n if op == "ge" else r == n if op == "eq" else r <= n)
            if it.isHidden() != hide:
                it.setHidden(hide)
            if hide and it.isSelected():
                it.setSelected(False)
            shown += not hide
        if hasattr(self, "lbl_filter"):
            self.btn_rf_clear.setVisible(bool(n))
            self.lbl_filter.setText(f"{shown} von {len(self.items)} Bildern" if n or shown != len(self.items)
                                    else f"{len(self.items)} Bilder")
        cur = self.lst.currentItem()
        if (cur is None or cur.isHidden()) and shown:
            # aktuelles Bild ausgefiltert → das im Filmstreifen direkt folgende
            # sichtbare Bild, am Ende das vorhergehende; ohne aktuelles das erste
            row = self.lst.row(cur) if cur is not None else -1
            n_rows = self.lst.count()
            order = list(range(row + 1, n_rows)) + list(range(row - 1, -1, -1)) if row >= 0 \
                else list(range(n_rows))
            nxt = next((self.lst.item(i) for i in order if not self.lst.item(i).isHidden()), None)
            if nxt is not None:
                self.lst.setCurrentItem(nxt)
        self.update_counts()

    def selected_paths(self):
        return [self.lst.item(i).data(Qt.UserRole) for i in range(self.lst.count())
                if self.lst.item(i).isSelected() and not self.lst.item(i).isHidden()]

    def current_path(self):
        it = self.lst.currentItem()
        return it.data(Qt.UserRole) if it and not it.isHidden() else None

    def update_counts(self):
        n = len(self.selected_paths())
        shown = sum(1 for it in self.items.values() if not it.isHidden())
        self.lbl_count.setText(f"{shown} Bilder, {n} ausgewählt")
        self.btn_apply.setText(f"Auf {n} ausgewählte(s) Bild(er) anwenden" if n
                               else "Auf Auswahl anwenden")
        self.btn_apply.setEnabled(n > 0)
        if hasattr(self, "btn_ac_apply"):
            self.btn_ac_apply.setText(f"In {n} Bild{'er' if n != 1 else ''} schreiben" if n
                                      else "Schreiben")
        self.btn_preview.setEnabled(n > 0)
        self.update_live()

    # ---- Metadaten lesen --------------------------------------------------
    def ensure_meta(self, paths, tags=frozenset()):
        need = [p for p in paths if p not in self.meta
                or not tags <= self.meta_tags.get(p, frozenset())]
        if not need:
            return
        if len(need) > 20:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            got = self.et.read_merged(need, sorted(tags))
        except core.ExifToolError as e:
            self.logmsg(f"FEHLER beim Lesen: {e}")
            got = {}
        finally:
            if len(need) > 20:
                QApplication.restoreOverrideCursor()
        for p in need:
            self.meta[p] = got.get(p, {})
            self.meta_tags[p] = frozenset(tags)

    def show_info(self):
        p = self.current_path()
        if not p:
            self.tbl.setRowCount(0)
            self.update_preview()
            return
        self.ensure_meta([p])
        if p not in self.dirty or p not in self.ratings:
            self._update_marks(p)
        self.update_preview()
        self.ac_detect()
        self.refresh_aufnahme()
        self.update_ac_live()
        m = self.meta.get(p, {})
        ctx = core.Context(p, m)
        rows = [("Datei", os.path.basename(p)),
                ("Aufnahme", ctx.resolve("{date} {time}")[0].strip()),
                ("Kamera", self._camera(ctx)),
                ("Objektiv", ctx.resolve("{lens}")[0]),
                ("Belichtung", ctx.resolve("{shutter} s · f/{aperture} · ISO {iso} · {focallength}")[0]
                 if core.lookup(m, "ExposureTime") else ""),
                ("Größe", ctx.resolve("{width} × {height} px")[0] if core.lookup(m, "ImageWidth") else "")]
        if m.get("_sidecar"):
            rows.append(("Begleitdatei", os.path.basename(m["_sidecar"])))
        rows += [(f.label, ("★" * core.rating_of(m) + "☆" * (5 - core.rating_of(m))
                            if core.rating_of(m) else "") if f.key == "rating"
                  else core.field_value(m, f)) for f in FIELDS]
        rows = [r for r in rows if r[1]]
        self.tbl.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            self.tbl.setItem(i, 0, QTableWidgetItem(k))
            self.tbl.setItem(i, 1, QTableWidgetItem(v))
        self.tbl.resizeRowsToContents()
        self.update_live()

    @staticmethod
    def _camera(ctx):
        make, model = ctx.value("make", ""), ctx.value("model", "")
        return model if model.lower().startswith(make.lower()) else f"{make} {model}".strip()

    # ---- Vorlagenfeld -----------------------------------------------------
    def pad_from_image(self):
        p = self.current_path()
        if not p:
            return
        self.ensure_meta([p])
        for f in FIELDS:
            v = core.field_value(self.meta.get(p, {}), f)
            self.set_field_text(f.key, v)
            self.checks[f.key].setChecked(bool(v))
        self.update_live()

    def pad_clear(self):
        self.set_pad_state({})
        self.update_live()

    def active_templates(self):
        """(felder{key: vorlage}, extras[(tag, vorlage)], fehler[])"""
        fields = {k: self.field_text(k) for k in self.edits if self.checks[k].isChecked()}
        extras, errors = [], []
        if self.chk_extra.isChecked():
            extras, errors = core.parse_extras(self.ed_extra.toPlainText())
        return fields, extras, errors

    def make_context(self, path, index, total, codes=None, data=None, seq_start=None):
        return core.Context(path, self.meta.get(path, {}), index, total,
                            self.spn_seq.value() if seq_start is None else seq_start,
                            codes or self.codes, data or self.data,
                            aircraft=self.ac_effective(),
                            ac_columns=self.ac_columns(),
                            ac_key=self.ac_keycol(), ac_vars=self.ac_vars())

    def update_live(self):
        """Zeigt unter den Feldern, was im aktuellen Bild landen würde."""
        if not hasattr(self, "lbl_live"):
            return
        p = self.current_path()
        fields, extras, errors = self.active_templates()
        rn = self.rename_template(False) if hasattr(self, "chk_rename") else None
        if not p or not (fields or extras or rn):
            self.lbl_live.setText("")
            return
        if p not in self.meta:
            self.lbl_live.setText("")
            return
        sel = self.selected_paths()
        idx = sel.index(p) if p in sel else 0
        ctx = self.make_context(p, idx, max(1, len(sel)))
        parts, warn = [], []
        for k, t in fields.items():
            v, w = ctx.resolve(t)
            warn += w
            if "{" in t or "=" in t:
                parts.append(f"<b>{FIELD_BY_KEY[k].label}:</b> "
                             + (v.replace("<", "&lt;").replace("\n", " ⏎ ") or "<i>leer</i>"))
        if rn:
            nm, w = ctx.resolve(rn)
            warn += w
            stem = core.clean_filename(nm, os.path.splitext(p)[1])
            parts.append("<b>Neuer Name:</b> " + (html.escape(stem + os.path.splitext(p)[1]) if stem
                                                  else "<i>leer – wird nicht umbenannt</i>"))
        text = f"<b>{os.path.basename(p)}</b> → " + " · ".join(parts[:5]) if parts else ""
        if warn or errors:
            text += f"<br><span style='color:#ffb347'>⚠ {'; '.join(dict.fromkeys(warn + ['Ungültige Zeile: ' + e for e in errors]))}</span>"
        self.lbl_live.setText(text)

    # ---- CSV --------------------------------------------------------------
    def pick_codes(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Kürzel-CSV wählen", self.folder,
                                            "CSV/Text (*.csv *.txt *.tsv);;Alle Dateien (*)")
        if fn:
            self.set_codes(fn)

    def pick_data(self):
        fn, _ = QFileDialog.getOpenFileName(self, "Daten-CSV wählen", self.folder,
                                            "CSV/Text (*.csv *.txt *.tsv);;Alle Dateien (*)")
        if fn:
            self.set_data(fn)

    def set_codes(self, path, quiet=False):
        try:
            self.codes = core.CodeTable(path) if path and os.path.isfile(path) else core.CodeTable()
        except Exception as e:  # noqa
            self.codes = core.CodeTable()
            if not quiet:
                QMessageBox.warning(self, "Kürzel-CSV", f"Datei konnte nicht gelesen werden:\n{e}")
        self.ed_codes.setText(f"{os.path.basename(self.codes.path)}  ({len(self.codes)} Kürzel)"
                              if self.codes.path else "")
        self.ed_codes.setToolTip(self.codes.path or "")
        self.update_live()

    def set_data(self, path, key=None, quiet=False):
        try:
            self.data = core.DataTable(path, key) if path and os.path.isfile(path) else core.DataTable()
        except Exception as e:  # noqa
            self.data = core.DataTable()
            if not quiet:
                QMessageBox.warning(self, "Daten-CSV", f"Datei konnte nicht gelesen werden:\n{e}")
        self.ed_data.setText(f"{os.path.basename(self.data.path)}  ({len(self.data.rows)} Zeilen)"
                             if self.data.path else "")
        self.ed_data.setToolTip(self.data.path or "")
        self.cmb_key.clear()
        self.cmb_key.addItems(self.data.columns)
        if self.data.key_column:
            self.cmb_key.setCurrentText(self.data.key_column)
        self.update_live()

    def map_csv_columns(self):
        if not self.data.columns:
            QMessageBox.information(self, "Daten-CSV", "Bitte zuerst eine Daten-CSV laden.")
            return
        aliases = {}
        for f in FIELDS:
            aliases[f.label.lower()] = f.key
            aliases[f.key] = f.key
        aliases.update({"keywords": "keywords", "caption": "caption", "personen": "persons",
                        "ort": "city", "bildunterschrift": "caption", "schlagwörter": "keywords",
                        "urheber": "creator", "autor": "creator"})
        hit = []
        for col in self.data.columns:
            k = aliases.get(col.strip().lower())
            if k and k != "rating" and col != self.data.key_column:
                self.set_field_text(k, f"{{csv:{col}}}")
                self.checks[k].setChecked(True)
                hit.append(f"{col} → {FIELD_BY_KEY[k].label}")
        QMessageBox.information(self, "Spalten zugeordnet",
                                "\n".join(hit) if hit else
                                "Keine Spaltenüberschrift entspricht einem Feldnamen.\n"
                                "Sie können {csv:Spaltenname} auch von Hand eintragen.")
        self.update_live()

    # ---- Vorlagen ---------------------------------------------------------
    def refresh_templates(self, select=None):
        self.cmb_tpl.clear()
        self.cmb_tpl.addItem("– Vorlage wählen –", None)
        if TEMPLATE_DIR.is_dir():
            for f in sorted(TEMPLATE_DIR.glob("*.json"), key=lambda p: p.stem.lower()):
                self.cmb_tpl.addItem(f.stem, str(f))
        if select:
            i = self.cmb_tpl.findText(select)
            if i >= 0:
                self.cmb_tpl.setCurrentIndex(i)

    def load_template(self):
        fn = self.cmb_tpl.currentData()
        if fn:
            self.set_pad_state(load_json(fn, {}))
            self.update_live()

    def save_template(self):
        cur = self.cmb_tpl.currentText() if self.cmb_tpl.currentData() else ""
        name, ok = QInputDialog.getText(self, "Vorlage speichern", "Name der Vorlage:", text=cur)
        name = "".join(ch for ch in name if ch not in '\\/:*?"<>|').strip()
        if ok and name:
            save_json(TEMPLATE_DIR / f"{name}.json", self.pad_state())
            self.refresh_templates(name)

    def delete_template(self):
        fn = self.cmb_tpl.currentData()
        if fn and QMessageBox.question(
                self, "Vorlage löschen",
                f"Vorlage „{self.cmb_tpl.currentText()}“ löschen?") == QMessageBox.Yes:
            try:
                os.remove(fn)
            except OSError:
                pass
            self.refresh_templates()

    # ---- Schreiben --------------------------------------------------------
    def apply(self, preview):
        paths = self.selected_paths()
        fields, extras, errors = self.active_templates()
        if not paths:
            return
        if errors:
            QMessageBox.warning(self, "Weitere Tags", "Diese Zeilen sind ungültig "
                                "(erwartet: TAG = Wert):\n\n" + "\n".join(errors))
            return
        rename = self.rename_template(False)
        if not fields and not extras and not rename:
            QMessageBox.information(self, core.APP_NAME,
                                    "Es ist kein Feld angehakt – es gibt nichts zu schreiben.")
            return
        jobs, rows, n_warn, cols = self.build_jobs(paths, fields, extras, rename=rename)
        if preview or n_warn:
            if PreviewDialog(self, rows, cols, n_warn, len(paths)).exec() != QDialog.Accepted:
                return
        elif len(paths) > 1:
            if QMessageBox.question(
                    self, "Metadaten schreiben",
                    f"{len(cols) - (1 if rename else 0)} Feld(er) in {len(paths)} Dateien schreiben"
                    + (" und die Dateien umbenennen?" if rename else "?")) != QMessageBox.Yes:
                return
        self.run_write(jobs)

    def build_jobs(self, paths, fields, extras, tidy=False, skip_empty=False, rename=None,
                   ops_fn=None, ctx_kw=None):
        """Löst die Vorlagen für alle Dateien auf.
        Rückgabe (jobs, vorschauzeilen, anzahl_warnungen, spaltentitel)."""
        tags = frozenset(core.template_tags(list(fields.values()) + [v for _, v in extras]
                                            + ([rename] if rename else [])))
        self.ensure_meta(paths, tags)
        jobs, rows, n_warn = [], [], 0
        for i, p in enumerate(paths):
            ctx = self.make_context(p, i, len(paths), **(ctx_kw or {}))
            vals, vwarn = {}, []
            for k, t in fields.items():
                vals[k], w = ctx.resolve(t)
                if tidy:
                    vals[k] = (core.tidy_line(vals[k]) if not FIELD_BY_KEY[k].multiline else
                               "\n".join(re.sub(r"[ \t]{2,}", " ", ln).strip()
                                         for ln in vals[k].split("\n")).strip())
                if FIELD_BY_KEY[k].is_list:
                    vals[k] = ", ".join(core.split_list(vals[k]))
                vwarn.append(w)
            ex = []
            for tag, t in extras:
                v, w = ctx.resolve(t)
                ex.append((tag, core.tidy_line(v) if tidy else v))
                vwarn.append(w)
            new_stem, newname = None, []
            if rename:
                nm, w = ctx.resolve(rename)
                ext = os.path.splitext(p)[1]
                stem = core.clean_filename(nm, ext)
                if not stem:
                    w = w + ["Neuer Dateiname ist leer – Datei wird nicht umbenannt"]
                new_stem = stem or None
                newname = [stem + ext if stem else ""]
                vwarn.append(w)
            n_warn += sum(len(w) for w in vwarn)
            if skip_empty:   # leere Ergebnisse lassen vorhandene Inhalte unangetastet
                vals = {k: v for k, v in vals.items() if v.strip()}
                ex = [(t, v) for t, v in ex if v.strip()]
                jobs.append((p, vals, ex, new_stem, ops_fn(p) if ops_fn else []))
            else:
                jobs.append((p, vals, ex, new_stem, ops_fn(p) if ops_fn else []))
            if i < 300:
                def show_val(k):
                    v = vals.get(k, "")
                    if k == "rating" and v.strip():
                        n = core.rating_of({"XMP-xmp:Rating": v})
                        return "★" * n + "☆" * (5 - n)
                    return v
                shown = [show_val(k) for k in fields] + [v for _, v in ex]
                if skip_empty:   # Spalten trotz ausgelassener Leerfelder ausrichten
                    exd = dict(ex)
                    shown = [show_val(k) for k in fields] + [exd.get(t, "") for t, _ in extras]
                rows.append((os.path.basename(p), shown + newname, vwarn))
        cols = [FIELD_BY_KEY[k].label for k in fields] + [t for t, _ in extras] \
            + (["Neuer Dateiname"] if rename else [])
        return jobs, rows, n_warn, cols

    def run_write(self, jobs, kw_mode=None, on_done=None):
        opts = {"kw_mode": kw_mode or self.cmb_kw.currentData(),
                "raw_mode": self.cfg.get("raw_mode", "sidecar"),
                "backup": self.cfg.get("backup", False)}
        dlg = QProgressDialog("Schreibe Metadaten …", "Abbrechen", 0, len(jobs), self)
        dlg.setWindowTitle(core.APP_NAME)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(300)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        worker = WriteWorker(self.et, jobs, opts)
        self._worker = worker
        worker.progress.connect(lambda i, name: (dlg.setValue(i), dlg.setLabelText(f"Schreibe {name} …")))
        dlg.canceled.connect(lambda: setattr(worker, "cancel", True))

        def done(results):
            dlg.close()
            ok = sum(1 for r in results if r[1])
            bad = [(r[0], r[2]) for r in results if not r[1]]
            rbad = [(r[0], r[4]) for r in results if r[4]]
            renamed = []
            for p, good, m, newp, rm in results:
                self.meta.pop(p, None)
                if m:
                    self.logmsg(f"{'Hinweis' if good else 'FEHLER'}  {os.path.basename(p)}: {m}")
                if rm:
                    self.logmsg(f"FEHLER  {os.path.basename(p)}: {rm}")
                if newp != p:
                    renamed.append((p, newp))
                    self.logmsg(f"Umbenannt: {os.path.basename(p)} → {os.path.basename(newp)}")
            self.apply_renames(renamed)
            self.refresh_tags([r[3] for r in results if r[1]])
            msg = f"{ok} von {len(jobs)} Datei(en) geschrieben" + (f", {len(renamed)} umbenannt" if renamed else "")
            self.logmsg(msg + ".")
            self.statusBar().showMessage(msg, 8000)
            if rbad:
                QMessageBox.warning(self, "Fehler beim Umbenennen",
                                    "Die Metadaten wurden geschrieben, aber diese Datei(en) konnten "
                                    "nicht umbenannt werden:\n\n"
                                    + "\n".join(f"{os.path.basename(p)}: {m}" for p, m in rbad[:12]))
            if bad:
                QMessageBox.warning(self, "Fehler beim Schreiben",
                                    f"{len(bad)} Datei(en) konnten nicht geschrieben werden:\n\n"
                                    + "\n".join(f"{os.path.basename(p)}: {m}" for p, m in bad[:12])
                                    + "\n\nDetails stehen im Reiter „Protokoll“.")
            self.show_info()
            if on_done:
                on_done(not bad and not rbad and ok == len(jobs))

        worker.finished_all.connect(done)
        worker.start()

    def on_scan(self, gen, data):
        if gen != self.generation:
            return
        cur = self.current_path()
        for p, m in data.items():
            if p in self.dirty or p not in self.items:
                continue
            if p not in self.meta:
                self.meta[p] = m
                self.meta_tags[p] = frozenset()
            self._update_marks(p)
        if self.star_filter.value:
            self.apply_filter()
        self.lst.viewport().update()
        if cur in data:
            self.update_preview()
            self.ac_detect()

    def refresh_tags(self, paths):
        """Nach dem Schreiben: Metadaten neu lesen, Markierung aktualisieren."""
        paths = [p for p in paths if p in self.items]
        if not paths or len(paths) > 500:
            return
        self.dirty.update(paths)
        for p in paths:
            self.meta.pop(p, None)
        self.ensure_meta(paths)
        for p in paths:
            self._update_marks(p)
        self.lst.viewport().update()

    def _update_marks(self, p):
        """Sterne und AeroTagger-Kennzeichnung eines Bildes aus seinen Metadaten."""
        m = self.meta.get(p, {})
        info = core.tag_info(m)
        if info is not None:
            self.tagged[p] = info
        else:
            self.tagged.pop(p, None)
        self.ratings[p] = core.rating_of(m)

    def set_rating(self, n):
        """Tasten 0–5: Sternbewertung der ausgewählten Bilder sofort schreiben."""
        paths = self.selected_paths()
        cur = self.current_path()
        if not paths and cur:
            paths = [cur]
        if not paths:
            return
        for p in paths:                    # gleich anzeigen, Schreiben folgt
            self.ratings[p] = n
            if p in self.meta:
                self.meta[p] = {k: v for k, v in self.meta[p].items() if k.rpartition(":")[2] != "Rating"}
                self.meta[p]["XMP-xmp:Rating"] = n
        self.lst.viewport().update()
        self.update_preview()
        extras = core.rating_extras(n)
        self.run_write([(p, {}, extras, None, []) for p in paths])
        stars = "★" * n + "☆" * (5 - n)
        self.statusBar().showMessage(f"Bewertung {stars} für {len(paths)} Bild(er) geschrieben", 5000)
        if self.star_filter.value:
            self.apply_filter()

    def apply_renames(self, pairs):
        """Filmstreifen und Zwischenspeicher auf die neuen Dateinamen umstellen.
        Die Reihenfolge im Streifen bleibt (F5 sortiert neu)."""
        for old, new in pairs:
            it = self.items.pop(old, None)
            if it is None:
                continue
            it.setData(Qt.UserRole, new)
            it.setText(os.path.relpath(new, self.folder) if self.chk_recursive.isChecked()
                       else os.path.basename(new))
            it.setToolTip(new)
            self.items[new] = it
            if old in self.pixmaps:
                self.pixmaps[new] = self.pixmaps.pop(old)
            if old in self.prev_cache:
                self.prev_cache[new] = self.prev_cache.pop(old)
            self.meta.pop(old, None)
            self.meta_tags.pop(old, None)
            if old in self.ratings:
                self.ratings[new] = self.ratings.pop(old)
            if old in self.tagged:
                self.tagged[new] = self.tagged.pop(old)
            if old in self.dirty:
                self.dirty.discard(old)
                self.dirty.add(new)
        if pairs:
            self.lst.viewport().update()

    # ---- Einstellungen ----------------------------------------------------
    def open_settings(self):
        d = SettingsDialog(self, self.cfg, f"Aktiv: ExifTool {self.et_ver}  ({' '.join(self.et.cmd)})")
        if d.exec() != QDialog.Accepted:
            return
        self.cfg["raw_mode"] = d.raw.currentData()
        self.cfg["backup"] = d.backup.isChecked()
        self.cfg["update_repo"] = d.repo.text().strip()
        self.cfg["github_token"] = d.token.text().strip()
        new = d.et.text().strip()
        if new != self.cfg.get("exiftool", ""):
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                cmd, ver = core.find_exiftool(new, strict=bool(new))
            finally:
                QApplication.restoreOverrideCursor()
            if cmd:
                self.cfg["exiftool"] = cmd[-1] if new else ""
                self.prev_pool.waitForDone(3000)
                self.et.close()
                self.et_thumb.close()
                self.et_preview.close()
                self.et, self.et_thumb, self.et_ver = core.ExifTool(cmd), core.ExifTool(cmd), ver
                self.et_preview = core.ExifTool(cmd)
                self.scan_pool.waitForDone(3000)
                self.et_scan.close()
                self.et_scan = core.ExifTool(cmd)
                self.statusBar().showMessage(f"ExifTool {ver}")
            else:
                QMessageBox.warning(self, "ExifTool", "Unter diesem Pfad wurde kein lauffähiges "
                                    f"ExifTool gefunden.\n\n{core.LAST_ERROR}")
        save_json(CONFIG_FILE, self.cfg)


# --------------------------------------------------------------------------
def dark_palette():
    p = QPalette()
    base, win, text = QColor("#1f2124"), QColor("#2b2d31"), QColor("#e4e6e9")
    p.setColor(QPalette.Window, win)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, win)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor("#383b40"))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.ToolTipBase, QColor("#111"))
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.Highlight, QColor("#2f6fb3"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.PlaceholderText, QColor("#7d838b"))
    for role in (QPalette.Text, QPalette.ButtonText, QPalette.WindowText):
        p.setColor(QPalette.Disabled, role, QColor("#777b82"))
    return p


def locate_exiftool(cfg, parent=None):
    cmd, ver = core.find_exiftool(cfg.get("exiftool", ""))
    if cmd:
        return cmd, ver
    if sys.platform == "win32":
        r = QMessageBox.question(
            parent, core.APP_NAME,
            "AeroTagger benötigt das kostenlose Programm ExifTool, das auf diesem "
            "Rechner noch nicht gefunden wurde.\n\nJetzt automatisch von "
            "exiftool.org herunterladen?")
        if r == QMessageBox.Yes:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                cfg["exiftool"] = core.download_exiftool_windows()
            except Exception as e:  # noqa
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(parent, core.APP_NAME, f"Download fehlgeschlagen:\n{e}")
            else:
                QApplication.restoreOverrideCursor()
                cmd, ver = core.find_exiftool(cfg["exiftool"])
                if cmd:
                    return cmd, ver
    msg = ("ExifTool wurde nicht gefunden.\n\nBitte von https://exiftool.org "
           "herunterladen, das Zip vollständig entpacken und im nächsten Dialog "
           "die Programmdatei auswählen (unter Windows „exiftool(-k).exe“ – "
           "der Ordner „exiftool_files“ muss daneben liegen).")
    if core.LAST_ERROR and cfg.get("exiftool"):
        msg += f"\n\nGrund beim zuletzt gewählten Pfad:\n{core.LAST_ERROR}"
    QMessageBox.information(parent, core.APP_NAME, msg)
    start = os.path.dirname(cfg.get("exiftool", "")) or str(Path.home() / "Downloads")
    flt = "ExifTool (exiftool*.exe);;Alle Dateien (*)" if sys.platform == "win32" else "Alle Dateien (*)"
    while True:
        fn, _ = QFileDialog.getOpenFileName(parent, "ExifTool auswählen", start, flt)
        if not fn:
            return None, None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cmd, ver = core.find_exiftool(fn)
        finally:
            QApplication.restoreOverrideCursor()
        if cmd:
            cfg["exiftool"] = cmd[-1]      # ggf. die angelegte exiftool.exe
            try:
                save_json(CONFIG_FILE, cfg)
            except OSError:
                pass
            return cmd, ver
        start = os.path.dirname(fn)
        if QMessageBox.warning(
                parent, core.APP_NAME,
                f"Diese Datei funktioniert nicht als ExifTool:\n{fn}\n\n{core.LAST_ERROR}",
                QMessageBox.Retry | QMessageBox.Cancel) != QMessageBox.Retry:
            return None, None


def main(app=None, splash=None):
    """Startet AeroTagger. app/splash kommen von AeroTagger.pyw, das den
    Startbildschirm schon vor dem Laden dieses Moduls zeigt."""
    if app is None:
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AeroTagger.App")
            except Exception:  # noqa
                pass
        app = QApplication(sys.argv)
    t0 = time.monotonic()
    if splash is None:
        from .splash import Splash
        splash = Splash(core.APP_VERSION)
        splash.show()
    app.setApplicationName(core.APP_NAME)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    splash.step("Lade Einstellungen …", 0.25)
    core.migrate_config()
    cfg = load_json(CONFIG_FILE, {})
    splash.step("Suche ExifTool …", 0.45)
    cmd, ver = core.find_exiftool(cfg.get("exiftool", ""))
    if not cmd:
        splash.hide()                       # Dialoge nicht hinter dem Startbild verstecken
        cmd, ver = locate_exiftool(cfg)
        if not cmd:
            splash.close()
            QMessageBox.critical(None, core.APP_NAME, "Ohne ExifTool kann AeroTagger nicht starten.")
            return 1
        splash.show()
    splash.step(f"ExifTool {ver} gefunden – öffne Ordner …", 0.7)
    win = MainWindow(cfg, cmd, ver)
    splash.step("Bereit", 1.0)

    def reveal():
        win.show()
        splash.finish(win)
    # Startbild mindestens gut eine Sekunde zeigen, damit es nicht nur aufblitzt
    QTimer.singleShot(max(0, int((1.2 - (time.monotonic() - t0)) * 1000)), reveal)
    return app.exec()
