"""Shared "tool switcher" shell: a left-hand list of tool-pill buttons
(``#ToolListPanel``/``#ToolListItem`` in ui.theme) driving a right-hand
``QStackedWidget`` of dark-glass hero-card pages (``#ToolHeroCard``). First
used by the Debugging Buddy redesign (built inline there); factored out here
for the Art/Audio/Animation/Shaders-VFX screens, which use the identical
shape.

Each tool's existing ``_build_*(layout)`` method is called unchanged with
that page's own ``QVBoxLayout`` -- this only changes how a screen's sections
are composed (one page each, switched by the list) rather than how any of
them build their own content.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from spiced.ui.widgets.pill_button import PillButton

ToolBuilder = Callable[[QVBoxLayout], None]


def build_tool_switcher(
    parent: QWidget,
    tools: list[tuple[str, ToolBuilder]],
    *,
    list_width: int = 230,
) -> tuple[QHBoxLayout, QStackedWidget, QButtonGroup]:
    """Returns ``(columns, stack, group)`` -- add ``columns`` to the
    screen's own layout. ``stack``/``group`` are returned in case the
    screen needs to react to tool switches or manage selection itself."""
    columns = QHBoxLayout()
    columns.setSpacing(16)

    tool_panel = QFrame()
    tool_panel.setObjectName("ToolListPanel")
    tool_panel.setFixedWidth(list_width)
    tool_layout = QVBoxLayout(tool_panel)
    tool_layout.setContentsMargins(14, 16, 14, 16)
    tool_layout.setSpacing(6)

    stack = QStackedWidget()
    group = QButtonGroup(parent)
    group.setExclusive(True)
    for index, (label, builder) in enumerate(tools):
        btn = PillButton(label, radius=14)
        btn.setObjectName("ToolListItem")
        btn.setCheckable(True)
        btn.clicked.connect(lambda _checked, i=index: stack.setCurrentIndex(i))
        group.addButton(btn, index)
        tool_layout.addWidget(btn)

        page = QFrame()
        page.setObjectName("ToolHeroCard")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 24, 24, 24)
        page_layout.setSpacing(10)
        builder(page_layout)

        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page_scroll.setWidget(page)
        stack.addWidget(page_scroll)
    tool_layout.addStretch(1)

    columns.addWidget(tool_panel, 0)
    columns.addWidget(stack, 1)

    if group.buttons():
        group.buttons()[0].setChecked(True)
        stack.setCurrentIndex(0)

    return columns, stack, group
