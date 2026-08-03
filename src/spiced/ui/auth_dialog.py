"""Sign up / log in dialog for Small-Team Mode.

Only ever shown when a developer explicitly tries to enable Team Mode or
link a project to a team from the Projects screen — Solo-Dev Mode never
prompts for an account.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from spiced.core.auth_service import AuthService


class AuthDialog(QDialog):
    def __init__(self, auth: AuthService, parent=None) -> None:
        super().__init__(parent)
        self._auth = auth
        self.setWindowTitle("Sign in to Spiced Team Mode")

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Team Mode needs an account so teammates can share test cases, debug "
            "sessions, and feedback for a linked project. Solo projects are never "
            "affected."
        )
        intro.setObjectName("Muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        self._email_input = QLineEdit()
        self._email_input.setPlaceholderText("you@example.com")
        form.addRow("Email", self._email_input)

        self._password_input = QLineEdit()
        self._password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password", self._password_input)
        layout.addLayout(form)

        self._error_label = QLabel("")
        self._error_label.setObjectName("Muted")
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        buttons = QDialogButtonBox()
        self._login_btn = buttons.addButton("Log in", QDialogButtonBox.ButtonRole.AcceptRole)
        self._signup_btn = buttons.addButton("Sign up", QDialogButtonBox.ButtonRole.ActionRole)
        self._cancel_btn = buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._login_btn.clicked.connect(self._on_login)
        self._signup_btn.clicked.connect(self._on_signup)
        self._cancel_btn.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.logged_in_email: str | None = None

    def _credentials(self) -> tuple[str, str] | None:
        email = self._email_input.text().strip()
        password = self._password_input.text()
        if not email or not password:
            self._error_label.setText("Enter both an email and a password.")
            return None
        return email, password

    def _on_login(self) -> None:
        credentials = self._credentials()
        if credentials is None:
            return
        email, password = credentials
        try:
            user = self._auth.log_in(email, password)
        except Exception as exc:
            self._error_label.setText(str(exc))
            return
        self.logged_in_email = user.email
        self.accept()

    def _on_signup(self) -> None:
        credentials = self._credentials()
        if credentials is None:
            return
        email, password = credentials
        try:
            user = self._auth.sign_up(email, password)
        except Exception as exc:
            self._error_label.setText(str(exc))
            return
        self.logged_in_email = user.email
        self.accept()
