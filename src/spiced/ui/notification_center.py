"""Notification Center: bell icon + dropdown inbox (Phase K, section 9 part 1,
Core tier).

QTimer-based poller mirroring ``ui.build_scheduler``'s pattern exactly: a
QTimer fires periodically while Spiced is running and polls the backend's
unread notifications for the active project's team (if any), off a worker
thread via ``launch_worker`` so the UI thread never blocks on the network
call. Every poll's results are bucketed by each notification's event kind's
configured delivery cadence (``core.notification_center.bucket_by_cadence``)
-- only the "due" ones actually update the bell's badge/dropdown; hourly/
daily ones stay unread on the backend but are held back from view here until
their digest window is due.
"""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.backend_client.api_client import Notification, NotificationPreference
from spiced.core.notification_center import bucket_by_cadence
from spiced.storage.projects import Project
from spiced.ui.thread_utils import launch_worker

# Frequent enough that a new notification feels reasonably live, cheap
# enough to poll continuously in the background.
_POLL_INTERVAL_MS = 120_000
_ITEM_ROLE = int(Qt.ItemDataRole.UserRole)


class _TeamLookupWorker(QObject):
    """Resolves the active project's team (if any) -- a network call, so run
    off the UI thread, same as every other TeamService lookup in this app."""

    done = Signal(object)  # str | None
    failed = Signal()

    def __init__(self, services: Services, project_uuid: str) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid

    def run(self) -> None:
        try:
            team = self._services.teams.find_team_for_project(self._project_uuid)
            self.done.emit(team.id if team else None)
        except Exception:
            self.failed.emit()


class _NotificationPollWorker(QObject):
    done = Signal(list, list)  # list[Notification], list[NotificationPreference] (this user's own)
    failed = Signal()

    def __init__(self, services: Services, team_id: str) -> None:
        super().__init__()
        self._services = services
        self._team_id = team_id

    def run(self) -> None:
        try:
            notifications = self._services.teams.list_notifications(self._team_id)
            all_prefs = self._services.teams.list_notification_preferences(self._team_id)
            user = self._services.auth.current_user()
            own_prefs = [p for p in all_prefs if user and p.user_id == user.id]
            self.done.emit(notifications, own_prefs)
        except Exception:
            self.failed.emit()


class _MarkReadWorker(QObject):
    done = Signal()
    failed = Signal()

    def __init__(self, services: Services, team_id: str, notification_id: str) -> None:
        super().__init__()
        self._services = services
        self._team_id = team_id
        self._notification_id = notification_id

    def run(self) -> None:
        try:
            self._services.teams.mark_notification_read(self._team_id, self._notification_id)
            self.done.emit()
        except Exception:
            self.failed.emit()


class NotificationDropdown(QFrame):
    """The popup inbox panel shown when the bell is clicked. A top-level
    popup widget (``Qt.WindowType.Popup``) so it closes itself on an
    outside click, same feel as a native dropdown menu."""

    notification_clicked = Signal(str)  # notification id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setObjectName("Panel")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        heading = QLabel("Notifications")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list)

        self._empty = QLabel("You're all caught up.")
        self._empty.setObjectName("Muted")
        layout.addWidget(self._empty)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

    def set_status(self, message: str) -> None:
        self._status.setText(message)

    def set_notifications(self, notifications: list[Notification]) -> None:
        self._list.clear()
        self._empty.setVisible(not notifications)
        self._list.setVisible(bool(notifications))
        for note in notifications:
            marker = "" if note.read_at else "● "  # bullet for unread
            text = f"{marker}{note.title}\n{note.body}\n{note.created_at}"
            item = QListWidgetItem(text)
            item.setData(_ITEM_ROLE, note.id)
            self._list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        note_id = item.data(_ITEM_ROLE)
        if note_id:
            self.notification_clicked.emit(note_id)


class NotificationBell(QFrame):
    """Bell button + unread badge, meant to sit in the top bar (see
    ``ui.top_bar.TopBar``). Owns the digest poller and the dropdown popup."""

    def __init__(self, services: Services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationBell")
        self._services = services
        self._team_id: str | None = None
        self._notifications: list[Notification] = []
        self._last_hourly_flush: datetime | None = None
        self._last_daily_flush: datetime | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._button = QPushButton("\U0001f514")  # bell emoji, kept minimal per spec
        self._button.setObjectName("Ghost")
        self._button.setToolTip("Notifications")
        self._button.clicked.connect(self._toggle_dropdown)
        layout.addWidget(self._button)

        self._dropdown = NotificationDropdown(self)
        self._dropdown.notification_clicked.connect(self._on_notification_clicked)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def stop(self) -> None:
        self._poll_timer.stop()

    def set_active_project(self, project: Project | None) -> None:
        """Resolve (async) the active project's team, if any, and poll it
        right away -- so switching projects updates the bell without
        waiting for the next timer tick."""
        self._team_id = None
        self._notifications = []
        self._update_badge()
        self._dropdown.set_notifications([])
        if project is None or not project.project_uuid or not self._services.auth.is_logged_in():
            self._dropdown.set_status(
                "Only available for a team-linked project you're signed in for."
            )
            return
        self._dropdown.set_status("Loading…")
        worker = _TeamLookupWorker(self._services, project.project_uuid)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_team_resolved)
        worker.failed.connect(self._on_team_lookup_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_team_resolved(self, team_id: str | None) -> None:
        self._team_id = team_id
        if team_id is None:
            self._dropdown.set_status("This project isn't linked to a team yet.")
            return
        self._poll()

    def _on_team_lookup_failed(self) -> None:
        self._dropdown.set_status("Couldn't reach the Spiced backend.")

    def _poll(self) -> None:
        if self._team_id is None:
            return
        worker = _NotificationPollWorker(self._services, self._team_id)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_polled)
        worker.failed.connect(self._on_poll_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_polled(
        self, notifications: list[Notification], preferences: list[NotificationPreference]
    ) -> None:
        unread = [n for n in notifications if n.read_at is None]
        now = datetime.now(UTC)
        result = bucket_by_cadence(
            unread,
            preferences,
            now=now,
            last_hourly_flush=self._last_hourly_flush,
            last_daily_flush=self._last_daily_flush,
        )
        if result.hourly_flushed:
            self._last_hourly_flush = now
        if result.daily_flushed:
            self._last_daily_flush = now

        # Already-read notifications are always shown for context; only
        # unread ones are subject to digest holding.
        read_notes = [n for n in notifications if n.read_at is not None]
        self._notifications = result.to_surface + read_notes
        self._update_badge(unread_count=len(result.to_surface))
        self._dropdown.set_status("")
        self._dropdown.set_notifications(self._notifications)

    def _on_poll_failed(self) -> None:
        self._dropdown.set_status("Couldn't reach the Spiced backend.")

    def _update_badge(self, unread_count: int = 0) -> None:
        self._button.setText(
            "\U0001f514" if not unread_count else f"\U0001f514 {unread_count}"
        )

    def _toggle_dropdown(self) -> None:
        if self._dropdown.isVisible():
            self._dropdown.hide()
            return
        point = self._button.mapToGlobal(self._button.rect().bottomLeft())
        self._dropdown.move(point)
        self._dropdown.show()

    def _on_notification_clicked(self, notification_id: str) -> None:
        if self._team_id is None:
            return
        worker = _MarkReadWorker(self._services, self._team_id, notification_id)
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._poll)
        worker.failed.connect(lambda: None)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()
