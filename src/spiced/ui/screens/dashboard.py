"""Project Dashboard: a calm, local-first overview of the active project.

Everything on this screen is computed deterministically from data Spiced already
stored — no AI call and no network. The build-readiness label is a planning aid,
never a claim the game is ready to ship; the developer stays in control.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from spiced.app.services import Services
from spiced.core.dashboard import (
    DEMO_CANDIDATE,
    NEEDS_REVIEW,
    NOT_ENOUGH_DATA,
    STABILIZING,
    DashboardSummary,
    ModuleCard,
    NextAction,
)
from spiced.core.widget_preferences import (
    DASHBOARD_WIDGETS,
    load_preferences,
    merge_and_dump,
    ordered_visible_ids,
)
from spiced.ui.widget_customize_dialog import WidgetCustomizeDialog
from spiced.ui.widgets.health_gauge import HealthGauge
from spiced.ui.widgets.pill_button import PillButton

# Frutiger Aqua theme (ui.theme): same label -> state mapping as
# ui.widgets.readiness_badge.ReadinessBadge, kept in sync so the Dashboard's
# own readiness card and Testing's Build Health Score badge color-code
# identically for the same label.
_READINESS_STATE_BY_LABEL = {
    NOT_ENOUGH_DATA: "neutral",
    NEEDS_REVIEW: "bad",
    STABILIZING: "warn",
    DEMO_CANDIDATE: "good",
}


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
        content.setObjectName("ScrollContent")
        scroll.setWidget(content)
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(28, 28, 28, 28)
        self._layout.setSpacing(14)

        title_row = QHBoxLayout()
        self._title = QLabel("Welcome back \U0001f44b")
        self._title.setObjectName("ScreenTitle")
        title_row.addWidget(self._title)
        title_row.addStretch(1)
        # Customizable Dashboard Widgets (Phase L, Phase 2 tier -- scoped
        # down to show/hide + reorder, see core.widget_preferences): applies
        # to the Debugging/Testing/Feedback module-card row below.
        self._customize_btn = PillButton("Customize modules", ghost=True)
        self._customize_btn.clicked.connect(self._on_customize_modules)
        title_row.addWidget(self._customize_btn)
        self._layout.addLayout(title_row)

        self._body = QVBoxLayout()
        self._body.setSpacing(14)
        self._layout.addLayout(self._body)
        self._layout.addStretch(1)

        self.refresh()

    # --- Rendering ---------------------------------------------------------

    def refresh(self) -> None:
        _clear_layout(self._body)
        self._title.setText(f"Welcome back, {self._services.display_name()} \U0001f44b")

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
        stat_row = _row(
            self._stat_card("Tests Passing", _pct_text(summary.tests_passing_pct)),
            self._stat_card("Open Bugs", str(summary.open_bugs)),
            self._stat_card("Feedback Themes", str(summary.feedback_theme_count)),
        )
        self._body.addWidget(stat_row)
        self._body.addWidget(self._actions_card(summary))
        self._body.addWidget(_row(self._health_card(summary), self._session_card(summary)))
        self._body.addWidget(self._activity_card(summary))

        cards_by_id = {
            "module_debugging": summary.debugging,
            "module_testing": summary.testing,
            "module_feedback": summary.feedback,
        }
        preferences = load_preferences(self._services.widget_preferences_json(), DASHBOARD_WIDGETS)
        visible_ids = ordered_visible_ids(preferences, DASHBOARD_WIDGETS)
        if visible_ids:
            cards_row = QHBoxLayout()
            cards_row.setSpacing(14)
            for widget_id in visible_ids:
                card_data = cards_by_id.get(widget_id)
                if card_data is not None:
                    cards_row.addWidget(self._module_card(card_data), 1)
            wrapper = QWidget()
            wrapper.setLayout(cards_row)
            self._body.addWidget(wrapper)

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

    def _stat_card(self, label: str, value: str) -> QFrame:
        card = _card()
        layout = card.layout()
        stat_label = QLabel(label)
        stat_label.setObjectName("StatLabel")
        layout.addWidget(stat_label)
        stat_value = QLabel(value)
        stat_value.setObjectName("StatValue")
        layout.addWidget(stat_value)
        return card

    def _health_card(self, summary: DashboardSummary) -> QFrame:
        """Build Health: a gauge (see ui.widgets.health_gauge -- its fill is
        a coarse, non-gamified visual, not a precision score) next to the
        readiness label, with the full evidence/caveats kept underneath --
        Spiced's "every assessment lists why" principle stays intact, the
        gauge is additive, not a replacement for the explanation."""
        card = _card(object_name="ReadinessCard")
        layout = card.layout()

        top = QHBoxLayout()
        top.setSpacing(16)
        gauge = HealthGauge(96)
        gauge.set_value(summary.health_fill_pct, summary.readiness.label)
        top.addWidget(gauge, 0)

        text_col = QVBoxLayout()
        heading = QLabel("Build Health")
        heading.setObjectName("SectionTitle")
        text_col.addWidget(heading)
        label = QLabel(summary.readiness.label)
        label.setObjectName("ReadinessLabel")
        state = _READINESS_STATE_BY_LABEL.get(summary.readiness.label, "neutral")
        label.setProperty("state", state)
        text_col.addWidget(label)
        if summary.readiness.evidence:
            first = _muted(summary.readiness.evidence[0])
            first.setWordWrap(True)
            text_col.addWidget(first)
        text_col.addStretch(1)
        top.addLayout(text_col, 1)
        layout.addLayout(top)

        if len(summary.readiness.evidence) > 1:
            layout.addWidget(_muted("Why:"))
            for item in summary.readiness.evidence[1:]:
                layout.addWidget(_bullet(item))
        for caveat in summary.readiness.caveats:
            note = _muted(f"Note: {caveat}")
            note.setWordWrap(True)
            layout.addWidget(note)
        return card

    def _session_card(self, summary: DashboardSummary) -> QFrame:
        card = _card()
        layout = card.layout()
        heading = QLabel("Session Summary")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        if not summary.session_recap:
            layout.addWidget(
                _muted(
                    "No sessions summarized yet. Use “Summarize / end session” in the "
                    "panel on the right to capture one."
                )
            )
            layout.addStretch(1)
            return card
        for line in summary.session_recap:
            recap_line = QLabel(f"✓ {line}")
            recap_line.setWordWrap(True)
            layout.addWidget(recap_line)
        layout.addStretch(1)
        return card

    def _activity_card(self, summary: DashboardSummary) -> QFrame:
        card = _card()
        layout = card.layout()
        heading = QLabel("Recent Activity")
        heading.setObjectName("CardTitle")
        layout.addWidget(heading)
        if not summary.recent_activity:
            layout.addWidget(_muted("Nothing recorded yet."))
            return card
        for index, item in enumerate(summary.recent_activity):
            if index > 0:
                layout.addWidget(_hairline())
            row = QHBoxLayout()
            text = QLabel(f"{item.label}  ·  {item.source_module}")
            text.setWordWrap(True)
            row.addWidget(text, 1)
            stamp = _muted(item.timestamp)
            row.addWidget(stamp, 0)
            layout.addLayout(row)
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
        for index, action in enumerate(summary.next_actions):
            if index > 0:
                layout.addWidget(_hairline())
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
        generate_btn = PillButton("Generate summary")
        generate_btn.clicked.connect(lambda: self._on_generate(summary))
        row.addWidget(generate_btn)
        self._copy_btn = PillButton("Copy to clipboard", ghost=True)
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

    def _on_customize_modules(self) -> None:
        preferences = load_preferences(self._services.widget_preferences_json(), DASHBOARD_WIDGETS)
        dialog = WidgetCustomizeDialog(
            DASHBOARD_WIDGETS, preferences, parent=self, title="Customize dashboard modules"
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.result_preferences()
            new_json = merge_and_dump(self._services.widget_preferences_json(), updated)
            self._services.set_widget_preferences_json(new_json)
            self.refresh()

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
    # Real drop-shadow elevation -- Qt QSS has no box-shadow (see ui.theme's
    # module docstring). Applied here rather than once via findChildren in
    # ui.main_window, since these frames are rebuilt fresh on every refresh().
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(20)
    shadow.setOffset(0, 5)
    shadow.setColor(QColor(20, 10, 40, 80))
    frame.setGraphicsEffect(shadow)
    return frame


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def _bullet(text: str) -> QLabel:
    label = QLabel(f"•  {text}")
    label.setWordWrap(True)
    return label


def _action_row(action: NextAction) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(12)

    pill = QLabel(action.priority.upper())
    pill.setObjectName("PriorityPill")
    pill.setProperty("priority", action.priority)
    pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(pill, 0, Qt.AlignmentFlag.AlignTop)

    text_col = QVBoxLayout()
    text_col.setSpacing(2)
    title = QLabel(action.title)
    title.setWordWrap(True)
    title.setStyleSheet("font-weight: 700;")
    text_col.addWidget(title)
    meta = _muted(f"{action.source_module} · {action.reason}")
    text_col.addWidget(meta)
    layout.addLayout(text_col, 1)
    return row


def _row(*widgets: QWidget) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(14)
    for widget in widgets:
        layout.addWidget(widget, 1)
    return wrapper


def _hairline() -> QFrame:
    line = QFrame()
    line.setObjectName("Hairline")
    line.setFixedHeight(1)
    return line


def _pct_text(pct: int | None) -> str:
    return "—" if pct is None else f"{pct}%"


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
