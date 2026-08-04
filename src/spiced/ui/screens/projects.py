"""Projects screen: create projects, pick one as active, connect a Unity folder."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
from spiced.backend_client.api_client import BackendAPIError, NotAuthenticatedError
from spiced.connectors import unity_build
from spiced.core.unity_test_runner import resolve_unity_editor
from spiced.ui.auth_dialog import AuthDialog

_HHMM_PLACEHOLDER = "HH:MM, 24h (e.g. 02:00)"


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

        self._build_unity_test_run(layout)
        self._build_build_pipeline(layout)
        self._build_team_section(layout)

        self.refresh()

    # --- Run Unity Tests opt-in ---------------------------------------------

    def _build_unity_test_run(self, layout: QVBoxLayout) -> None:
        section = QLabel("Run Unity tests")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)

        intro = QLabel(
            "Off by default. When enabled, the Testing screen can launch this project's "
            "Unity Editor headlessly to run its tests — the one place Spiced executes an "
            "external process rather than only reading text you give it."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._unity_run_toggle = QCheckBox(
            "Allow Spiced to run this project's Unity tests"
        )
        self._unity_run_toggle.toggled.connect(self._on_unity_run_toggle)
        layout.addWidget(self._unity_run_toggle)

        override_row = QHBoxLayout()
        override_row.addWidget(QLabel("Unity Editor path (optional override):"))
        self._unity_editor_path_input = QLineEdit()
        self._unity_editor_path_input.setPlaceholderText(
            "Leave blank to auto-detect via Unity Hub"
        )
        self._unity_editor_path_input.editingFinished.connect(self._on_unity_editor_path_changed)
        override_row.addWidget(self._unity_editor_path_input, 1)
        self._unity_editor_browse_btn = QPushButton("Browse…")
        self._unity_editor_browse_btn.clicked.connect(self._on_browse_unity_editor)
        override_row.addWidget(self._unity_editor_browse_btn)
        layout.addLayout(override_row)

        self._unity_run_status = QLabel()
        self._unity_run_status.setObjectName("Muted")
        self._unity_run_status.setWordWrap(True)
        layout.addWidget(self._unity_run_status)

    def _on_unity_run_toggle(self, checked: bool) -> None:
        project = self._services.active_project()
        if project is None:
            return
        override = self._unity_editor_path_input.text().strip() or None
        self._services.projects.set_unity_test_run_settings(project.id, checked, override)
        self._update_unity_run_status()

    def _on_unity_editor_path_changed(self) -> None:
        project = self._services.active_project()
        if project is None:
            return
        override = self._unity_editor_path_input.text().strip() or None
        self._services.projects.set_unity_test_run_settings(
            project.id, self._unity_run_toggle.isChecked(), override
        )
        self._update_unity_run_status()

    def _on_browse_unity_editor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose the Unity Editor executable",
            "",
            "Unity Editor (Unity.exe);;All files (*)",
        )
        if not path:
            return
        self._unity_editor_path_input.setText(path)
        self._on_unity_editor_path_changed()

    def _update_unity_run_status(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        enabled = project.unity_test_run_enabled if project else False
        self._unity_run_toggle.blockSignals(True)
        self._unity_run_toggle.setChecked(bool(enabled))
        self._unity_run_toggle.blockSignals(False)
        self._unity_run_toggle.setEnabled(has_project)

        override = project.unity_editor_path_override if project else None
        self._unity_editor_path_input.blockSignals(True)
        self._unity_editor_path_input.setText(override or "")
        self._unity_editor_path_input.blockSignals(False)
        self._unity_editor_path_input.setEnabled(has_project)
        self._unity_editor_browse_btn.setEnabled(has_project)

        if not has_project:
            self._unity_run_status.setText("")
            return
        if not enabled:
            self._unity_run_status.setText("Not enabled. Turn this on to run tests from Testing.")
            return
        required_version = project.engine_metadata.get("unity_version")
        editor = resolve_unity_editor(required_version, override)
        if editor is not None:
            self._unity_run_status.setText(f"Will run Unity {editor.version} at {editor.path}")
        elif override:
            self._unity_run_status.setText(
                "The manual path above doesn't point to a file — check it."
            )
        elif not required_version:
            self._unity_run_status.setText(
                "Connect a valid Unity folder first so Spiced knows which Unity version to run."
            )
        else:
            self._unity_run_status.setText(
                f"Unity {required_version} isn't installed (or Unity Hub wasn't found). "
                "Install it via Unity Hub, or set a manual path above."
            )

    # --- Automated Build Pipeline opt-in -------------------------------------

    def _build_build_pipeline(self, layout: QVBoxLayout) -> None:
        section = QLabel("Build Pipeline")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)

        intro = QLabel(
            "Off by default. When enabled, Spiced writes a standard Editor build script into "
            "this project (only if one doesn't already exist) and can trigger a headless build "
            "for it — from the Testing screen, or nightly while Spiced is open. The nightly "
            "schedule only fires while Spiced is running: it does not register anything with "
            "Windows Task Scheduler, so a build won't happen on a day Spiced isn't open."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._build_pipeline_toggle = QCheckBox(
            "Allow Spiced to write/trigger this project's build script"
        )
        self._build_pipeline_toggle.toggled.connect(self._on_build_pipeline_toggle)
        layout.addWidget(self._build_pipeline_toggle)

        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Default target platform:"))
        self._build_platform_input = QComboBox()
        self._build_platform_input.addItems(list(unity_build.BUILD_TARGETS))
        self._build_platform_input.currentTextChanged.connect(self._on_build_platform_changed)
        platform_row.addWidget(self._build_platform_input)
        platform_row.addStretch(1)
        layout.addLayout(platform_row)

        schedule_row = QHBoxLayout()
        self._build_schedule_toggle = QCheckBox("Run a build nightly while Spiced is open, at:")
        self._build_schedule_toggle.toggled.connect(self._on_build_schedule_toggle)
        schedule_row.addWidget(self._build_schedule_toggle)
        self._build_schedule_time_input = QLineEdit()
        self._build_schedule_time_input.setPlaceholderText(_HHMM_PLACEHOLDER)
        self._build_schedule_time_input.setFixedWidth(140)
        self._build_schedule_time_input.editingFinished.connect(self._on_build_schedule_time_changed)
        schedule_row.addWidget(self._build_schedule_time_input)
        schedule_row.addStretch(1)
        layout.addLayout(schedule_row)

        self._build_pipeline_status = QLabel()
        self._build_pipeline_status.setObjectName("Muted")
        self._build_pipeline_status.setWordWrap(True)
        layout.addWidget(self._build_pipeline_status)

    def _on_build_pipeline_toggle(self, checked: bool) -> None:
        project = self._services.active_project()
        if project is None:
            return
        platform = self._build_platform_input.currentText()
        self._services.projects.set_build_pipeline_settings(project.id, checked, platform)
        self._update_build_pipeline_status()

    def _on_build_platform_changed(self, platform: str) -> None:
        project = self._services.active_project()
        if project is None:
            return
        self._services.projects.set_build_pipeline_settings(
            project.id, self._build_pipeline_toggle.isChecked(), platform
        )

    def _on_build_schedule_toggle(self, checked: bool) -> None:
        project = self._services.active_project()
        if project is None:
            return
        time_text = self._build_schedule_time_input.text().strip() or None
        self._services.projects.set_build_schedule(project.id, checked, time_text)
        self._update_build_pipeline_status()

    def _on_build_schedule_time_changed(self) -> None:
        project = self._services.active_project()
        if project is None:
            return
        time_text = self._build_schedule_time_input.text().strip() or None
        self._services.projects.set_build_schedule(
            project.id, self._build_schedule_toggle.isChecked(), time_text
        )
        self._update_build_pipeline_status()

    def _update_build_pipeline_status(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        enabled = project.build_pipeline_enabled if project else False

        self._build_pipeline_toggle.blockSignals(True)
        self._build_pipeline_toggle.setChecked(bool(enabled))
        self._build_pipeline_toggle.blockSignals(False)
        self._build_pipeline_toggle.setEnabled(has_project)

        self._build_platform_input.blockSignals(True)
        if project and project.build_target_platform:
            idx = self._build_platform_input.findText(project.build_target_platform)
            if idx >= 0:
                self._build_platform_input.setCurrentIndex(idx)
        self._build_platform_input.blockSignals(False)
        self._build_platform_input.setEnabled(has_project)

        schedule_enabled = project.build_schedule_enabled if project else False
        self._build_schedule_toggle.blockSignals(True)
        self._build_schedule_toggle.setChecked(bool(schedule_enabled))
        self._build_schedule_toggle.blockSignals(False)
        self._build_schedule_toggle.setEnabled(has_project)

        self._build_schedule_time_input.blockSignals(True)
        schedule_time = (project.build_schedule_time if project else "") or ""
        self._build_schedule_time_input.setText(schedule_time)
        self._build_schedule_time_input.blockSignals(False)
        self._build_schedule_time_input.setEnabled(has_project)

        if not has_project:
            self._build_pipeline_status.setText("")
        elif not enabled:
            self._build_pipeline_status.setText(
                "Not enabled. Turn this on to write/trigger a build script from Testing."
            )
        elif not project.path:
            self._build_pipeline_status.setText(
                "Connect a Unity folder above before Spiced can build this project."
            )
        else:
            self._build_pipeline_status.setText(
                f"Enabled. Builds are written under {project.path}\\Builds\\."
            )

    # --- Team Mode (opt-in) -------------------------------------------------

    def _build_team_section(self, layout: QVBoxLayout) -> None:
        section = QLabel("Team")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)

        intro = QLabel(
            "Off by default. Sign in and link the active project to a team so "
            "teammates can share it — everything else in Spiced stays local "
            "unless you do this."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._team_account_status = QLabel()
        self._team_account_status.setObjectName("Muted")
        self._team_account_status.setWordWrap(True)
        layout.addWidget(self._team_account_status)

        account_row = QHBoxLayout()
        account_row.setSpacing(8)
        self._team_signin_btn = QPushButton("Sign in / Sign up")
        self._team_signin_btn.setObjectName("Ghost")
        self._team_signin_btn.clicked.connect(self._on_team_sign_in)
        account_row.addWidget(self._team_signin_btn)
        self._team_signout_btn = QPushButton("Sign out")
        self._team_signout_btn.setObjectName("Ghost")
        self._team_signout_btn.clicked.connect(self._on_team_sign_out)
        account_row.addWidget(self._team_signout_btn)
        account_row.addStretch(1)
        layout.addLayout(account_row)

        create_row = QHBoxLayout()
        create_row.setSpacing(8)
        self._team_name_input = QLineEdit()
        self._team_name_input.setPlaceholderText("New team name")
        self._team_create_btn = QPushButton("Create team")
        self._team_create_btn.clicked.connect(self._on_team_create)
        create_row.addWidget(self._team_name_input, 3)
        create_row.addWidget(self._team_create_btn, 0)
        layout.addLayout(create_row)

        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        self._team_select = QComboBox()
        self._team_link_btn = QPushButton("Link active project")
        self._team_link_btn.clicked.connect(self._on_team_link_project)
        self._team_unlink_btn = QPushButton("Unlink")
        self._team_unlink_btn.setObjectName("Ghost")
        self._team_unlink_btn.clicked.connect(self._on_team_unlink_project)
        link_row.addWidget(self._team_select, 3)
        link_row.addWidget(self._team_link_btn, 0)
        link_row.addWidget(self._team_unlink_btn, 0)
        layout.addLayout(link_row)

        self._team_link_status = QLabel()
        self._team_link_status.setObjectName("Muted")
        self._team_link_status.setWordWrap(True)
        layout.addWidget(self._team_link_status)

    def _on_team_sign_in(self) -> None:
        if not self._services.auth.is_configured():
            QMessageBox.information(
                self,
                "Team Mode not configured",
                "Set SUPABASE_URL and SUPABASE_ANON_KEY in your environment or a local "
                ".env file to use Team Mode.",
            )
            return
        dialog = AuthDialog(self._services.auth, self)
        if dialog.exec() == AuthDialog.DialogCode.Accepted:
            self._refresh_team_section()

    def _on_team_sign_out(self) -> None:
        self._services.auth.log_out()
        self._refresh_team_section()

    def _on_team_create(self) -> None:
        name = self._team_name_input.text().strip()
        if not name:
            QMessageBox.information(self, "Name needed", "Please enter a team name.")
            return
        try:
            self._services.teams.create_team(name)
        except Exception as exc:
            QMessageBox.warning(self, "Couldn't create team", str(exc))
            return
        self._team_name_input.clear()
        self._refresh_team_section()

    def _on_team_link_project(self) -> None:
        project = self._services.active_project()
        team_id = self._team_select.currentData()
        if project is None or not team_id:
            return
        try:
            self._services.teams.link_active_project(team_id, project.id, project.name)
        except Exception as exc:
            QMessageBox.warning(self, "Couldn't link project", str(exc))
            return
        self._refresh_team_section()

    def _on_team_unlink_project(self) -> None:
        project = self._services.active_project()
        team_id = self._team_select.currentData()
        if project is None or not team_id or not project.project_uuid:
            return
        try:
            self._services.teams.unlink_project(team_id, project.project_uuid)
        except Exception as exc:
            QMessageBox.warning(self, "Couldn't unlink project", str(exc))
            return
        self._refresh_team_section()

    def _refresh_team_section(self) -> None:
        auth = self._services.auth
        logged_in = auth.is_logged_in()
        user = auth.current_user()
        self._team_account_status.setText(
            f"Signed in as {user.email}" if logged_in and user else "Not signed in."
        )
        self._team_signin_btn.setEnabled(not logged_in)
        self._team_signout_btn.setEnabled(logged_in)

        for widget in (
            self._team_name_input,
            self._team_create_btn,
            self._team_select,
            self._team_link_btn,
            self._team_unlink_btn,
        ):
            widget.setEnabled(logged_in)

        self._team_select.blockSignals(True)
        self._team_select.clear()
        if logged_in:
            try:
                teams = self._services.teams.list_teams()
            except (BackendAPIError, NotAuthenticatedError) as exc:
                self._team_link_status.setText(f"Couldn't reach the team backend: {exc}")
                teams = []
            for team in teams:
                self._team_select.addItem(team.name, team.id)
        self._team_select.blockSignals(False)

        project = self._services.active_project()
        if not logged_in:
            self._team_link_status.setText("")
        elif project is None:
            self._team_link_status.setText("Select or create a project above to link it.")
        elif project.project_uuid:
            self._team_link_status.setText(
                f"{project.name} has a stable team id ({project.project_uuid[:8]}…). "
                "Pick a team above and click Link, or Unlink to remove it from that team."
            )
        else:
            self._team_link_status.setText(
                f"{project.name} isn't linked to a team yet — pick one above and click Link."
            )

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
        self._refresh_team_section()

    def _update_detail(self) -> None:
        self._update_unity_run_status()
        self._update_build_pipeline_status()
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
