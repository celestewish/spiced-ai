"""Transparent AI Reasoning: a reusable "Why am I seeing this?" expander.

Every AI-produced result in Spiced already has captured, on-disk provenance
for why it looks the way it does: a raw excerpt that was sent to the
provider, a matched known-issue's ``RegressionMatch.note`` (see
``core/regression.py``), or a source label like an imported filename. This
widget is the one place that provenance gets surfaced back to the developer
— a short description plus a "Why am I seeing this? ▸/▾" toggle that reveals
the underlying excerpt on click. It never invents anything; callers pass in
data the corresponding ``*_reports``/``*_sessions`` table (or
``RegressionMatch``) already stores.

``ReadinessBadge`` (Phase B) used this same "label + Why? ▸/▾ toggle" shape
before this widget existed, and its docstring anticipated unifying the two.
``_ExpanderMixin`` below is the small shared base both now build on, so the
toggle behavior lives in exactly one place — ``SourceLinkExpander`` itself
stays specific to "one description + one excerpt", which is a different
enough shape (and different enough default-visibility rules — hidden
entirely when there's nothing to show) that fully merging the two widgets
would have made both harder to read for no real gain.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from spiced.ui.widgets.pill_button import PillButton


class _ExpanderMixin:
    """Shared "label + Why? ▸/▾ toggle + hidden body" click behavior.

    Subclasses build their own header/body widgets in ``__init__`` and then
    call ``_init_expander(...)`` once both exist. Pure-Python mixin (no Qt
    base class of its own) so it can sit alongside any ``QWidget`` subclass.
    """

    def _init_expander(
        self, toggle: QPushButton, body: QLabel, closed_text: str, open_text: str
    ) -> None:
        self._toggle = toggle
        self._body = body
        self._closed_text = closed_text
        self._open_text = open_text
        self._toggle.setText(closed_text)
        self._toggle.clicked.connect(self._on_toggle_expander)
        self._body.setVisible(False)

    def _on_toggle_expander(self) -> None:
        expanded = not self._body.isVisible()
        self._body.setVisible(expanded)
        self._toggle.setText(self._open_text if expanded else self._closed_text)


class SourceLinkExpander(_ExpanderMixin, QFrame):
    """A short "why" description plus its excerpt, collapsed by default.

    Hidden entirely (``setVisible(False)``) until ``set_source`` is called
    with a real description — so it never shows an empty "Why?" control for
    a result that has nothing captured to explain (e.g. no active project).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SourceLinkExpander")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)

        top = QHBoxLayout()
        self._description = QLabel("")
        self._description.setObjectName("Muted")
        self._description.setWordWrap(True)
        top.addWidget(self._description, 1)
        toggle = PillButton("Why am I seeing this? ▸", ghost=True)
        top.addWidget(toggle)
        layout.addLayout(top)

        body = QLabel("")
        body.setObjectName("Muted")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)

        self._init_expander(toggle, body, "Why am I seeing this? ▸", "Why am I seeing this? ▾")
        self.setVisible(False)

    def set_source(self, description: str | None, excerpt: str | None) -> None:
        """Show ``description`` with ``excerpt`` revealed on click.

        Pass ``description=None`` (the default state) to hide the widget
        entirely — used when a result has no captured provenance to show,
        rather than displaying an empty/misleading "Why?" control.
        """
        if not description:
            self.setVisible(False)
            self._description.setText("")
            self._body.setText("")
            return
        self.setVisible(True)
        self._description.setText(description)
        if excerpt:
            self._body.setText(excerpt.strip())
        else:
            self._body.setText("(no excerpt was captured for this result)")
        self._body.setVisible(False)
        self._toggle.setText(self._closed_text)
