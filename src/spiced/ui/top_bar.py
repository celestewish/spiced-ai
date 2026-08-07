"""Top bar: Spiced wordmark + Multi-Project Switcher (left), notification
bell (right) (Phase K, section 9 part 1, foundation + Core tier).

Spiced had no top bar at all before this phase -- see ``ui.main_window``,
which now stacks this above the existing Sidebar/Workspace/Context-panel
row. Kept deliberately thin and minimal, matching the existing theme's
spacing/color conventions (``ui.theme``).

The Multi-Project Switcher reuses the exact same "set active project"
mechanism the Projects screen already uses (``Services.set_active_project``)
and fires ``project_switched`` for ``MainWindow`` to relay into the same
``projects_changed``-style cascade every other screen already listens to --
see ``MainWindow._on_top_bar_project_switched``. It does not duplicate any
active-project-setting logic of its own.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel

from spiced.app.services import Services
from spiced.ui.notification_center import NotificationBell
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox


class TopBar(QFrame):
    """The thin strip above Sidebar/Workspace/Context panel."""

    project_switched = Signal()

    def __init__(self, services: Services, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self._services = services

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 18, 10)
        layout.setSpacing(12)

        brand = QLabel("Spiced")
        brand.setObjectName("Brand")
        layout.addWidget(brand)

        self._project_switcher = ScrollSafeComboBox()
        self._project_switcher.setMinimumWidth(220)
        self._project_switcher.setToolTip("Switch active project")
        self._project_switcher.currentIndexChanged.connect(self._on_switcher_changed)
        layout.addWidget(self._project_switcher)

        layout.addStretch(1)

        self._bell = NotificationBell(self._services, self)
        layout.addWidget(self._bell)

        self.refresh()

    @property
    def bell(self) -> NotificationBell:
        return self._bell

    def stop(self) -> None:
        """Stop the bell's poller -- call from MainWindow.closeEvent, same
        as BuildScheduler.stop()."""
        self._bell.stop()

    def refresh(self) -> None:
        """Repopulate the project switcher and re-resolve the bell's team
        context. Safe to call whenever the active project or the project
        list changes."""
        self._refresh_project_switcher()
        self._bell.set_active_project(self._services.active_project())

    def _refresh_project_switcher(self) -> None:
        active = self._services.active_project()
        projects = self._services.projects.list_projects()

        self._project_switcher.blockSignals(True)
        self._project_switcher.clear()
        for project in projects:
            self._project_switcher.addItem(project.name, project.id)
        if active is not None:
            idx = self._project_switcher.findData(active.id)
            if idx >= 0:
                self._project_switcher.setCurrentIndex(idx)
        self._project_switcher.blockSignals(False)
        self._project_switcher.setEnabled(bool(projects))

    def _on_switcher_changed(self, index: int) -> None:
        project_id = self._project_switcher.itemData(index)
        if project_id is None:
            return
        active = self._services.active_project()
        if active is not None and active.id == project_id:
            return
        self._services.set_active_project(int(project_id))
        self._bell.set_active_project(self._services.active_project())
        self.project_switched.emit()
