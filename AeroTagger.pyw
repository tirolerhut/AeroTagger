"""Startdatei für AeroTagger.

Zeigt zuerst nur den Startbildschirm und lädt erst danach den Rest der
Anwendung – so ist sofort etwas zu sehen."""
import sys


def run():
    if sys.platform == "win32":
        # eigenes Taskleistensymbol statt des Python-Symbols
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AeroTagger.App")
        except Exception:  # noqa
            pass
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    from aerotagger.splash import Splash
    from aerotagger.core import APP_VERSION
    splash = Splash(APP_VERSION)
    splash.show()
    splash.step("Starte …", 0.08)
    from aerotagger.app import main      # der große Teil wird erst jetzt geladen
    return main(app, splash)


if __name__ == "__main__":
    sys.exit(run())
