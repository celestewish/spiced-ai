"""Team: discipline self-service + Companion Mobile View.

New sidebar page (Phase J, section 8 part 2, Cross-Role & Team Glue). Only
meaningful for a team-linked project -- discipline and the mobile link both
require a ``team_id``, so this screen shows a plain explanatory message
instead for a solo/local-only project, same discipline as the Player Crash
panel on the Testing screen.

The Unified Task Board (Kanban) previously lived here too; it's been
removed by product decision -- not competing with a dedicated project-
management tool (Inferno). The backend TeamTask API is untouched in case a
board resurfaces elsewhere; this is a UI-only removal.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.backend_client import config as backend_config
from spiced.ui.thread_utils import launch_worker
from spiced.ui.widgets.pill_button import PillButton
from spiced.ui.widgets.scroll_safe_combo_box import ScrollSafeComboBox

# A small suggested set, not a rigid enum -- indie teams don't fit neat
# boxes, so the combo box below stays editable (a free-ish string).
SUGGESTED_DISCIPLINES = ["programmer", "artist", "audio", "animation", "design"]


class _TeamLinkWorker(QObject):
    """Resolves just the active project's team (if any) -- discipline and
    the mobile link both need only this, not the full task list the old
    board used to load."""

    done = Signal(object)  # team_id | None
    failed = Signal(str)

    def __init__(self, services: Services, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            team = self._services.teams.find_team_for_project(self._project_uuid)
            self.done.emit(team.id if team else None)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't check this project's team: {exc}")


class _TaskMutateWorker(QObject):
    """Kept generic (not board-specific despite the name) -- also used by
    discipline saves, which are a one-shot "do this, tell me if it failed"
    call same shape as everything the old board used it for."""

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


class TeamScreen(QWidget):
    usage_changed = Signal()

    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services
        self._team_id: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("ScrollContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("Team")
        title.setObjectName("ScreenTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self._mode_pill = QLabel("Solo-Dev Mode")
        self._mode_pill.setObjectName("UsagePill")
        title_row.addWidget(self._mode_pill)
        layout.addLayout(title_row)

        self._context_label = QLabel()
        self._context_label.setObjectName("Muted")
        self._context_label.setWordWrap(True)
        layout.addWidget(self._context_label)

        two_up = QHBoxLayout()
        two_up.setSpacing(14)
        discipline_card = _card()
        self._build_discipline_section(discipline_card.layout())
        two_up.addWidget(discipline_card, 1)
        mobile_card = _card()
        self._build_mobile_link_section(mobile_card.layout())
        two_up.addWidget(mobile_card, 1)
        layout.addLayout(two_up)
        layout.addStretch(1)

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
        heading.setObjectName("CardTitle")
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
        self._mobile_link_btn = PillButton("Copy mobile link", ghost=True)
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
                "Select a team-linked project first -- the link above needs it to load."
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
        heading.setObjectName("CardTitle")
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
        self._discipline_input = ScrollSafeComboBox()
        self._discipline_input.setEditable(True)
        self._discipline_input.addItem("")
        self._discipline_input.addItems(SUGGESTED_DISCIPLINES)
        row.addWidget(self._discipline_input, 1)
        self._discipline_save_btn = PillButton("Save")
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

    # --- Refresh -----------------------------------------------------------

    def refresh(self) -> None:
        self._mode_pill.setText(
            "Team Mode" if self._services.team_mode_enabled() else "Solo-Dev Mode"
        )
        project = self._services.active_project()
        if project is None:
            self._context_label.setText(
                "No active project selected. Choose one on the Projects screen."
            )
            self._team_id = None
            return
        if not project.project_uuid:
            self._context_label.setText(
                f"Active project: {project.name}. Discipline and the mobile link only apply to "
                "team-linked projects -- link this project to a team on the Projects screen."
            )
            self._team_id = None
            return

        self._context_label.setText(f"Active project: {project.name} (team-linked).")
        self._refresh_discipline()
        self._refresh_team_link(project.project_uuid)

    def _refresh_team_link(self, project_uuid: str) -> None:
        worker = _TeamLinkWorker(self._services, project_uuid)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_team_link_loaded)
        worker.failed.connect(self._on_team_link_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_team_link_loaded(self, team_id: str | None) -> None:
        self._team_id = team_id

    def _on_team_link_failed(self, message: str) -> None:
        self._mobile_link_status.setText(message)
