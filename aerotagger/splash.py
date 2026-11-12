"""Startbildschirm – bewusst schlank, damit er erscheint, bevor der Rest
von AeroTagger geladen ist."""
import sys
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

RES_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "aerotagger" / "resources"


class Splash(QSplashScreen):
    # Maße im Startbild (logische Pixel, Bild 560 × 320)
    BAR = QRectF(48, 255.5, 464, 3)
    TEXT = QRect(48, 268, 464, 26)

    def __init__(self, version=""):
        screen = QApplication.primaryScreen()
        dpr = screen.devicePixelRatio() if screen else 1.0
        hi = dpr > 1.2 and (RES_DIR / "splash@2x.png").is_file()
        pm = QPixmap(str(RES_DIR / ("splash@2x.png" if hi else "splash@1x.png")))
        if hi:
            pm.setDevicePixelRatio(2)
        super().__init__(pm, Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)   # abgerundete Ecken
        self.version = version
        self.progress = 0.0
        self.text = ""

    def step(self, text, progress):
        """Statuszeile und Fortschrittsbalken aktualisieren."""
        self.text, self.progress = text, max(self.progress, min(1.0, progress))
        self.repaint()
        QApplication.processEvents()

    def drawContents(self, p):
        p.setRenderHint(p.RenderHint.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#1E3D60"))
        p.drawRoundedRect(self.BAR, 1.5, 1.5)
        if self.progress > 0:
            r = QRectF(self.BAR)
            r.setWidth(max(12.0, self.BAR.width() * self.progress))
            p.setBrush(QColor("#F5A524"))
            p.drawRoundedRect(r, 1.5, 1.5)
        f = p.font()
        f.setPointSizeF(max(8.5, f.pointSizeF() * 0.95))
        p.setFont(f)
        p.setPen(QColor("#9FB4C7"))
        p.drawText(self.TEXT, Qt.AlignLeft | Qt.AlignVCenter, self.text)
        if self.version:
            p.setPen(QColor("#6F8AA6"))
            p.drawText(self.TEXT, Qt.AlignRight | Qt.AlignVCenter, f"Version {self.version}")
