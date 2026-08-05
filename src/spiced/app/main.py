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


def main() -> int:
    _load_env()

    # Imported here so non-GUI tooling can import spiced.app.services without Qt.
    from PySide6.QtWidgets import QApplication

    from spiced.ui.main_window import MainWindow
    from spiced.ui.theme import build_stylesheet

    app = QApplication(sys.argv)
    app.setApplicationName("Spiced")

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
