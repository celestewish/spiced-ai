"""Roadmap screen: public changelog + a suggestion board with upvoting.

Open Roadmap & Feedback Loop (Phase C, section 5, stretch). Viewing both
lists needs no login — they're read straight from the backend's public
``/roadmap`` endpoints. Submitting a suggestion or voting requires being
signed in, reusing ``AuthService``/``AuthDialog`` from Phase A exactly the
way Phase B's Team Mode toggle (``settings.py``) and Projects screen's team
section already do — there's no separate roadmap-specific account system.

Network calls here run synchronously on the UI thread, matching the existing
pattern in ``ProjectsScreen._refresh_team_section`` (which does the same for
team data) rather than introducing new QThread machinery for this screen.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.backend_client.api_client import (
    BackendAPIError,
    NotAuthenticatedError,
    RoadmapSuggestion,
)
from spiced.ui.auth_dialog import AuthDialog

_USER_ROLE = 0x0100


class RoadmapScreen(QWidget):
    def __init__(self, services: Services) -> None:
        super().__init__()
        self._services = services

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

        title = QLabel("Roadmap")
        title.setObjectName("ScreenTitle")
        layout.addWidget(title)

        intro = QLabel(
            "What's already shipped, and what's being considered next — the same list every "
            "Spiced user sees. Viewing needs no account. Submitting a suggestion or voting "
            "needs a free account, the same one used for Small-Team Mode."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._account_status = QLabel()
        self._account_status.setObjectName("Muted")
        self._account_status.setWordWrap(True)
        layout.addWidget(self._account_status)

        account_row = QHBoxLayout()
        self._signin_btn = QPushButton("Sign in / Sign up")
        self._signin_btn.setObjectName("Ghost")
        self._signin_btn.clicked.connect(self._on_sign_in)
        account_row.addWidget(self._signin_btn)
        account_row.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        account_row.addWidget(self._refresh_btn)
        layout.addLayout(account_row)

        self._build_changelog(layout)
        self._build_suggestions(layout)

        self.refresh()

    # --- Changelog (public) --------------------------------------------------

    def _build_changelog(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Changelog")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._changelog_list = QListWidget()
        self._changelog_list.setFixedHeight(220)
        layout.addWidget(self._changelog_list)

        self._changelog_empty = QLabel("No changelog entries yet.")
        self._changelog_empty.setObjectName("Muted")
        layout.addWidget(self._changelog_empty)

        self._changelog_error = QLabel("")
        self._changelog_error.setObjectName("Muted")
        self._changelog_error.setWordWrap(True)
        layout.addWidget(self._changelog_error)

    # --- Suggestion board (voting requires sign-in) ---------------------------

    def _build_suggestions(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Suggestions")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        row = QHBoxLayout()
        self._suggestion_input = QPlainTextEdit()
        self._suggestion_input.setPlaceholderText("A short suggestion title…")
        self._suggestion_input.setFixedHeight(50)
        row.addWidget(self._suggestion_input, 1)
        self._submit_btn = QPushButton("Submit suggestion")
        self._submit_btn.clicked.connect(self._on_submit_suggestion)
        row.addWidget(self._submit_btn)
        layout.addLayout(row)

        self._suggestions_list = QListWidget()
        self._suggestions_list.setFixedHeight(260)
        layout.addWidget(self._suggestions_list)

        self._suggestions_empty = QLabel("No suggestions yet — be the first.")
        self._suggestions_empty.setObjectName("Muted")
        layout.addWidget(self._suggestions_empty)

        self._suggestions_error = QLabel("")
        self._suggestions_error.setObjectName("Muted")
        self._suggestions_error.setWordWrap(True)
        layout.addWidget(self._suggestions_error)

    def _suggestion_widget(self, suggestion: RoadmapSuggestion) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(6, 4, 6, 4)

        text_col = QVBoxLayout()
        title_label = QLabel(suggestion.title)
        title_label.setWordWrap(True)
        text_col.addWidget(title_label)
        if suggestion.body:
            body_label = QLabel(suggestion.body)
            body_label.setObjectName("Muted")
            body_label.setWordWrap(True)
            text_col.addWidget(body_label)
        text_widget = QWidget()
        text_widget.setLayout(text_col)
        row.addWidget(text_widget, 1)

        vote_btn = QPushButton(
            f"▲ Unvote ({suggestion.vote_count})"
            if suggestion.voted_by_me
            else f"▲ Upvote ({suggestion.vote_count})"
        )
        vote_btn.clicked.connect(
            lambda _checked=False, s=suggestion: self._on_toggle_vote(s)
        )
        row.addWidget(vote_btn)
        return widget

    def _on_sign_in(self) -> None:
        if not self._services.auth.is_configured():
            QMessageBox.information(
                self,
                "Account not configured",
                "Set SUPABASE_URL and SUPABASE_ANON_KEY in your environment or a local "
                ".env file to sign in.",
            )
            return
        dialog = AuthDialog(self._services.auth, self)
        if dialog.exec() == AuthDialog.DialogCode.Accepted:
            self.refresh()

    def _on_submit_suggestion(self) -> None:
        if not self._services.auth.is_logged_in():
            QMessageBox.information(
                self, "Sign in required", "Sign in above to submit a suggestion."
            )
            return
        text = self._suggestion_input.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "Nothing to submit", "Write a suggestion first.")
            return
        title, _, body = text.partition("\n")
        try:
            self._services.roadmap.submit_suggestion(title.strip()[:300], body.strip())
        except (BackendAPIError, NotAuthenticatedError) as exc:
            QMessageBox.warning(self, "Couldn't submit suggestion", str(exc))
            return
        self._suggestion_input.clear()
        self._refresh_suggestions()

    def _on_toggle_vote(self, suggestion: RoadmapSuggestion) -> None:
        if not self._services.auth.is_logged_in():
            QMessageBox.information(self, "Sign in required", "Sign in above to vote.")
            return
        try:
            if suggestion.voted_by_me:
                self._services.roadmap.unvote(suggestion.id)
            else:
                self._services.roadmap.vote(suggestion.id)
        except (BackendAPIError, NotAuthenticatedError) as exc:
            QMessageBox.warning(self, "Couldn't record vote", str(exc))
            return
        self._refresh_suggestions()

    # --- Refresh ---------------------------------------------------------------

    def refresh(self) -> None:
        auth = self._services.auth
        logged_in = auth.is_logged_in()
        user = auth.current_user()
        self._account_status.setText(
            f"Signed in as {user.email}" if logged_in and user else "Not signed in."
        )
        self._signin_btn.setEnabled(not logged_in)
        self._refresh_changelog()
        self._refresh_suggestions()

    def _refresh_changelog(self) -> None:
        self._changelog_list.clear()
        try:
            entries = self._services.roadmap.list_changelog()
        except (BackendAPIError, NotAuthenticatedError) as exc:
            self._changelog_error.setText(f"Couldn't reach the roadmap backend: {exc}")
            self._changelog_empty.setVisible(False)
            self._changelog_list.setVisible(False)
            return
        self._changelog_error.setText("")
        self._changelog_empty.setVisible(not entries)
        self._changelog_list.setVisible(bool(entries))
        for entry in entries:
            label = f"[{entry.version_or_phase_label}] {entry.title}\n{entry.body}"
            item = QListWidgetItem(label)
            self._changelog_list.addItem(item)

    def _refresh_suggestions(self) -> None:
        self._suggestions_list.clear()
        try:
            suggestions = self._services.roadmap.list_suggestions()
        except (BackendAPIError, NotAuthenticatedError) as exc:
            self._suggestions_error.setText(f"Couldn't reach the roadmap backend: {exc}")
            self._suggestions_empty.setVisible(False)
            self._suggestions_list.setVisible(False)
            return
        self._suggestions_error.setText("")
        self._suggestions_empty.setVisible(not suggestions)
        self._suggestions_list.setVisible(bool(suggestions))
        for suggestion in suggestions:
            item = QListWidgetItem()
            self._suggestions_list.addItem(item)
            widget = self._suggestion_widget(suggestion)
            item.setSizeHint(widget.sizeHint())
            self._suggestions_list.setItemWidget(item, widget)
