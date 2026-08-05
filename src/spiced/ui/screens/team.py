"""Team: Unified Task Board (Kanban) + discipline self-service + comments.

New sidebar page (Phase J, section 8 part 2, Cross-Role & Team Glue). Only
meaningful for a team-linked project -- TeamTask/Comment/discipline all
require a ``team_id``, so this screen shows a plain explanatory message
instead of the board for a solo/local-only project, same discipline as the
Player Crash panel on the Testing screen.

The board is a simple three-column (Open / In Progress / Done) layout with
move-via-button interaction rather than drag-and-drop -- a documented,
deliberate scope call per the phase plan ("a simple drag-free 'move via
dropdown/button' interaction is fine, full drag-and-drop is a nice-to-have
not a requirement").
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.backend_client import config as backend_config
from spiced.backend_client.api_client import TeamTask
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.comments_widget import CommentsWidget

STATUSES = ["open", "in_progress", "done"]
STATUS_LABELS = {"open": "Open", "in_progress": "In Progress", "done": "Done"}

# A small suggested set, not a rigid enum -- indie teams don't fit neat
# boxes, so the combo box below stays editable (a free-ish string).
SUGGESTED_DISCIPLINES = ["programmer", "artist", "audio", "animation", "design"]

_USER_ROLE = 32


class _TaskLoadWorker(QObject):
    done = Signal(object, list)  # team_id | None, list[TeamTask]
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            team = self._services.teams.find_team_for_project(self._project_uuid)
            if team is None:
                self.done.emit(None, [])
                return
            tasks = self._services.teams.list_tasks(team.id, project_uuid=self._project_uuid)
            self.done.emit(team.id, tasks)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't load the task board: {exc}")


class _TaskMutateWorker(QObject):
    done = Signal()
    failed = Signal(str)

    def __init__(self, action) -> None:
        super().__init__()
        self._action = action

    def run(self) -> None:
        try:
            self._action()
            self.done.emit()
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"That didn't go through: {exc}")


class _DisciplineLoadWorker(QObject):
    done = Signal(object)  # str | None
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            self.done.emit(self._services.teams.my_discipline(self._project_uuid))
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't load your discipline: {exc}")


class TeamScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._tasks: list[TeamTask] = []
        self._selected_task_id: str | None = None
        self._team_id: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(12)

        title = QLabel("Team")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        self._build_discipline_section(layout)
        self._build_mobile_link_section(layout)
        self._build_new_task_section(layout)
        self._build_board(layout)
        self._build_selected_task_section(layout)

        self.refresh()

    # --- Companion Mobile View (Phase L, Stretch tier): the link ------------
    #
    # The backend's /mobile/teams/{team_id} route (routers/mobile.py) needs a
    # bearer token, but it's a plain HTML page a phone browser navigates to
    # directly -- it can't set an Authorization header the way this desktop
    # app's own API calls do. So the desktop app is the one place that can
    # hand the developer a ready-to-open link carrying the token as a
    # ?token= query param (see app.auth.get_current_user_for_html's own
    # docstring on the backend side for why that fallback exists). This is
    # the SAME long-lived session token this app already uses for every
    # other authenticated call -- not a separate short-lived token minting
    # flow, which would need new backend infrastructure this session didn't
    # build. Copied to the clipboard, never displayed/logged in full, since
    # it is a live credential for as long as this session's token is valid.

    def _build_mobile_link_section(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Companion mobile view")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "A read-only page (build alerts, player crash reports, open tasks) you can open "
            "on your phone. The link carries your current sign-in -- keep it private, same as "
            "a password."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._mobile_link_btn = QPushButton("Copy mobile link")
        self._mobile_link_btn.setObjectName("Ghost")
        self._mobile_link_btn.clicked.connect(self._on_copy_mobile_link)
        row.addWidget(self._mobile_link_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._mobile_link_status = QLabel("")
        self._mobile_link_status.setObjectName("Muted")
        self._mobile_link_status.setWordWrap(True)
        layout.addWidget(self._mobile_link_status)

    def _on_copy_mobile_link(self) -> None:
        project = self._services.active_project()
        token = self._services.auth.access_token()
        if project is None or not project.project_uuid or self._team_id is None:
            self._mobile_link_status.setText(
                "Select a team-linked project first -- the board above must finish loading."
            )
            return
        if not token:
            self._mobile_link_status.setText("Sign in to Small-Team Mode first (Settings).")
            return

        base = backend_config.backend_base_url().rstrip("/")
        link = (
            f"{base}/mobile/teams/{self._team_id}"
            f"?project_uuid={project.project_uuid}&token={token}"
        )
        QApplication.clipboard().setText(link)
        self._mobile_link_status.setText(
            "Link copied to clipboard. It's private -- treat it like a password."
        )

    # --- Discipline self-service (Role-Based Dashboards, #4) ------------------

    def _build_discipline_section(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Your discipline")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        intro = QLabel(
            "A free-ish label, not a rigid role -- pick a suggested value or type your own. "
            "Used to route feedback/bugs to the right person and to personalize your Project "
            "Context panel."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        row = QHBoxLayout()
        self._discipline_input = QComboBox()
        self._discipline_input.setEditable(True)
        self._discipline_input.addItem("")
        self._discipline_input.addItems(SUGGESTED_DISCIPLINES)
        row.addWidget(self._discipline_input, 1)
        self._discipline_save_btn = QPushButton("Save")
        self._discipline_save_btn.clicked.connect(self._on_save_discipline)
        row.addWidget(self._discipline_save_btn)
        layout.addLayout(row)

        self._discipline_status = QLabel("")
        self._discipline_status.setObjectName("Muted")
        self._discipline_status.setWordWrap(True)
        layout.addWidget(self._discipline_status)

    def _on_save_discipline(self) -> None:
        project = self._services.active_project()
        if project is None or not project.project_uuid or self._team_id is None:
            return
        value = self._discipline_input.currentText().strip() or None
        self._discipline_save_btn.setEnabled(False)

        worker = _TaskMutateWorker(
            lambda: self._services.teams.set_my_discipline(self._team_id, value)
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_discipline_saved)
        worker.failed.connect(self._on_discipline_save_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_discipline_saved(self) -> None:
        self._discipline_save_btn.setEnabled(True)
        self._discipline_status.setText("Saved.")

    def _on_discipline_save_failed(self, message: str) -> None:
        self._discipline_save_btn.setEnabled(True)
        self._discipline_status.setText(message)

    def _refresh_discipline(self) -> None:
        project = self._services.active_project()
        if project is None or not project.project_uuid:
            return
        worker = _DisciplineLoadWorker(self._services, project.project_uuid)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_discipline_loaded)
        worker.failed.connect(lambda _msg: None)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_discipline_loaded(self, discipline: str | None) -> None:
        self._discipline_input.setCurrentText(discipline or "")

    # --- New task -------------------------------------------------------------

    def _build_new_task_section(self, layout: QVBoxLayout) -> None:
        heading = QLabel("New task")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        row = QHBoxLayout()
        self._new_task_title = QLineEdit()
        self._new_task_title.setPlaceholderText("Task title")
        row.addWidget(self._new_task_title, 2)
        self._new_task_discipline = QComboBox()
        self._new_task_discipline.setEditable(True)
        self._new_task_discipline.addItem("")
        self._new_task_discipline.addItems(SUGGESTED_DISCIPLINES)
        row.addWidget(self._new_task_discipline, 1)
        self._new_task_btn = QPushButton("Add task")
        self._new_task_btn.clicked.connect(self._on_new_task)
        row.addWidget(self._new_task_btn)
        layout.addLayout(row)

    def _on_new_task(self) -> None:
        project = self._services.active_project()
        title = self._new_task_title.text().strip()
        if project is None or not project.project_uuid or self._team_id is None:
            QMessageBox.information(
                self, "Team board unavailable",
                "Link this project to a team on the Projects screen first.",
            )
            return
        if not title:
            QMessageBox.information(self, "Missing title", "Give the task a title first.")
            return
        discipline = self._new_task_discipline.currentText().strip() or None
        project_uuid = project.project_uuid
        team_id = self._team_id
        self._new_task_btn.setEnabled(False)

        worker = _TaskMutateWorker(
            lambda: self._services.teams.create_task(
                team_id, title, project_uuid=project_uuid, assigned_discipline=discipline
            )
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_task_mutated)
        worker.failed.connect(self._on_task_mutate_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()
        self._new_task_title.clear()

    # --- Board ------------------------------------------------------------------

    def _build_board(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Board")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        columns = QHBoxLayout()
        self._columns: dict[str, QListWidget] = {}
        for status in STATUSES:
            col = QVBoxLayout()
            label = QLabel(STATUS_LABELS[status])
            label.setObjectName("Muted")
            col.addWidget(label)
            list_widget = QListWidget()
            list_widget.setMinimumHeight(220)
            list_widget.currentItemChanged.connect(self._on_task_selected)
            col.addWidget(list_widget)
            self._columns[status] = list_widget
            columns.addLayout(col)
        layout.addLayout(columns)

    def _on_task_selected(self, current: QListWidgetItem | None, _prev=None) -> None:
        if current is None:
            return
        self._selected_task_id = current.data(_USER_ROLE)
        self._refresh_selected_task_section()

    def _refresh_board(self) -> None:
        for status in STATUSES:
            self._columns[status].clear()
        for task in self._tasks:
            status = task.status if task.status in self._columns else "open"
            discipline = f" [{task.assigned_discipline}]" if task.assigned_discipline else ""
            item = QListWidgetItem(f"{task.title}{discipline}")
            item.setData(_USER_ROLE, task.id)
            self._columns[status].addItem(item)

    # --- Selected task detail + move/delete + comments -------------------------

    def _build_selected_task_section(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Selected task")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._selected_task_label = QLabel("Select a task on the board above.")
        self._selected_task_label.setObjectName("Muted")
        self._selected_task_label.setWordWrap(True)
        layout.addWidget(self._selected_task_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("Move to:"))
        self._move_status_box = QComboBox()
        for status in STATUSES:
            self._move_status_box.addItem(STATUS_LABELS[status], status)
        row.addWidget(self._move_status_box)
        self._move_btn = QPushButton("Move")
        self._move_btn.clicked.connect(self._on_move_task)
        row.addWidget(self._move_btn)
        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setObjectName("Ghost")
        self._delete_btn.clicked.connect(self._on_delete_task)
        row.addWidget(self._delete_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._comments = CommentsWidget(self._services)
        layout.addWidget(self._comments)

    def _selected_task(self) -> TeamTask | None:
        return next((t for t in self._tasks if t.id == self._selected_task_id), None)

    def _refresh_selected_task_section(self) -> None:
        task = self._selected_task()
        project = self._services.active_project()
        if task is None:
            self._selected_task_label.setText("Select a task on the board above.")
            self._comments.set_subject(None, "task", "")
            return
        discipline = task.assigned_discipline or "unassigned"
        source = f" (from {task.source_type}: {task.source_ref})" if task.source_ref else ""
        self._selected_task_label.setText(
            f"{task.title} -- {STATUS_LABELS.get(task.status, task.status)}, {discipline}{source}"
        )
        project_uuid = project.project_uuid if project else None
        self._comments.set_subject(project_uuid, "task", task.id)

    def _on_move_task(self) -> None:
        task = self._selected_task()
        if task is None or self._team_id is None:
            return
        new_status = self._move_status_box.currentData()
        team_id = self._team_id
        worker = _TaskMutateWorker(
            lambda: self._services.teams.update_task(team_id, task.id, status_value=new_status)
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_task_mutated)
        worker.failed.connect(self._on_task_mutate_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_delete_task(self) -> None:
        task = self._selected_task()
        if task is None or self._team_id is None:
            return
        team_id = self._team_id
        self._selected_task_id = None
        worker = _TaskMutateWorker(lambda: self._services.teams.delete_task(team_id, task.id))
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_task_mutated)
        worker.failed.connect(self._on_task_mutate_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_task_mutated(self) -> None:
        self._new_task_btn.setEnabled(True)
        self.usage_changed.emit()
        self.refresh()

    def _on_task_mutate_failed(self, message: str) -> None:
        self._new_task_btn.setEnabled(True)
        QMessageBox.warning(self, "Something went wrong", message)

    # --- Refresh -----------------------------------------------------------

    def refresh(self) -> None:
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose one on the Projects screen."
            )
            self._team_id = None
            self._tasks = []
            self._refresh_board()
            self._refresh_selected_task_section()
            return
        if not project.project_uuid:
            self._context_label.setText(
                f"Active project: {project.name}. The Team board only applies to team-linked "
                "projects -- link this project to a team on the Projects screen to use it."
            )
            self._team_id = None
            self._tasks = []
            self._refresh_board()
            self._refresh_selected_task_section()
            return

        self._context_label.setText(f"Active project: {project.name} (team-linked).")
        self._refresh_discipline()
        self._refresh_tasks(project.project_uuid)

    def _refresh_tasks(self, project_uuid: str) -> None:
        worker = _TaskLoadWorker(self._services, project_uuid)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_tasks_loaded)
        worker.failed.connect(self._on_tasks_load_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_tasks_loaded(self, team_id: str | None, tasks: list[TeamTask]) -> None:
        self._team_id = team_id
        self._tasks = tasks
        self._refresh_board()
        self._refresh_selected_task_section()

    def _on_tasks_load_failed(self, message: str) -> None:
        self._selected_task_label.setText(message)
