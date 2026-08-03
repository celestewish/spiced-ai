"""A compact, always-visible Build Health Score badge with an expander.

Reuses ``core.dashboard.ReadinessAssessment`` as-is — it already returns a
non-gamified enum label plus its evidence/caveats, matching the spec's "not
hidden behind a score" requirement. This widget is a minimal, deliberately
small building block (label + "Why?" expander) rather than a rich card, so it
fits as a persistent header on any screen; the Dashboard screen keeps its own
richer readiness card. It shares its "label + Why? ▸/▾ toggle" behavior with
Phase C's ``SourceLinkExpander`` via ``_ExpanderMixin`` (see
``ui/widgets/source_link.py``) rather than duplicating that toggle logic —
the two widgets stayed separate classes since a badge's "always has a label,
starts collapsed but keeps its state across refreshes" shape differs from a
source link's "hidden entirely until there's something to show" shape.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from spiced.core.dashboard import ReadinessAssessment
from spiced.ui.widgets.source_link import _ExpanderMixin


class ReadinessBadge(_ExpanderMixin, QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ReadinessBadge")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        self._label = QLabel("Build health: —")
        self._label.setObjectName("ReadinessLabel")
        top.addWidget(self._label)
        top.addStretch(1)
        toggle = QPushButton("Why? ▸")
        toggle.setObjectName("Ghost")
        top.addWidget(toggle)
        layout.addLayout(top)

        body = QLabel("")
        body.setObjectName("Muted")
        body.setWordWrap(True)
        layout.addWidget(body)

        self._init_expander(toggle, body, "Why? ▸", "Why? ▾")

    def set_readiness(
        self, readiness: ReadinessAssessment | None, *, team_linked: bool = False
    ) -> None:
        if readiness is None:
            self._label.setText("Build health: no active project")
            self._body.setText("Select an active project on the Projects screen.")
            return

        self._label.setText(f"Build health: {readiness.label}")
        lines = ["Why:"]
        lines += [f"• {item}" for item in readiness.evidence] or ["• (no evidence yet)"]
        lines += [f"Note: {c}" for c in readiness.caveats]
        if team_linked:
            lines.append(
                "Note: this project is team-linked — session summaries are tracked "
                "centrally, but a full team-wide rollup across everyone's machines isn't "
                "built yet; this label still reflects only your local data."
            )
        self._body.setText("\n".join(lines))
