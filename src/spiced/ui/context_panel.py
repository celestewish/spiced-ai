"""Right-hand project context panel."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from spiced.app.services import Services


class ContextPanel(QFrame):
    """Shows lightweight, always-visible context: project count and usage."""

    def __init__(self, services: Services) -> None:
        super().__init__()
        self.setObjectName("ContextPanel")
        self._services = services

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        heading = QLabel("Project context")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        self._projects_label = QLabel()
        self._projects_label.setWordWrap(True)
        layout.addWidget(self._projects_label)

        layout.addSpacing(10)
        usage_title = QLabel("Usage")
        usage_title.setObjectName("SectionTitle")
        layout.addWidget(usage_title)

        self._usage_pill = QLabel()
        self._usage_pill.setObjectName("UsagePill")
        self._usage_pill.setWordWrap(True)
        layout.addWidget(self._usage_pill)

        layout.addStretch(1)

        footer = QLabel("Spiced keeps everything local. You decide what to share.")
        footer.setObjectName("Muted")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self.refresh()

    def refresh(self) -> None:
        count = len(self._services.projects.list_projects())
        word = "project" if count == 1 else "projects"
        self._projects_label.setText(f"{count} {word} saved locally.")
        self._usage_pill.setText(self._services.usage.status().summary())
