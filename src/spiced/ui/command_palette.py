"""Command Palette / Quick Search (Phase K, section 9 part 1, Core tier).

A keyboard-triggered (Ctrl+K, which ``QKeySequence`` maps to Cmd+K on macOS)
modal dialog: a search box + a live-filtered list jumping to any sidebar
page, any local project (switching the active project, same mechanism as the
top bar's Multi-Project Switcher -- see ``ui.top_bar``), or a recent item.
"Recent item" covers three concrete, representative types per the phase's
"don't need to cover everything" pattern: a recent debug session, test run,
and feedback batch for the active project -- clicking one jumps to the
screen that item lives on (Debugging Buddy / Automated Testing / Feedback
Review respectively), since none of those screens have a "jump straight to
this one record" deep link yet.

``filter_items`` is pure and GUI-free by design, so it's directly testable
without simulating keystrokes/clicks (see tests/test_command_palette.py).
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout

_ITEM_ROLE = int(Qt.ItemDataRole.UserRole)


@dataclass(frozen=True)
class PaletteItem:
    """One jumpable entry. ``action`` is called (with no arguments) when the
    item is activated -- the palette itself has no idea what a "page" or
    "project" is, that's entirely up to the caller building the item list
    (see ``ui.main_window.MainWindow._build_palette_items``)."""

    kind: str  # "page" | "project" | "recent"
    label: str
    subtitle: str
    action: Callable[[], None]

    @property
    def _haystack(self) -> str:
        return f"{self.label} {self.subtitle}".lower()


def filter_items(items: list[PaletteItem], query: str) -> list[PaletteItem]:
    """Case-insensitive substring match first (kept in the given order);
    falls back to a loose fuzzy match (stdlib ``difflib.get_close_matches``,
    no fuzzy-matching dependency needed) for typos, when nothing matches by
    substring. An empty/whitespace-only query returns every item, unfiltered.
    """
    query = (query or "").strip().lower()
    if not query:
        return list(items)

    substring_hits = [item for item in items if query in item._haystack]
    if substring_hits:
        return substring_hits

    haystacks = [item._haystack for item in items]
    close = difflib.get_close_matches(query, haystacks, n=10, cutoff=0.3)
    # get_close_matches doesn't preserve input order and can't disambiguate
    # duplicate haystacks -- map back positionally, first-match-wins.
    seen: set[int] = set()
    matched: list[PaletteItem] = []
    for target in close:
        for index, item in enumerate(items):
            if index in seen:
                continue
            if item._haystack == target:
                matched.append(item)
                seen.add(index)
                break
    return matched


class CommandPalette(QDialog):
    """The Ctrl+K modal: a search box + a live-filtered jump list."""

    def __init__(self, items_provider: Callable[[], list[PaletteItem]], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setWindowTitle("Quick search")
        self.setMinimumWidth(440)
        self._items_provider = items_provider
        self._items: list[PaletteItem] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Jump to a page, project, or recent item…")
        self._input.textChanged.connect(self._on_query_changed)
        self._input.returnPressed.connect(self._activate_current)
        layout.addWidget(self._input)

        self._list = QListWidget()
        self._list.itemActivated.connect(self._on_item_activated)
        layout.addWidget(self._list)

    def open(self) -> None:
        """Refresh the item list from ``items_provider`` and show the
        dialog fresh (empty query, first item highlighted) -- called on
        every Ctrl+K press rather than once at startup, since projects and
        recent items change over the app's lifetime."""
        self._items = self._items_provider()
        self._input.blockSignals(True)
        self._input.clear()
        self._input.blockSignals(False)
        self._populate(self._items)
        self.show()
        self.raise_()
        self._input.setFocus()

    def _on_query_changed(self, text: str) -> None:
        self._populate(filter_items(self._items, text))

    def _populate(self, items: list[PaletteItem]) -> None:
        self._list.clear()
        for item in items:
            widget_item = QListWidgetItem(f"{item.label}  —  {item.subtitle}")
            widget_item.setData(_ITEM_ROLE, item)
            self._list.addItem(widget_item)
        if self._list.count():
            self._list.setCurrentRow(0)

    def _activate_current(self) -> None:
        current = self._list.currentItem()
        if current is not None:
            self._on_item_activated(current)

    def _on_item_activated(self, list_item: QListWidgetItem) -> None:
        item: PaletteItem | None = list_item.data(_ITEM_ROLE)
        self.close()
        if item is not None:
            item.action()
