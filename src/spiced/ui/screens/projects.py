"""Projects screen: create projects, pick one as active, connect a Unity folder.

Master-detail layout (Frutiger Aqua redesign): a left-hand project picker
(create form + a scrollable list of glass-card rows, active one aqua-
highlighted) drives a right-hand detail column for whichever project is
active. The four opt-in settings (Run Unity Tests, Build Pipeline,
Pre-Commit Review, Design Doc Sync) are collapsible accordion sections
(``ui.widgets.accordion.AccordionSection``) so scanning what's on doesn't
require expanding anything, and only one stays open at a time to keep the
column short. This is a layout/disclosure change only -- every handler and
``_update_*_status`` method below keeps its original settings logic
unchanged; the only new responsibility they pick up is also syncing a small
On/Off status pill in the section's collapsed header.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.backend_client.api_client import BackendAPIError, NotAuthenticatedError
from spiced.connectors import unity_build
from spiced.core.precommit_hook import ForeignHookExistsError, NotAGitRepoError
from spiced.core.unity_test_runner import resolve_unity_editor
from spiced.storage.projects import Project
from spiced.ui.auth_dialog import AuthDialog
from spiced.ui.widgets.accordion import AccordionSection
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox

_HHMM_PLACEHOLDER = "HH:MM, 24h (e.g. 02:00)"


class ProjectsScreen(QWidget):
    """Create projects, select the active one, and connect a Unity folder."""

    projects_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._projects = services.projects
        self._accordions: list[AccordionSection] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.setSpacing(14)

        title = QLabel("Projects")
        title.setObjectName("ScreenTitle")
        outer.addWidget(title)

        intro = QLabel(
            "Add a game project to keep Spiced's help organized. Pick one as active, then "
            "connect its Unity folder. Nothing here leaves your machine."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        outer.addWidget(intro)

        columns = QHBoxLayout()
        columns.setSpacing(18)
        outer.addLayout(columns, 1)
        columns.addWidget(self._build_left_column(), 0)
        columns.addWidget(self._build_right_column(), 1)

        self.refresh()

    # --- Left column: project picker ----------------------------------------

    def _build_left_column(self) -> QWidget:
        column = QWidget()
        column.setFixedWidth(300)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        new_card = _card()
        new_layout = new_card.layout()
        new_heading = QLabel("New project")
        new_heading.setObjectName("CardTitle")
        new_layout.addWidget(new_heading)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Project name (e.g. Moonlit Depths)")
        self._name_input.returnPressed.connect(self._create)
        new_layout.addWidget(self._name_input)
        self._engine_input = ScrollSafeComboBox()
        self._engine_input.addItems(["Unity", "Godot", "Unreal", "Other"])
        new_layout.addWidget(self._engine_input)
        self._create_btn = PillButton("Create project")
        self._create_btn.clicked.connect(self._create)
        new_layout.addWidget(self._create_btn)

        # Explicit, safe demo loader. Seeds one bundled sample project so every
        # screen has realistic data. No Unity, no AI, no network — and it never
        # touches projects you created yourself.
        self._demo_btn = PillButton("Load demo project", ghost=True)
        self._demo_btn.clicked.connect(self._load_demo)
        new_layout.addWidget(self._demo_btn)
        layout.addWidget(new_card)

        section = QLabel("Your projects")
        section.setObjectName("SectionTitle")
        layout.addWidget(section)

        self._empty = QLabel("No projects yet. Create your first one above.")
        self._empty.setObjectName("Muted")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)

        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        list_content = QWidget()
        list_content.setObjectName("ScrollContent")
        self._project_list_layout = QVBoxLayout(list_content)
        self._project_list_layout.setContentsMargins(0, 0, 0, 0)
        self._project_list_layout.setSpacing(8)
        self._project_list_layout.addStretch(1)
        list_scroll.setWidget(list_content)
        layout.addWidget(list_scroll, 1)

        return column

    # --- Right column: active project detail --------------------------------

    def _build_right_column(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("ScrollContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header_card = _card()
        header_layout = header_card.layout()
        self._detail = QLabel()
        self._detail.setObjectName("CardTitle")
        self._detail.setWordWrap(True)
        header_layout.addWidget(self._detail)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._folder_btn = PillButton("Choose Unity Folder…")
        self._folder_btn.clicked.connect(self._choose_folder)
        controls.addWidget(self._folder_btn)
        controls.addStretch(1)
        header_layout.addLayout(controls)
        layout.addWidget(header_card)

        self._build_unity_test_run(self._new_accordion(layout, "Run Unity Tests"))
        self._build_build_pipeline(self._new_accordion(layout, "Build Pipeline"))
        self._build_precommit_review(self._new_accordion(layout, "Pre-Commit Review"))
        self._build_design_doc_sync(self._new_accordion(layout, "Design Doc Sync"))

        self._build_team_section(layout)
        layout.addStretch(1)
        return scroll

    def _new_accordion(self, layout: QVBoxLayout, title: str) -> AccordionSection:
        accordion = AccordionSection(title)
        accordion.toggled.connect(
            lambda expanded, a=accordion: self._on_accordion_toggled(a, expanded)
        )
        self._accordions.append(accordion)
        layout.addWidget(accordion)
        return accordion

    def _on_accordion_toggled(self, accordion: AccordionSection, expanded: bool) -> None:
        """Only one settings section stays open at a time, per the redesign."""
        if not expanded:
            return
        for other in self._accordions:
            if other is not accordion:
                other.set_expanded(False)

    # --- Run Unity Tests opt-in ---------------------------------------------

    def _build_unity_test_run(self, accordion: AccordionSection) -> None:
        layout = accordion.body_layout
        intro = QLabel(
            "Off by default. When enabled, the Testing screen can launch this project's "
            "Unity Editor headlessly to run its tests — the one place Spiced executes an "
            "external process rather than only reading text you give it."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._unity_run_pill = _status_pill()
        accordion.header_extra.addWidget(self._unity_run_pill)
        self._unity_run_toggle = QCheckBox(
            "Allow Spiced to run this project's Unity tests"
        )
        self._unity_run_toggle.toggled.connect(self._on_unity_run_toggle)
        accordion.header_extra.addWidget(self._unity_run_toggle)

        override_row = QHBoxLayout()
        override_row.addWidget(QLabel("Unity Editor path (optional override):"))
        self._unity_editor_path_input = QLineEdit()
        self._unity_editor_path_input.setPlaceholderText(
            "Leave blank to auto-detect via Unity Hub"
        )
        self._unity_editor_path_input.editingFinished.connect(self._on_unity_editor_path_changed)
        override_row.addWidget(self._unity_editor_path_input, 1)
        self._unity_editor_browse_btn = PillButton("Browse…")
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
        self.projects_changed.emit()

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
        _set_pill_state(self._unity_run_pill, bool(enabled))

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

    def _build_build_pipeline(self, accordion: AccordionSection) -> None:
        layout = accordion.body_layout
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

        self._build_pipeline_pill = _status_pill()
        accordion.header_extra.addWidget(self._build_pipeline_pill)
        self._build_pipeline_toggle = QCheckBox(
            "Allow Spiced to write/trigger this project's build script"
        )
        self._build_pipeline_toggle.toggled.connect(self._on_build_pipeline_toggle)
        accordion.header_extra.addWidget(self._build_pipeline_toggle)

        platform_row = QHBoxLayout()
        platform_row.addWidget(QLabel("Default target platform:"))
        self._build_platform_input = ScrollSafeComboBox()
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
        self.projects_changed.emit()

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
        _set_pill_state(self._build_pipeline_pill, bool(enabled))

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

    # --- Pre-Commit Review opt-in -------------------------------------------

    def _build_precommit_review(self, accordion: AccordionSection) -> None:
        layout = accordion.body_layout
        intro = QLabel(
            "Off by default. When enabled, click \"Install hook\" to add a .git/hooks/"
            "pre-commit script to this project that flags obvious TODOs, stray Debug.Log/"
            "print statements, leftover merge-conflict markers, and very large staged files "
            "on every commit — local and instant, no AI or network call. It's a heads-up "
            "only: the hook always lets the commit through, never blocks it. Spiced will "
            "never overwrite a pre-commit hook it didn't create — if one already exists, "
            "you'll be asked to back it up or remove it yourself first."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._precommit_pill = _status_pill()
        accordion.header_extra.addWidget(self._precommit_pill)
        self._precommit_toggle = QCheckBox("Allow Spiced to install a pre-commit hook")
        self._precommit_toggle.toggled.connect(self._on_precommit_toggle)
        accordion.header_extra.addWidget(self._precommit_toggle)

        row = QHBoxLayout()
        self._precommit_install_btn = PillButton("Install hook")
        self._precommit_install_btn.clicked.connect(self._on_precommit_install)
        row.addWidget(self._precommit_install_btn)
        self._precommit_uninstall_btn = PillButton("Remove hook", ghost=True)
        self._precommit_uninstall_btn.clicked.connect(self._on_precommit_uninstall)
        row.addWidget(self._precommit_uninstall_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._precommit_status = QLabel()
        self._precommit_status.setObjectName("Muted")
        self._precommit_status.setWordWrap(True)
        layout.addWidget(self._precommit_status)

    def _on_precommit_toggle(self, checked: bool) -> None:
        project = self._services.active_project()
        if project is None:
            return
        self._services.projects.set_precommit_review_settings(project.id, checked)
        self._update_precommit_status()
        self.projects_changed.emit()

    def _on_precommit_install(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            QMessageBox.information(
                self, "Pick a project first", "Select a project with a connected folder above."
            )
            return
        if not project.precommit_review_enabled:
            QMessageBox.information(
                self, "Turn this on first", "Check the box above before installing the hook."
            )
            return
        try:
            result = self._services.install_precommit_hook(project)
        except NotAGitRepoError as exc:
            QMessageBox.warning(self, "Not a git repository", str(exc))
            return
        except ForeignHookExistsError as exc:
            QMessageBox.warning(self, "An existing hook is already there", str(exc))
            return
        QMessageBox.information(
            self, "Hook installed", f"Installed at {result.hook_path}."
        )
        self._update_precommit_status()

    def _on_precommit_uninstall(self) -> None:
        project = self._services.active_project()
        if project is None or not project.path:
            return
        removed = self._services.uninstall_precommit_hook(project)
        message = (
            "Removed the Spiced-installed hook."
            if removed
            else "No Spiced-installed hook was found to remove."
        )
        QMessageBox.information(self, "Pre-Commit Review", message)
        self._update_precommit_status()

    def _update_precommit_status(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        enabled = project.precommit_review_enabled if project else False

        self._precommit_toggle.blockSignals(True)
        self._precommit_toggle.setChecked(bool(enabled))
        self._precommit_toggle.blockSignals(False)
        self._precommit_toggle.setEnabled(has_project)
        self._precommit_install_btn.setEnabled(has_project)
        self._precommit_uninstall_btn.setEnabled(has_project)
        _set_pill_state(self._precommit_pill, bool(enabled))

        if not has_project:
            self._precommit_status.setText("")
        elif not project.path:
            self._precommit_status.setText("Connect a Unity folder above first.")
        elif not enabled:
            self._precommit_status.setText("Not enabled. Check the box above, then Install hook.")
        else:
            self._precommit_status.setText(
                "Enabled. Click \"Install hook\" to add it to this project's git hooks "
                "directory, or \"Remove hook\" to take it back out."
            )

    # --- Design Doc Sync opt-in ----------------------------------------------

    def _build_design_doc_sync(self, accordion: AccordionSection) -> None:
        layout = accordion.body_layout
        intro = QLabel(
            "Off by default. When enabled, the Debugging Buddy page's Design Drift section "
            "lets you upload or paste your own game's design doc for this project and compare "
            "it against Spiced's Auto-Generated Dev Docs — flagging drift either direction as "
            "a heads-up to reconcile the doc or rein in scope, never a verdict."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._design_doc_sync_pill = _status_pill()
        accordion.header_extra.addWidget(self._design_doc_sync_pill)
        self._design_doc_sync_toggle = QCheckBox(
            "Enable Design Doc Sync for this project"
        )
        self._design_doc_sync_toggle.toggled.connect(self._on_design_doc_sync_toggle)
        accordion.header_extra.addWidget(self._design_doc_sync_toggle)

        self._design_doc_sync_status = QLabel()
        self._design_doc_sync_status.setObjectName("Muted")
        self._design_doc_sync_status.setWordWrap(True)
        layout.addWidget(self._design_doc_sync_status)

    def _on_design_doc_sync_toggle(self, checked: bool) -> None:
        project = self._services.active_project()
        if project is None:
            return
        self._services.projects.set_design_doc_sync_settings(project.id, checked)
        self._update_design_doc_sync_status()
        self.projects_changed.emit()

    def _update_design_doc_sync_status(self) -> None:
        project = self._services.active_project()
        has_project = project is not None
        enabled = project.design_doc_sync_enabled if project else False

        self._design_doc_sync_toggle.blockSignals(True)
        self._design_doc_sync_toggle.setChecked(bool(enabled))
        self._design_doc_sync_toggle.blockSignals(False)
        self._design_doc_sync_toggle.setEnabled(has_project)
        _set_pill_state(self._design_doc_sync_pill, bool(enabled))

        if not has_project:
            self._design_doc_sync_status.setText("")
        elif not enabled:
            self._design_doc_sync_status.setText(
                "Not enabled. Turn this on to use Design Drift on the Debugging Buddy page."
            )
        else:
            self._design_doc_sync_status.setText(
                "Enabled. Upload or paste your design doc on the Debugging Buddy page's "
                "Design Drift section."
            )

    # --- Team Mode (opt-in) -------------------------------------------------

    def _build_team_section(self, layout: QVBoxLayout) -> None:
        card = _card()
        card_layout = card.layout()
        heading = QLabel("Team")
        heading.setObjectName("CardTitle")
        card_layout.addWidget(heading)

        intro = QLabel(
            "Off by default. Sign in and link the active project to a team so "
            "teammates can share it — everything else in Spiced stays local "
            "unless you do this."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        card_layout.addWidget(intro)

        self._team_account_status = QLabel()
        self._team_account_status.setObjectName("Muted")
        self._team_account_status.setWordWrap(True)
        card_layout.addWidget(self._team_account_status)

        account_row = QHBoxLayout()
        account_row.setSpacing(8)
        self._team_signin_btn = PillButton("Sign in / Sign up", ghost=True)
        self._team_signin_btn.clicked.connect(self._on_team_sign_in)
        account_row.addWidget(self._team_signin_btn)
        self._team_signout_btn = PillButton("Sign out", ghost=True)
        self._team_signout_btn.clicked.connect(self._on_team_sign_out)
        account_row.addWidget(self._team_signout_btn)
        account_row.addStretch(1)
        card_layout.addLayout(account_row)

        create_row = QHBoxLayout()
        create_row.setSpacing(8)
        self._team_name_input = QLineEdit()
        self._team_name_input.setPlaceholderText("New team name")
        self._team_create_btn = PillButton("Create team")
        self._team_create_btn.clicked.connect(self._on_team_create)
        create_row.addWidget(self._team_name_input, 3)
        create_row.addWidget(self._team_create_btn, 0)
        card_layout.addLayout(create_row)

        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        self._team_select = ScrollSafeComboBox()
        self._team_link_btn = PillButton("Link active project")
        self._team_link_btn.clicked.connect(self._on_team_link_project)
        self._team_unlink_btn = PillButton("Unlink", ghost=True)
        self._team_unlink_btn.clicked.connect(self._on_team_unlink_project)
        link_row.addWidget(self._team_select, 3)
        link_row.addWidget(self._team_link_btn, 0)
        link_row.addWidget(self._team_unlink_btn, 0)
        card_layout.addLayout(link_row)

        self._team_link_status = QLabel()
        self._team_link_status.setObjectName("Muted")
        self._team_link_status.setWordWrap(True)
        card_layout.addWidget(self._team_link_status)

        layout.addWidget(card)

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

    def _on_project_card_clicked(self, project_id: int) -> None:
        active = self._services.active_project()
        if active is not None and active.id == project_id:
            return
        self._services.set_active_project(project_id)
        self._update_detail()
        self._refresh_project_cards()
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
        self._refresh_project_cards()
        self._update_detail()
        self._refresh_team_section()

    def _refresh_project_cards(self) -> None:
        active = self._services.active_project()
        items = self._projects.list_projects()
        # Last layout item is the trailing stretch (added once in
        # _build_left_column) -- clear everything before it and re-add rows.
        while self._project_list_layout.count() > 1:
            item = self._project_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for project in items:
            is_active = active is not None and project.id == active.id
            card = _ProjectCard(project, is_active)
            card.clicked.connect(self._on_project_card_clicked)
            self._project_list_layout.insertWidget(self._project_list_layout.count() - 1, card)
        self._empty.setVisible(not items)

    def _update_detail(self) -> None:
        self._update_unity_run_status()
        self._update_build_pipeline_status()
        self._update_precommit_status()
        self._update_design_doc_sync_status()
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


# --- Small widget helpers ----------------------------------------------------


class _ProjectCard(QFrame):
    """One glass-card row in the left column's project picker (replaces the
    old QListWidget row) -- the active project gets the aqua-highlighted
    look via the ``active`` dynamic property (see ui.theme's
    ``QFrame#ProjectCard[active="true"]`` rule)."""

    clicked = Signal(int)

    def __init__(self, project: Project, active: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectCard")
        self.setProperty("active", "true" if active else "false")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._project_id = project.id

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(2)
        name = QLabel(project.name)
        name.setObjectName("CardTitle")
        layout.addWidget(name)
        marker = "✓ Unity" if project.is_valid_unity else project.engine
        meta = QLabel(f"{marker}  ·  {project.created_at}")
        meta.setObjectName("Muted")
        layout.addWidget(meta)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit(self._project_id)
        super().mousePressEvent(event)


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("Card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(8)
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 5)
    shadow.setColor(QColor(20, 10, 40, 80))
    frame.setGraphicsEffect(shadow)
    return frame


def _status_pill() -> QLabel:
    pill = QLabel("Off")
    pill.setObjectName("StatusPill")
    pill.setProperty("state", "off")
    return pill


def _set_pill_state(pill: QLabel, enabled: bool) -> None:
    pill.setText("On" if enabled else "Off")
    pill.setProperty("state", "on" if enabled else "off")
    pill.style().unpolish(pill)
    pill.style().polish(pill)
