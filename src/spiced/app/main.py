"""Spiced desktop entry point.

Run with:  python -m spiced.app.main
"""

from __future__ import annotations

import sys

from spiced.app.services import Services
from spiced.storage.database import DatabaseUnavailableError


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


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    # --smoke-test (Connect-a-Project Setup Simplification spec, Finding 3
    # fix 8): constructs the real app -- Services, MainWindow, every screen
    # -- then exits without ever calling .show()/.exec(). Meant for CI to
    # run once against a freshly built installer on a clean Windows runner,
    # to catch the class of bug that only shows up in a bundled build and
    # never in a source checkout (a file PyInstaller silently didn't
    # include, an unset FFMPEG_PATH, a relative path that assumed the
    # source tree's layout) before a real user does.
    smoke_test = "--smoke-test" in argv[1:]

    _load_env()

    # Imported here so non-GUI tooling can import spiced.app.services without Qt.
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QMessageBox

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

    # QApplication.instance() or ...: constructing a second QApplication
    # while one already exists raises RuntimeError -- never happens in a
    # real run (main() is the process's first Qt code), but the
    # --smoke-test path being genuinely callable from a test suite (a
    # shared pytest session already has one from other screen tests) is
    # exactly what makes --smoke-test itself testable outside a full
    # PyInstaller build. See tests/test_app_main_smoke_test.py.
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Spiced")
    _register_bundled_fonts()

    try:
        services = Services()
    except DatabaseUnavailableError as exc:
        QMessageBox.critical(None, "Spiced couldn't start", str(exc))
        return 1
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

    if smoke_test:
        window.close()
        services.close()
        print("Spiced smoke test OK")
        return 0

    window.show()

    exit_code = app.exec()
    services.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
