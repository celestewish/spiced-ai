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
    from spiced.ui.theme import STYLESHEET

    app = QApplication(sys.argv)
    app.setApplicationName("Spiced")
    app.setStyleSheet(STYLESHEET)

    services = Services()
    window = MainWindow(services)
    window.show()
    window.maybe_show_onboarding()

    exit_code = app.exec()
    services.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
