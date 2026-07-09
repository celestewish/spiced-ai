"""Project Dashboard: a calm, local-first overview of the active project.

Everything on this screen is computed deterministically from data Spiced already
stored — no AI call and no network. The build-readiness label is a planning aid,
never a claim the game is ready to ship; the developer stays in control.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.dashboard import DashboardSummary, ModuleCard, NextAction


class DashboardScreen(QWidget):
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
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(28, 28, 28, 28)
        self._layout.setSpacing(14)

        title = QLabel("Project Dashboard")
        title.setObjectName("ScreenTitle")
        self._layout.addWidget(title)

        self._body = QVBoxLayout()
        self._body.setSpacing(14)
        self._layout.addLayout(self._body)
        self._layout.addStretch(1)

        self.refresh()

    # --- Rendering ---------------------------------------------------------

    def refresh(self) -> None:
        _clear_layout(self._body)
        summary = self._services.dashboard.summarize(self._services.active_project())
        if summary is None:
            self._body.addWidget(
                _muted(
                    "No active project selected. Create or choose one on the Projects screen "
                    "to see its dashboard."
                )
            )
            return

        self._body.addWidget(self._overview_card(summary))
        self._body.addWidget(self._readiness_card(summary))

        cards_row = QHBoxLayout()
        cards_row.setSpacing(14)
        for card in (summary.debugging, summary.testing, summary.feedback):
            cards_row.addWidget(self._module_card(card), 1)
        wrapper = QWidget()
        wrapper.setLayout(cards_row)
        self._body.addWidget(wrapper)

        self._body.addWidget(self._actions_card(summary))
        if summary.missing_data:
            self._body.addWidget(self._reminders_card(summary))
        self._body.addWidget(self._summary_tools(summary))

    def _overview_card(self, summary: DashboardSummary) -> QFrame:
        card = _card()
        layout = card.layout()
        heading = QLabel(summary.project_name)
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        layout.addWidget(_muted(f"Engine: {summary.engine}"))
        layout.addWidget(_muted(f"Unity folder: {summary.unity_status}"))
        if summary.project_path:
            path = _muted(f"Path: {summary.project_path}")
            path.setWordWrap(True)
            layout.addWidget(path)
        return card

    def _readiness_card(self, summary: DashboardSummary) -> QFrame:
        card = _card(object_name="ReadinessCard")
        layout = card.layout()
        heading = QLabel("Build readiness")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        label = QLabel(summary.readiness.label)
        label.setObjectName("ReadinessLabel")
        layout.addWidget(label)
        layout.addWidget(_muted("Why:"))
        for item in summary.readiness.evidence:
            layout.addWidget(_bullet(item))
        for caveat in summary.readiness.caveats:
            note = _muted(f"Note: {caveat}")
            note.setWordWrap(True)
            layout.addWidget(note)
        return card

    def _module_card(self, card_data: ModuleCard) -> QFrame:
        card = _card()
        layout = card.layout()
        heading = QLabel(card_data.name)
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        headline = _muted(card_data.headline)
        headline.setWordWrap(True)
        layout.addWidget(headline)
        for line in card_data.lines:
            layout.addWidget(_bullet(line))
        layout.addStretch(1)
        return card

    def _actions_card(self, summary: DashboardSummary) -> QFrame:
        card = _card()
        layout = card.layout()
        heading = QLabel("Recommended next actions")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        if not summary.next_actions:
            layout.addWidget(
                _muted("Nothing urgent yet. Capture more data to get recommendations.")
            )
            return card
        for action in summary.next_actions:
            layout.addWidget(_action_row(action))
        layout.addWidget(
            _muted("These are suggestions to help you plan — you decide what to work on.")
        )
        return card

    def _reminders_card(self, summary: DashboardSummary) -> QFrame:
        card = _card()
        layout = card.layout()
        heading = QLabel("Setup reminders")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        for item in summary.missing_data:
            layout.addWidget(_bullet(item))
        return card

    def _summary_tools(self, summary: DashboardSummary) -> QFrame:
        card = _card()
        layout = card.layout()
        heading = QLabel("Project health summary")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        layout.addWidget(
            _muted(
                "Generate a local, Markdown-friendly summary for your planning or devlog notes. "
                "It contains only summaries and counts — never full logs, feedback, or code."
            )
        )
        row = QHBoxLayout()
        generate_btn = QPushButton("Generate summary")
        generate_btn.clicked.connect(lambda: self._on_generate(summary))
        row.addWidget(generate_btn)
        self._copy_btn = QPushButton("Copy to clipboard")
        self._copy_btn.setObjectName("Ghost")
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._on_copy)
        row.addWidget(self._copy_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self._summary_view = QLabel("")
        self._summary_view.setObjectName("Muted")
        self._summary_view.setWordWrap(True)
        self._summary_view.setTextInteractionFlags(
            self._summary_view.textInteractionFlags().TextSelectableByMouse
        )
        layout.addWidget(self._summary_view)
        self._summary_text = ""
        return card

    # --- Handlers ----------------------------------------------------------

    def _on_generate(self, summary: DashboardSummary) -> None:
        self._summary_text = summary.to_markdown()
        self._summary_view.setText(self._summary_text)
        self._copy_btn.setEnabled(True)

    def _on_copy(self) -> None:
        if self._summary_text:
            QApplication.clipboard().setText(self._summary_text)
            self._copy_btn.setText("Copied ✓")


# --- Small widget helpers --------------------------------------------------


def _card(object_name: str = "Card") -> QFrame:
    frame = QFrame()
    frame.setObjectName(object_name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(6)
    return frame


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    return label


def _bullet(text: str) -> QLabel:
    label = QLabel(f"•  {text}")
    label.setWordWrap(True)
    return label


def _action_row(action: NextAction) -> QLabel:
    label = QLabel(
        f"[{action.priority}] {action.title}\n"
        f"      {action.source_module} · {action.reason}"
    )
    label.setWordWrap(True)
    return label


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()
        else:
            child = item.layout()
            if child is not None:
                _clear_layout(child)
