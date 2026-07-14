"""Projects screen: create projects, pick one as active, connect a Unity folder."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services


class ProjectsScreen(QWidget):
    """Create projects, select the active one, and connect a Unity folder."""

    projects_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._projects = services.projects

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title = QLabel("Projects")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        intro = QLabel(
            "Add a game project to keep Spiced's help organized. Pick one as active, then "
            "connect its Unity folder. Nothing here leaves your machine."
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

        # Explicit, safe demo loader. Seeds one bundled sample project so every
        # screen has realistic data. No Unity, no AI, no network — and it never
        # touches projects you created yourself.
        demo_row = QHBoxLayout()
        demo_row.setSpacing(8)
        self._demo_btn = QPushButton("Load demo project")
        self._demo_btn.setObjectName("Ghost")
        self._demo_btn.clicked.connect(self._load_demo)
        demo_row.addWidget(self._demo_btn, 0)
        demo_hint = QLabel(
            "Adds a bundled sample project (no Unity files, nothing sent anywhere) so you can "
            "explore the Dashboard and every screen right away."
        )
        demo_hint.setObjectName("Muted")
        demo_hint.setWordWrap(True)
        demo_row.addWidget(demo_hint, 1)
        layout.addLayout(demo_row)

        section = QLabel("Your projects")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list, 1)

        self._empty = QLabel("No projects yet. Create your first one above.")
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)

        # Active-project detail + Unity folder controls
        self._detail = QLabel()
        self._detail.setObjectName("Muted")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._folder_btn = QPushButton("Choose Unity Folder…")
        self._folder_btn.clicked.connect(self._choose_folder)
        controls.addWidget(self._folder_btn)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.refresh()

    def _create(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.information(self, "Name needed", "Please enter a project name.")
            return
        project = self._projects.create_project(
            name=name, engine=self._engine_input.currentText()
        )
        self._services.set_active_project(project.id)
        self._name_input.clear()
        self.refresh()
        self.projects_changed.emit()

    def _load_demo(self) -> None:
        already = self._services.demo.is_seeded()
        project = self._services.load_demo_project()
        self.refresh()
        self.projects_changed.emit()
        message = (
            "The demo project is already loaded — switched to it."
            if already
            else "Loaded the bundled demo project with sample debugging, testing, and "
            "feedback data. Open the Dashboard to see it. Nothing was sent anywhere, "
            "and your own projects were not changed."
        )
        QMessageBox.information(self, project.name, message)

    def _on_selection_changed(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            return
        project_id = current.data(0x0100)  # Qt.UserRole
        if project_id is None:
            return
        self._services.set_active_project(int(project_id))
        self._update_detail()
        self.projects_changed.emit()

    def _choose_folder(self) -> None:
        project = self._services.active_project()
        if project is None:
            QMessageBox.information(
                self, "Pick a project first", "Select a project above, then choose its folder."
            )
            return
        folder = QFileDialog.getExistingDirectory(self, "Choose your Unity project folder")
        if not folder:
            return
        _updated, detection = self._projects.attach_unity_folder(project.id, folder)
        if detection.is_valid:
            QMessageBox.information(
                self,
                "Unity project connected",
                f"That looks like a valid Unity project ({detection.project_name}).",
            )
        else:
            warnings = (
                "\n".join(f"• {w}" for w in detection.warnings) or "Unexpected folder layout."
            )
            QMessageBox.warning(
                self,
                "That doesn't look like a Unity project",
                "I saved the path, but it's missing some things a Unity project usually has:\n\n"
                f"{warnings}\n\nYou can pick a different folder any time.",
            )
        self.refresh()
        self.projects_changed.emit()

    def refresh(self) -> None:
        active = self._services.active_project()
        self._list.blockSignals(True)
        self._list.clear()
        items = self._projects.list_projects()
        active_row = -1
        for row, project in enumerate(items):
            marker = "✓ Unity" if project.is_valid_unity else project.engine
            label = f"{project.name}   ·   {marker}   ·   {project.created_at}"
            item = QListWidgetItem(label)
            item.setData(0x0100, project.id)  # Qt.UserRole
            self._list.addItem(item)
            if active is not None and project.id == active.id:
                active_row = row
        self._list.blockSignals(False)
        if active_row >= 0:
            self._list.setCurrentRow(active_row)
        self._empty.setVisible(not items)
        self._list.setVisible(bool(items))
        self._update_detail()

    def _update_detail(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._detail.setText("Select or create a project to connect a Unity folder.")
            self._folder_btn.setEnabled(False)
            return
        self._folder_btn.setEnabled(True)
        if not project.path:
            self._detail.setText(
                f"Active: {project.name}. No Unity folder connected yet — "
                "click “Choose Unity Folder”."
            )
            return
        meta = project.engine_metadata
        version = meta.get("unity_version")
        status = "valid Unity project" if project.is_valid_unity else "not recognized as Unity"
        version_note = f" · Unity {version}" if version else ""
        self._detail.setText(f"Active: {project.name}\n{project.path}\n({status}{version_note})")
