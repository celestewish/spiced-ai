"""Spotlight overlay: dims the window and cuts a hole around the current
step's target widget, with a small callout box beside it.

Nothing in the codebase already did this in place -- ``ShortcutsCheatSheet``
(``ui.shortcuts_cheatsheet``) is a plain modal dialog, and
``ProgressTrail``/``SourceLinkExpander`` are inline disclosure widgets. Two
things this must not become, given what the Unity Alpha Readiness Spec's
Priority 1 just fixed (a ``QGraphicsDropShadowEffect`` on the frame holding
every screen was forcing a full-subtree offscreen rasterize on every repaint
of anything inside it):

- **No ``QGraphicsEffect`` of any kind.** This is a plain ``QWidget`` with a
  hand-painted dim scrim + cutout, composited the ordinary way.
- **No timer, no per-frame ticking.** Step changes and resizes each trigger
  exactly one ``update()`` call; there is no ``Ticker``-driven animation
  loop here to reintroduce that class of bug.

Styling deliberately reuses what ``theme.py``/``ui.widgets.pill_button``
already define rather than inventing new colors: the callout gets
``objectName("Panel")`` (the same rounded cream-glass look ``ShortcutsCheatSheet``
gets from ``QDialog#Panel`` -- the callout itself is a ``QFrame``, which is
what picks up ``theme.py``'s separate ``QFrame#Panel`` rule; a plain
``QWidget`` matches neither selector and paints no background at all), its
heading gets ``objectName("SectionTitle")``, and its buttons are
``PillButton``. A screenshot of a tutorial step should be indistinguishable
in style from any other Spiced panel.

The cutout around the current step's target widget is a real hole, not a
painted illusion: ``setMask()`` excludes that region from this widget's own
paint *and* hit-testing, so the target widget already rendered underneath
shows through with correct compositing (not a solid black square -- trying
to "clear" a hole into an opaque widget's own paint buffer via
``CompositionMode_Clear`` does not reveal a sibling widget's already-painted
pixels, it just leaves undefined/black content there) and, critically,
remains genuinely clickable through the overlay -- the entire point of the
"click Analyze" step this overlay drives.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QPainter, QRegion
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from spiced.ui import theme
from spiced.ui.widgets.pill_button import PillButton

# theme.py's own stated principle for high-contrast mode (module docstring):
# translucency undermines the point of that mode, so every panel resolves to
# a flat, opaque value there instead of a gradient -- this scrim follows the
# same rule, and deliberately does NOT read palette["SIDEBAR"] in that mode
# (which means something else there: a light neutral panel tone, not a dim
# overlay -- see HIGH_CONTRAST_PALETTE).
_SCRIM_HIGH_CONTRAST = QColor(0, 0, 0, 255)
_SCRIM_ALPHA = 170  # ~67%, over the default palette's SIDEBAR (#2B1C46)


@dataclass
class TutorialStep:
    title: str
    body: str
    # Resolved fresh each time the step is shown, not cached -- the target
    # widget may not exist yet (or its geometry may not be valid) when the
    # step list is first built.
    target: Callable[[], QWidget | None]
    on_enter: Callable[[], None] | None = None
    # When set, the step auto-advances on this Qt signal instead of waiting
    # for "Next" -- used for "click Analyze, then wait for the real result"
    # so the user's own click drives progress, not a button in this overlay.
    auto_advance_signal: Any = field(default=None)


class TutorialOverlay(QWidget):
    """Dims ``main_window``, cuts a hole around the current step's target
    widget, and shows a callout beside it. Repaints only on step change or
    resize -- see this module's docstring for why that matters here."""

    def __init__(self, main_window: QWidget, services) -> None:
        super().__init__(main_window)
        self._main_window = main_window
        self._services = services
        self._steps: list[TutorialStep] = []
        self._index = 0
        self._on_finished: Callable[[bool], None] | None = None
        self._connected_signal: Any = None

        self._callout = QFrame(self)
        self._callout.setObjectName("Panel")
        self._callout.setFixedWidth(320)
        callout_layout = QVBoxLayout(self._callout)
        self._title_label = QLabel()
        self._title_label.setObjectName("SectionTitle")
        self._body_label = QLabel()
        self._body_label.setWordWrap(True)
        callout_layout.addWidget(self._title_label)
        callout_layout.addWidget(self._body_label)
        buttons = QHBoxLayout()
        self._skip_btn = PillButton("Skip", ghost=True)
        self._skip_btn.clicked.connect(lambda: self.finish(skipped=True))
        self._next_btn = PillButton("Next")
        self._next_btn.clicked.connect(self._advance)
        buttons.addWidget(self._skip_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._next_btn)
        callout_layout.addLayout(buttons)
        self._callout.hide()

    # --- Public API ----------------------------------------------------

    def start(self, steps: list[TutorialStep], on_finished: Callable[[bool], None]) -> None:
        """Show the overlay and begin at the first step. ``on_finished``
        is called with ``skipped=True`` if the developer clicked Skip at
        any point, or ``False`` once every step has been shown and the
        last one advanced past -- the caller (``ui.main_window``) decides
        what each case means (e.g. whether to show a closing hand-off
        dialog only on genuine completion)."""
        self._steps = steps
        self._index = 0
        self._on_finished = on_finished
        self.setGeometry(self._main_window.rect())
        self.show()
        self.raise_()
        self._show_step()

    def resize_to_parent(self) -> None:
        """Call from ``main_window``'s own ``resizeEvent`` -- this widget
        has no layout manager and Qt does not resize a plain child
        automatically when its parent does."""
        if self.isVisible():
            self.setGeometry(self._main_window.rect())
            self._refresh_cutout()

    # --- Step flow -------------------------------------------------------

    def _show_step(self) -> None:
        self._disconnect_auto_advance()
        step = self._steps[self._index]
        self._title_label.setText(step.title)
        self._body_label.setText(step.body)
        self._next_btn.setVisible(step.auto_advance_signal is None)
        if step.on_enter is not None:
            step.on_enter()
        if step.auto_advance_signal is not None:
            step.auto_advance_signal.connect(self._advance)
            self._connected_signal = step.auto_advance_signal
        self._refresh_cutout()

    def _disconnect_auto_advance(self) -> None:
        if self._connected_signal is not None:
            try:
                self._connected_signal.disconnect(self._advance)
            except (RuntimeError, TypeError):
                pass  # already disconnected, or the signal's owner is gone
            self._connected_signal = None

    def _advance(self) -> None:
        self._index += 1
        if self._index >= len(self._steps):
            self.finish(skipped=False)
            return
        self._show_step()

    def finish(self, *, skipped: bool) -> None:
        self._disconnect_auto_advance()
        self._callout.hide()
        self.clearMask()
        self.hide()
        if self._on_finished is not None:
            self._on_finished(skipped)

    # --- Cutout: a real hole, not a painted illusion ------------------------
    #
    # setMask() excludes the cutout region from both this widget's own
    # painting AND its hit-testing -- unlike trying to "clear" a hole via
    # CompositionMode_Clear (which only ever operates on this widget's own
    # paint buffer and can't reveal a sibling's already-rendered pixels;
    # it just leaves undefined/black content there instead), masking lets
    # the target widget underneath show through with correct compositing
    # and, just as importantly, keeps it genuinely clickable through the
    # overlay -- required for the "click Analyze" step to work at all.

    def _resolve_cutout(self) -> QRect | None:
        if not self._steps:
            return None
        target = self._steps[self._index].target()
        if target is None or not target.isVisible():
            return None
        self._ensure_target_visible(target)
        top_left = target.mapTo(self._main_window, target.rect().topLeft())
        return QRect(top_left, target.size())

    @staticmethod
    def _ensure_target_visible(target: QWidget) -> None:
        """Scroll ``target`` into view first if it's inside a ``QScrollArea``
        that hasn't already scrolled to show it -- e.g. DebuggingScreen puts
        every tool's content in its own per-tool QScrollArea, and a widget
        further down that content (like the "Full transparency" step's
        source-link expander) reports ``isVisible() == True`` regardless of
        whether it's actually within the scrolled viewport right now. Without
        this, the cutout/callout end up pointing at a widget the developer
        can't see or reach without first scrolling manually -- the walkthrough
        needs to do that scrolling itself, not assume the page is already
        positioned right.
        """
        parent = target.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                parent.ensureWidgetVisible(target, 20, 20)
                return
            parent = parent.parentWidget()

    def _refresh_cutout(self) -> None:
        cutout = self._resolve_cutout()
        if cutout is None:
            self.clearMask()
        else:
            region = QRegion(self.rect())
            region -= QRegion(cutout)
            self.setMask(region)
        self.update()
        self._position_callout(cutout)

    # --- Painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._steps:
            return
        painter = QPainter(self)
        painter.fillRect(self.rect(), self._scrim_color())

    def _scrim_color(self) -> QColor:
        high_contrast = bool(
            self._services is not None
            and getattr(self._services, "accessibility_high_contrast_enabled", lambda: False)()
        )
        if high_contrast:
            return _SCRIM_HIGH_CONTRAST
        colorblind_safe = bool(
            self._services is not None
            and getattr(self._services, "accessibility_colorblind_safe_enabled", lambda: False)()
        )
        palette = theme.resolve_palette(high_contrast=False, colorblind_safe=colorblind_safe)
        color = QColor(palette["SIDEBAR"])
        color.setAlpha(_SCRIM_ALPHA)
        return color

    def _position_callout(self, cutout: QRect | None) -> None:
        self._callout.adjustSize()
        if cutout is None:
            # No visible target (e.g. the widget it points at hasn't been
            # shown yet) -- fall back to a centered callout rather than
            # pointing at nothing.
            x = (self.width() - self._callout.width()) // 2
            y = (self.height() - self._callout.height()) // 2
        else:
            x = min(cutout.left(), self.width() - self._callout.width() - 16)
            y = cutout.bottom() + 12
            if y + self._callout.height() > self.height():
                y = max(0, cutout.top() - self._callout.height() - 12)
        self._callout.move(max(16, x), max(16, y))
        self._callout.show()
        self._callout.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.update()
