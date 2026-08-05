"""WidgetCustomizeDialog: show/hide + up/down reorder list (Phase L).

The UI half of Customizable Dashboard Widgets' documented scope-down (see
``core.widget_preferences`` for the full reasoning) -- a checkable list with
Move up/down buttons, reused as-is by both consumers
(``ui.context_panel.ContextPanel`` and ``ui.screens.dashboard.DashboardScreen``)
rather than building a separate dialog per screen.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from spiced.core.widget_preferences import WidgetPreference, WidgetSpec

_ID_ROLE = int(Qt.ItemDataRole.UserRole)


class WidgetCustomizeDialog(QDialog):
    def __init__(
        self,
        specs: list[WidgetSpec],
        preferences: dict[str, WidgetPreference],
        parent=None,
        title: str = "Customize widgets",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setWindowTitle(title)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self._list)

        ordered = sorted(specs, key=lambda s: preferences.get(s.id, WidgetPreference()).order)
        for spec in ordered:
            pref = preferences.get(spec.id, WidgetPreference())
            item = QListWidgetItem(spec.label)
            item.setData(_ID_ROLE, spec.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if pref.visible else Qt.CheckState.Unchecked)
            self._list.addItem(item)

        button_row = QHBoxLayout()
        up_btn = QPushButton("Move up")
        up_btn.setObjectName("Ghost")
        up_btn.clicked.connect(self._move_up)
        button_row.addWidget(up_btn)
        down_btn = QPushButton("Move down")
        down_btn.setObjectName("Ghost")
        down_btn.clicked.connect(self._move_down)
        button_row.addWidget(down_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("Ghost")
        cancel_btn.clicked.connect(self.reject)
        action_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.accept)
        action_row.addWidget(save_btn)
        layout.addLayout(action_row)

    def _move_up(self) -> None:
        row = self._list.currentRow()
        if row > 0:
            item = self._list.takeItem(row)
            self._list.insertItem(row - 1, item)
            self._list.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < self._list.count() - 1:
            item = self._list.takeItem(row)
            self._list.insertItem(row + 1, item)
            self._list.setCurrentRow(row + 1)

    def result_preferences(self) -> dict[str, WidgetPreference]:
        """Read the dialog's current list state back into a preferences
        dict -- call after ``exec()`` returns ``Accepted``."""
        result: dict[str, WidgetPreference] = {}
        for row in range(self._list.count()):
            item = self._list.item(row)
            widget_id = item.data(_ID_ROLE)
            result[widget_id] = WidgetPreference(
                visible=item.checkState() == Qt.CheckState.Checked, order=row
            )
        return result
