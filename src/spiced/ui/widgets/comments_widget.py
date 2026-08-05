"""Comment Threads on Assets/Builds: a reusable "Comments" widget (Phase J).

Attaches to any subject that has one of the fixed ``subject_type``s the
backend accepts ('task' | 'known_issue' | 'build' | 'session_summary') --
this phase wires it into a ``TeamTask`` card (see ``ui.screens.team``) and a
Known Issue entry (``ui.screens.testing``) as the two concrete places per
spec. Only shown/usable for team-linked projects, since comments require a
``team_id`` (``TeamService.comments_for_project_subject`` returns ``[]`` for
an unlinked project, and this widget hides itself entirely in that case
rather than showing an unusable "0 comments" panel).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from spiced.app.services import Services
from spiced.backend_client.api_client import Comment
from spiced.ui.thread_utils import launch_worker


class _CommentsLoadWorker(QObject):
    done = Signal(list)  # list[Comment]
    failed = Signal(str)

    def __init__(
        self, services: Services, project_uuid: str, subject_type: str, subject_id: str
    ) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid
        self._subject_type = subject_type
        self._subject_id = subject_id

    def run(self) -> None:
        try:
            comments = self._services.teams.comments_for_project_subject(
                self._project_uuid, self._subject_type, self._subject_id
            )
            self.done.emit(comments)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't load comments: {exc}")


class _CommentsPostWorker(QObject):
    done = Signal(object)  # Comment | None
    failed = Signal(str)

    def __init__(
        self, services: Services, project_uuid: str, subject_type: str, subject_id: str, body: str
    ) -> None:
        super().__init__()
        self._services = services
        self._project_uuid = project_uuid
        self._subject_type = subject_type
        self._subject_id = subject_id
        self._body = body

    def run(self) -> None:
        try:
            comment = self._services.teams.add_comment_for_project(
                self._project_uuid, self._subject_type, self._subject_id, self._body
            )
            self.done.emit(comment)
        except Exception as exc:  # surfaced calmly to the user
            self.failed.emit(f"Couldn't post comment: {exc}")


class CommentsWidget(QFrame):
    """A comment list + add-comment box, attachable to any team subject."""

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.setObjectName("CommentsWidget")
        self._services = services
        self._project_uuid: str | None = None
        self._subject_type: str | None = None
        self._subject_id: str | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)

        heading = QLabel("Comments")
        heading.setObjectName("Muted")
        layout.addWidget(heading)

        self._list = QTextEdit()
        self._list.setReadOnly(True)
        self._list.setFixedHeight(90)
        self._list.setPlaceholderText("No comments yet.")
        layout.addWidget(self._list)

        row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Add a comment…")
        self._input.returnPressed.connect(self._on_post)
        row.addWidget(self._input, 1)
        self._post_btn = QPushButton("Post")
        self._post_btn.clicked.connect(self._on_post)
        row.addWidget(self._post_btn)
        layout.addLayout(row)

        self._status = QLabel("")
        self._status.setObjectName("Muted")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self.setVisible(False)

    def set_subject(self, project_uuid: str | None, subject_type: str, subject_id: str) -> None:
        """Point this widget at one subject and (re)load its comments.

        Pass ``project_uuid=None`` for a solo/unlinked project -- the widget
        hides itself entirely rather than showing an unusable panel.
        """
        self._project_uuid = project_uuid
        self._subject_type = subject_type
        self._subject_id = subject_id
        if not project_uuid:
            self.setVisible(False)
            return
        self.setVisible(True)
        self.refresh()

    def refresh(self) -> None:
        if not self._project_uuid or not self._subject_type or not self._subject_id:
            return
        self._list.setPlainText("Loading comments…")
        worker = _CommentsLoadWorker(
            self._services, self._project_uuid, self._subject_type, self._subject_id
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_loaded)
        worker.failed.connect(self._on_load_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_loaded(self, comments: list[Comment]) -> None:
        if not comments:
            self._list.setPlainText("No comments yet.")
            return
        lines = [f"[{c.created_at}] {c.author_user_id}: {c.body}" for c in comments]
        self._list.setPlainText("\n".join(lines))

    def _on_load_failed(self, message: str) -> None:
        self._list.setPlainText(message)

    def _on_post(self) -> None:
        text = self._input.text().strip()
        if not text or not self._project_uuid:
            return
        self._post_btn.setEnabled(False)
        self._status.setText("Posting…")

        worker = _CommentsPostWorker(
            self._services, self._project_uuid, self._subject_type, self._subject_id, text
        )
        thread = launch_worker(self, worker)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_posted)
        worker.failed.connect(self._on_post_failed)
        worker.done.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.start()

    def _on_posted(self, _comment: Comment | None) -> None:
        self._post_btn.setEnabled(True)
        self._status.setText("")
        self._input.clear()
        self.refresh()

    def _on_post_failed(self, message: str) -> None:
        self._post_btn.setEnabled(True)
        self._status.setText(message)
