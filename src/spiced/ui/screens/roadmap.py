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

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.backend_client.api_client import (
    BackendAPIError,
    ChangelogEntry,
    NotAuthenticatedError,
    RoadmapSuggestion,
)
from spiced.ui.auth_dialog import AuthDialog
from spiced.ui.widgets.pill_button import PillButton


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


def _hairline() -> QFrame:
    line = QFrame()
    line.setObjectName("Hairline")
    line.setFixedHeight(1)
    return line


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
        content.setObjectName("ScrollContent")
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(14)

        title_row = QHBoxLayout()
        title = QLabel("Roadmap")
        title.setObjectName("ScreenTitle")
        title_row.addWidget(title)
        self._account_status = QLabel()
        self._account_status.setObjectName("UsagePill")
        title_row.addWidget(self._account_status)
        title_row.addStretch(1)
        self._refresh_btn = PillButton("Refresh", ghost=True)
        self._refresh_btn.clicked.connect(self.refresh)
        title_row.addWidget(self._refresh_btn)
        self._signin_btn = PillButton("Sign in / Sign up")
        self._signin_btn.clicked.connect(self._on_sign_in)
        title_row.addWidget(self._signin_btn)
        layout.addLayout(title_row)

        intro = QLabel(
            "What's already shipped, and what's being considered next — the same list every "
            "Spiced user sees. Viewing needs no account. Submitting a suggestion or voting "
            "needs a free account, the same one used for Small-Team Mode."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        changelog_card = _card()
        self._build_changelog(changelog_card.layout())
        layout.addWidget(changelog_card)

        suggestions_card = _card()
        self._build_suggestions(suggestions_card.layout())
        layout.addWidget(suggestions_card)

        self.refresh()

    # --- Changelog (public) --------------------------------------------------

    def _build_changelog(self, layout: QVBoxLayout) -> None:
        heading = QLabel("Changelog")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)

        changelog_scroll = QScrollArea()
        changelog_scroll.setWidgetResizable(True)
        changelog_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        changelog_scroll.setFixedHeight(240)
        changelog_content = QWidget()
        self._changelog_layout = QVBoxLayout(changelog_content)
        self._changelog_layout.setContentsMargins(0, 0, 0, 0)
        self._changelog_layout.setSpacing(4)
        changelog_scroll.setWidget(changelog_content)
        layout.addWidget(changelog_scroll)

        self._changelog_empty = QLabel("No changelog entries yet.")
        self._changelog_empty.setObjectName("Muted")
        layout.addWidget(self._changelog_empty)

        self._changelog_error = QLabel("")
        self._changelog_error.setObjectName("Muted")
        self._changelog_error.setWordWrap(True)
        layout.addWidget(self._changelog_error)

    def _changelog_row(self, entry: ChangelogEntry) -> QWidget:
        row = QWidget()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 8, 0, 8)
        row_layout.setSpacing(4)
        top = QHBoxLayout()
        chip = QLabel(entry.version_or_phase_label)
        chip.setObjectName("UsagePill")
        top.addWidget(chip, 0)
        title_label = QLabel(entry.title)
        title_label.setStyleSheet("font-weight: 700;")
        title_label.setWordWrap(True)
        top.addWidget(title_label, 1)
        row_layout.addLayout(top)
        if entry.body:
            body_label = QLabel(entry.body)
            body_label.setObjectName("Muted")
            body_label.setWordWrap(True)
            row_layout.addWidget(body_label)
        return row

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
        self._submit_btn = PillButton("Submit suggestion")
        self._submit_btn.clicked.connect(self._on_submit_suggestion)
        row.addWidget(self._submit_btn)
        layout.addLayout(row)

        suggestions_scroll = QScrollArea()
        suggestions_scroll.setWidgetResizable(True)
        suggestions_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        suggestions_scroll.setFixedHeight(280)
        suggestions_content = QWidget()
        self._suggestions_layout = QVBoxLayout(suggestions_content)
        self._suggestions_layout.setContentsMargins(0, 0, 0, 0)
        self._suggestions_layout.setSpacing(4)
        suggestions_scroll.setWidget(suggestions_content)
        layout.addWidget(suggestions_scroll)

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
        row.setContentsMargins(0, 8, 0, 8)

        text_col = QVBoxLayout()
        title_label = QLabel(suggestion.title)
        title_label.setStyleSheet("font-weight: 700;")
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

        vote_btn = PillButton(
            f"▲ Unvote ({suggestion.vote_count})"
            if suggestion.voted_by_me
            else f"▲ Upvote ({suggestion.vote_count})"
        )
        vote_btn.setObjectName("VoteButton")
        vote_btn.setProperty("voted", "true" if suggestion.voted_by_me else "false")
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
            f"Signed in as {user.email}" if logged_in and user else "Not signed in"
        )
        self._signin_btn.setEnabled(not logged_in)
        self._refresh_changelog()
        self._refresh_suggestions()

    def _refresh_changelog(self) -> None:
        _clear_layout(self._changelog_layout)
        try:
            entries = self._services.roadmap.list_changelog()
            self._changelog_empty.setVisible(not entries)
            for index, entry in enumerate(entries):
                if index > 0:
                    self._changelog_layout.addWidget(_hairline())
                self._changelog_layout.addWidget(self._changelog_row(entry))
        except (BackendAPIError, NotAuthenticatedError) as exc:
            self._changelog_error.setText(f"Couldn't reach the roadmap backend: {exc}")
            self._changelog_empty.setVisible(False)
            return
        except Exception as exc:  # surfaced calmly to the user, never a crash
            self._changelog_error.setText(f"Couldn't load the changelog: {exc}")
            self._changelog_empty.setVisible(False)
            return
        self._changelog_error.setText("")

    def _refresh_suggestions(self) -> None:
        _clear_layout(self._suggestions_layout)
        try:
            suggestions = self._services.roadmap.list_suggestions()
            self._suggestions_empty.setVisible(not suggestions)
            for index, suggestion in enumerate(suggestions):
                if index > 0:
                    self._suggestions_layout.addWidget(_hairline())
                self._suggestions_layout.addWidget(self._suggestion_widget(suggestion))
        except (BackendAPIError, NotAuthenticatedError) as exc:
            self._suggestions_error.setText(f"Couldn't reach the roadmap backend: {exc}")
            self._suggestions_empty.setVisible(False)
            return
        except Exception as exc:  # surfaced calmly to the user, never a crash
            self._suggestions_error.setText(f"Couldn't load suggestions: {exc}")
            self._suggestions_empty.setVisible(False)
            return
        self._suggestions_error.setText("")


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
