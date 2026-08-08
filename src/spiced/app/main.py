"""Spiced desktop entry point.

Run with:  python -m spiced.app.main
"""

from __future__ import annotations

import sys

from spiced.app.services import Services


def _load_env() -> None:
    """Load a local .env if python-dotenv is installed. Optional and quiet."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _register_bundled_fonts() -> None:
    """Register the Baloo 2 / Nunito variable fonts (ui/assets/fonts/) with
    Qt's font database. Self-hosted rather than fetched at runtime -- Spiced
    is offline-first, and Qt/QSS has no equivalent of a CSS @font-face web
    request anyway. Missing/failed files are skipped quietly: the QSS in
    ui.theme still names these families, so a missing font just falls back
    to the platform default rather than crashing the app.
    """
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase

    fonts_dir = Path(__file__).resolve().parent.parent / "ui" / "assets" / "fonts"
    for font_file in sorted(fonts_dir.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font_file))


def main() -> int:
    _load_env()

    # Imported here so non-GUI tooling can import spiced.app.services without Qt.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from spiced.ui.main_window import MainWindow
    from spiced.ui.theme import build_stylesheet

    # At a non-integer Windows display scale (125%, 175%, ...), Qt's default
    # DPI-scale rounding can mismatch what Windows reports as the window's
    # size against what Qt lays out internally when maximized -- content
    # (including the fixed-width sidebar) overflows the actual visible
    # window with no scrollbar to reveal the rest, since Qt itself believes
    # everything fits within its own (wrongly rounded) viewport. PassThrough
    # uses the exact scale factor instead of rounding to the nearest
    # integer, which is Qt's own documented fix for this class of bug. Must
    # be set before QApplication is constructed.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Spiced")
    _register_bundled_fonts()

    services = Services()
    # In-App Accessibility Settings (Phase L, Core tier): apply whatever was
    # saved from a previous run right away, rather than always starting from
    # the default palette/text size -- see ui.screens.settings for where
    # these are changed live at runtime.
    app.setStyleSheet(
        build_stylesheet(
            text_size=services.accessibility_text_size(),
            high_contrast=services.accessibility_high_contrast_enabled(),
            colorblind_safe=services.accessibility_colorblind_safe_enabled(),
            reduce_motion=services.accessibility_reduce_motion_enabled(),
        )
    )

    window = MainWindow(services)
    window.show()

    exit_code = app.exec()
    services.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
