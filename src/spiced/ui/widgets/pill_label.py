"""A QLabel that always paints a genuinely round, antialiased shape.

Same underlying problem as ``pill_button.PillButton`` -- see its module
docstring for the full "QSS border-radius isn't reliably honored" story --
and the same fix shape: render unclipped, then punch the corners outside a
rounded-rect path back to transparent. Used for solid-filled status pills
(e.g. ``ReadinessBadge``'s "Needs Review"/"Ready for Playtesters" pill).

QLabel needs one extra step ``PillButton`` doesn't: a stylesheet-styled
QLabel gets ``Qt.WA_StyledBackground`` set automatically, which makes Qt
paint the label's QSS background as an implicit *opaque, square* pre-fill
before ``paintEvent`` even runs. Punching transparent corners into our own
painted buffer doesn't help if that square pre-fill is still sitting
underneath it on the backing store -- the "transparent" corners just let
the square fill show back through. ``Qt.WA_NoSystemBackground`` turns that
implicit pre-fill off so our buffer is the only thing painted.

QLabel also has no single "draw the whole control" style call the way
``QStyle.CE_PushButton`` covers a button's background/border/label in one
go, so background and text are drawn as two separate steps here:
``QStyle.PE_Widget`` for the QSS-driven background/border (the same
primitive Qt itself would've used for that implicit pre-fill), then the
text drawn directly with the label's own font/alignment/palette color.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPixmap
from PySide6.QtWidgets import QLabel, QStyle, QStyleOption, QWidget


class PillLabel(QLabel):
    def __init__(
        self, text: str = "", parent: QWidget | None = None, *, radius: float | None = None
    ) -> None:
        super().__init__(text, parent)
        self._fixed_radius = radius
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, event: QPaintEvent) -> None:
        if self.width() <= 0 or self.height() <= 0:
            super().paintEvent(event)
            return

        radius = self._fixed_radius if self._fixed_radius is not None else self.height() / 2

        buffer = QPixmap(self.size())
        buffer.fill(Qt.transparent)
        buffer_painter = QPainter(buffer)
        buffer_painter.setRenderHint(QPainter.Antialiasing)
        option = QStyleOption()
        option.initFrom(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, buffer_painter, self)
        buffer_painter.setPen(self.palette().color(self.foregroundRole()))
        buffer_painter.setFont(self.font())
        # contentsRect(), not rect() -- QSS padding is applied to this
        # widget's contents margins (Qt does this automatically for a
        # stylesheet-styled widget), so drawing into the raw, un-inset rect
        # left text sitting flush against the left edge with all the
        # padding's width pushed to the right instead of split evenly.
        buffer_painter.drawText(self.contentsRect(), int(self.alignment()), self.text())
        buffer_painter.end()

        buffer_painter = QPainter(buffer)
        buffer_painter.setRenderHint(QPainter.Antialiasing)
        full_rect = QPainterPath()
        full_rect.addRect(QRectF(buffer.rect()))
        rounded_rect = QPainterPath()
        rounded_rect.addRoundedRect(QRectF(buffer.rect()), radius, radius)
        corners = full_rect.subtracted(rounded_rect)
        buffer_painter.setCompositionMode(QPainter.CompositionMode_Clear)
        buffer_painter.fillPath(corners, Qt.transparent)
        buffer_painter.end()

        widget_painter = QPainter(self)
        widget_painter.setRenderHint(QPainter.Antialiasing)
        widget_painter.drawPixmap(0, 0, buffer)
