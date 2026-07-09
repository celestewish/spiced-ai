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

        self._active_label = QLabel()
        self._active_label.setWordWrap(True)
        layout.addWidget(self._active_label)

        self._unity_label = QLabel()
        self._unity_label.setObjectName("Muted")
        self._unity_label.setWordWrap(True)
        layout.addWidget(self._unity_label)

        self._projects_label = QLabel()
        self._projects_label.setObjectName("Muted")
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
        active = self._services.active_project()
        if active is None:
            self._active_label.setText("No active project selected.")
            self._unity_label.setText("Choose one on the Projects screen to add Unity context.")
        else:
            self._active_label.setText(f"Active: {active.name}")
            if active.is_valid_unity:
                version = active.engine_metadata.get("unity_version")
                suffix = f" (Unity {version})" if version else ""
                self._unity_label.setText(f"Unity folder connected{suffix}.")
            elif active.path:
                self._unity_label.setText("Folder set, but not recognized as a Unity project.")
            else:
                self._unity_label.setText("No Unity folder connected yet.")

        count = len(self._services.projects.list_projects())
        word = "project" if count == 1 else "projects"
        self._projects_label.setText(f"{count} {word} saved locally.")
        self._usage_pill.setText(self._services.usage.status().summary())
