"""A QLabel that always paints a genuinely round, antialiased shape.

Same fix as ``pill_button.PillButton`` -- see its module docstring for the
full story, including why the radius is recomputed lazily at the top of
``paintEvent`` (self-correcting against premature-height reads) rather than
only in ``resizeEvent``. Used for solid-filled status pills (e.g.
``ReadinessBadge``'s "Needs Review"/"Ready for Playtesters" pill) where the
oversized ``border-radius: 999px`` trick proved just as unreliable on QLabel
as it was on QPushButton; an exact radius matching the label's real height
fixes it the same way.
"""

from __future__ import annotations

from PySide6.QtGui import QPaintEvent
from PySide6.QtWidgets import QLabel, QWidget


class PillLabel(QLabel):
    def __init__(
        self, text: str = "", parent: QWidget | None = None, *, radius: float | None = None
    ) -> None:
        super().__init__(text, parent)
        self._fixed_radius = radius
        self._applied_radius: int | None = None

    def paintEvent(self, event: QPaintEvent) -> None:
        self._apply_exact_radius()
        super().paintEvent(event)

    def _apply_exact_radius(self) -> None:
        if self.height() <= 0:
            return
        radius = round(self._fixed_radius if self._fixed_radius is not None else self.height() / 2)
        if radius <= 0 or radius == self._applied_radius:
            return
        self._applied_radius = radius
        self.setStyleSheet(f"border-radius: {radius}px;")
        # setStyleSheet() alone doesn't reliably force Qt's cached style-sheet
        # render rules to refresh in time for the paint pass already under
        # way when this runs (it's called from paintEvent) -- unpolish/polish
        # is the explicit way to invalidate that cache immediately.
        self.style().unpolish(self)
        self.style().polish(self)
