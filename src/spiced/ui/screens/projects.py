"""Projects screen: create and view local projects."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spiced.core.projects_service import ProjectsService


class ProjectsScreen(QWidget):
    """Lets the developer create a project and see the ones they've saved."""

    projects_changed = Signal()

    def __init__(self, projects: ProjectsService) -> None:
        super().__init__()
        self._projects = projects

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("Projects")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        intro = QLabel(
            "Add a game project to keep Spiced's help organized. Nothing here leaves "
            "your machine."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Create form
        form = QHBoxLayout()
        form.setSpacing(8)
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Project name (e.g. Moonlit Depths)")
        self._name_input.returnPressed.connect(self._create)
        self._engine_input = QComboBox()
        self._engine_input.addItems(["Unity", "Godot", "Unreal", "Other"])
        self._create_btn = QPushButton("Create project")
        self._create_btn.clicked.connect(self._create)
        form.addWidget(self._name_input, 3)
        form.addWidget(self._engine_input, 1)
        form.addWidget(self._create_btn, 0)
        layout.addLayout(form)

        section = QLabel("Your projects")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)

        self._list = QListWidget()
        layout.addWidget(self._list, 1)

        self._empty = QLabel("No projects yet. Create your first one above.")
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)

        self.refresh()

    def _create(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.information(self, "Name needed", "Please enter a project name.")
            return
        self._projects.create_project(name=name, engine=self._engine_input.currentText())
        self._name_input.clear()
        self.refresh()
        self.projects_changed.emit()

    def refresh(self) -> None:
        self._list.clear()
        items = self._projects.list_projects()
        for project in items:
            self._list.addItem(f"{project.name}   ·   {project.engine}   ·   {project.created_at}")
        self._empty.setVisible(not items)
        self._list.setVisible(bool(items))
