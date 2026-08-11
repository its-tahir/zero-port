"""ZeroPort entry point.

Deliberately thin and deliberately fast: build the application, show the
window, and let the first scan start on the event loop's first turn. No
network, no database, no server, no background services.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QApplication

from app import APP_NAME, APP_VERSION
from app.config.config_manager import ConfigManager
from app.ui import styles
from app.ui.main_window import MainWindow
from app.utils.windows import set_app_user_model_id

APP_ID = "TahirNazir.ZeroPort"


def asset_path(name: str) -> Path:
    """Resolve an asset both in development and inside a PyInstaller bundle."""
    bundled = getattr(sys, "_MEIPASS", None)
    base = Path(bundled) if bundled else Path(__file__).resolve().parent.parent
    return base / "assets" / name


def build_palette() -> QPalette:
    """A dark palette so native chrome matches the app instead of fighting it."""
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, styles.BASE)
    palette.setColor(QPalette.ColorRole.WindowText, styles.TEXT)
    palette.setColor(QPalette.ColorRole.Base, styles.SURFACE)
    palette.setColor(QPalette.ColorRole.AlternateBase, styles.SURFACE_RAISED)
    palette.setColor(QPalette.ColorRole.Text, styles.TEXT)
    palette.setColor(QPalette.ColorRole.Button, styles.SURFACE)
    palette.setColor(QPalette.ColorRole.ButtonText, styles.TEXT)
    palette.setColor(QPalette.ColorRole.Highlight, styles.ACCENT_SOFT)
    palette.setColor(QPalette.ColorRole.HighlightedText, styles.TEXT)
    palette.setColor(QPalette.ColorRole.ToolTipBase, styles.SURFACE_RAISED)
    palette.setColor(QPalette.ColorRole.ToolTipText, styles.TEXT)
    palette.setColor(QPalette.ColorRole.PlaceholderText, styles.TEXT_GHOST)
    return palette


def main() -> int:
    set_app_user_model_id(APP_ID)

    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setApplicationVersion(APP_VERSION)
    QApplication.setOrganizationName("Tahir Nazir")

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setFont(styles.sans(10))
    app.setStyleSheet(styles.app_stylesheet())

    # Ask Windows for dark title bars and native dark chrome (Qt 6.8+).
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except (AttributeError, TypeError):
        pass

    icon_file = asset_path("icon.ico")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    config = ConfigManager()
    config.ensure_file_exists()

    window = MainWindow(config)
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
