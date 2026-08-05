"""Keyboard shortcuts cheat-sheet overlay (Phase L, Phase 2 tier).

A simple modal listing every action's current binding, opened by pressing
``?`` (see ``ui.main_window`` for the QShortcut wiring) or from the
Settings screen. Reads bindings fresh every time it opens via
``bindings_provider`` so a rebind made in Settings shows up immediately.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from spiced.core.keyboard_shortcuts import ACTIONS, binding_for


class ShortcutsCheatSheet(QDialog):
    def __init__(
        self, bindings_provider: Callable[[], dict[str, str]], parent=None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setWindowTitle("Keyboard shortcuts")
        self.setMinimumWidth(420)
        self._bindings_provider = bindings_provider

        layout = QVBoxLayout(self)
        heading = QLabel("Keyboard shortcuts")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._list = QListWidget()
        layout.addWidget(self._list)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("Ghost")
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    def open(self) -> None:
        """Refresh the list from ``bindings_provider`` and show the dialog."""
        bindings = self._bindings_provider()
        self._list.clear()
        for action in ACTIONS:
            binding = binding_for(action.id, bindings)
            self._list.addItem(QListWidgetItem(f"{binding}   —   {action.label}"))
        self.show()
        self.raise_()
