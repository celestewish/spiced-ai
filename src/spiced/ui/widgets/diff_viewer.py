"""Visual Diff Viewer (Phase L, Phase 2 tier).

One reusable widget for comparing two versions of something -- text or
images -- meant to be reused by several "compare" moments across the app
rather than built as a one-off for a single feature. Two real consumers are
wired up (see each screen's own comments for the exact call site):

1. Shaders/VFX's Visual Regression Testing report
   (``ui.screens.shaders_vfx.ShadersVfxScreen._on_view_diff_pair``, image
   mode) -- lets a developer open a specific before/after screenshot pair
   from a saved diff run in a side-by-side or highlighted-overlay view,
   instead of only reading the numeric changed-pixel-ratio line.
2. Debugging Buddy's Dev Docs snapshot history
   (``ui.screens.debugging.DebuggingScreen._on_compare_dev_docs_snapshots``,
   text mode) -- compares the two most recent Dev Docs snapshots' AI
   summaries, a natural "what changed since last time" moment for data this
   app already stores specifically as a version history (see
   ``core.dev_docs``'s module docstring).

Two modes:
- Text: two text blobs, diffed with stdlib ``difflib`` only (no new
  dependency) -- a side-by-side view (default) or a unified-diff view,
  toggle-able.
- Image: two image file paths, diffed by reusing
  ``core.visual_regression.diff_ratio_and_highlight`` -- the exact same
  Pillow pixel-difference logic Visual Regression Testing already uses --
  side-by-side or an overlay/highlighted-diff toggle.

The pure diff logic (``diff_text``) has no Qt dependency and is directly
unit-tested (see tests/test_diff_viewer.py); the widget classes below are
thin rendering wrappers left to import-cleanliness testing only, per this
app's "no display available" convention for GUI code.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from spiced.core.visual_regression import diff_ratio_and_highlight

_PIXMAP_MAX_DIM = 420


@dataclass(frozen=True)
class TextDiffResult:
    unified: str
    left_rows: list[str] = field(default_factory=list)
    right_rows: list[str] = field(default_factory=list)

    @property
    def has_differences(self) -> bool:
        return bool(self.unified.strip())


def diff_text(
    left: str, right: str, *, left_label: str = "before", right_label: str = "after"
) -> TextDiffResult:
    """Pure, GUI-free text diff -- stdlib ``difflib`` only.

    ``left_rows``/``right_rows`` are parallel, row-aligned lists suitable for
    rendering two side-by-side columns: an insertion/deletion pads the
    shorter side with ``""`` so both columns stay the same length and line
    up visually, row for row.
    """
    left_lines = left.splitlines()
    right_lines = right.splitlines()
    unified = "\n".join(
        difflib.unified_diff(
            left_lines, right_lines, fromfile=left_label, tofile=right_label, lineterm=""
        )
    )
    matcher = difflib.SequenceMatcher(None, left_lines, right_lines)
    left_rows: list[str] = []
    right_rows: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        left_chunk = left_lines[i1:i2]
        right_chunk = right_lines[j1:j2]
        if tag == "equal":
            left_rows.extend(left_chunk)
            right_rows.extend(right_chunk)
        else:
            width = max(len(left_chunk), len(right_chunk))
            for i in range(width):
                left_rows.append(left_chunk[i] if i < len(left_chunk) else "")
                right_rows.append(right_chunk[i] if i < len(right_chunk) else "")
    return TextDiffResult(unified=unified, left_rows=left_rows, right_rows=right_rows)


def _pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    data = rgb.tobytes("raw", "RGB")
    qimage = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimage.copy())  # .copy() so it owns its buffer


def _image_label(pixmap: QPixmap, caption: str) -> QWidget:
    wrapper = QWidget()
    layout = QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    title = QLabel(caption)
    title.setObjectName("Muted")
    layout.addWidget(title)
    picture = QLabel()
    picture.setPixmap(
        pixmap.scaled(
            _PIXMAP_MAX_DIM, _PIXMAP_MAX_DIM, Qt.AspectRatioMode.KeepAspectRatio
        )
    )
    layout.addWidget(picture)
    return wrapper


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


class DiffViewer(QWidget):
    """Renders either a text diff or an image diff, with a side-by-side /
    unified (text) or side-by-side / overlay (image) toggle. Call
    ``set_text`` or ``set_images`` to load content; either can be called
    again later to show a different comparison in the same widget."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DiffViewer")
        self._mode: str | None = None
        self._side_by_side = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)

        toggle_row = QHBoxLayout()
        self._toggle_btn = QPushButton("Toggle view")
        self._toggle_btn.setObjectName("Ghost")
        self._toggle_btn.clicked.connect(self._on_toggle)
        toggle_row.addWidget(self._toggle_btn)
        toggle_row.addStretch(1)
        outer.addLayout(toggle_row)

        self._body = QVBoxLayout()
        outer.addLayout(self._body)

    def set_text(
        self, left: str, right: str, *, left_label: str = "Before", right_label: str = "After"
    ) -> None:
        self._mode = "text"
        self._left_label = left_label
        self._right_label = right_label
        self._text_result = diff_text(left, right, left_label=left_label, right_label=right_label)
        self._side_by_side = True
        self._toggle_btn.setText("Show unified diff")
        self._render()

    def set_images(self, before_path: str | Path, after_path: str | Path) -> None:
        with Image.open(before_path) as before_img, Image.open(after_path) as after_img:
            before_img.load()
            after_img.load()
            ratio, highlight = diff_ratio_and_highlight(before_img, after_img)
            self._before_pixmap = _pil_to_pixmap(before_img)
            self._after_pixmap = _pil_to_pixmap(after_img)
        self._highlight_pixmap = _pil_to_pixmap(highlight)
        self._diff_ratio = ratio
        self._mode = "image"
        self._side_by_side = True
        self._toggle_btn.setText("Show highlighted overlay")
        self._render()

    def _on_toggle(self) -> None:
        self._side_by_side = not self._side_by_side
        if self._mode == "text":
            self._toggle_btn.setText(
                "Show unified diff" if self._side_by_side else "Show side-by-side"
            )
        elif self._mode == "image":
            self._toggle_btn.setText(
                "Show highlighted overlay" if self._side_by_side else "Show side-by-side"
            )
        self._render()

    def _render(self) -> None:
        _clear_layout(self._body)
        if self._mode == "text":
            self._render_text()
        elif self._mode == "image":
            self._render_image()

    def _render_text(self) -> None:
        result = self._text_result
        if self._side_by_side:
            row = QHBoxLayout()
            left = QPlainTextEdit("\n".join(result.left_rows))
            left.setReadOnly(True)
            right = QPlainTextEdit("\n".join(result.right_rows))
            right.setReadOnly(True)
            row.addWidget(left)
            row.addWidget(right)
            wrapper = QWidget()
            wrapper.setLayout(row)
            self._body.addWidget(wrapper)
        else:
            unified = QPlainTextEdit(result.unified or "(no textual differences)")
            unified.setReadOnly(True)
            self._body.addWidget(unified)

    def _render_image(self) -> None:
        info = QLabel(f"{self._diff_ratio * 100:.1f}% of pixels changed.")
        info.setObjectName("Muted")
        self._body.addWidget(info)
        if self._side_by_side:
            row = QHBoxLayout()
            row.addWidget(_image_label(self._before_pixmap, "Before"))
            row.addWidget(_image_label(self._after_pixmap, "After"))
            wrapper = QWidget()
            wrapper.setLayout(row)
            self._body.addWidget(wrapper)
        else:
            self._body.addWidget(_image_label(self._highlight_pixmap, "Highlighted diff"))


class DiffViewerDialog(QDialog):
    """A modal wrapper around ``DiffViewer`` -- the shape most call sites
    actually want (open a diff, look at it, close it)."""

    def __init__(self, parent: QWidget | None = None, *, title: str = "Compare") -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self.setWindowTitle(title)
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        self._viewer = DiffViewer(self)
        layout.addWidget(self._viewer, 1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("Ghost")
        close_btn.clicked.connect(self.close)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

    @property
    def viewer(self) -> DiffViewer:
        return self._viewer

    @classmethod
    def for_text(
        cls,
        left: str,
        right: str,
        *,
        left_label: str = "Before",
        right_label: str = "After",
        title: str = "Compare",
        parent: QWidget | None = None,
    ) -> DiffViewerDialog:
        dialog = cls(parent, title=title)
        dialog.viewer.set_text(left, right, left_label=left_label, right_label=right_label)
        return dialog

    @classmethod
    def for_images(
        cls,
        before_path: str | Path,
        after_path: str | Path,
        *,
        title: str = "Compare",
        parent: QWidget | None = None,
    ) -> DiffViewerDialog:
        dialog = cls(parent, title=title)
        dialog.viewer.set_images(before_path, after_path)
        return dialog
