"""Live Task Progress Transparency (Phase L, deferred from Phase K, Core tier).

A small, reusable, appending list of plain-language step descriptions a
long-running worker can emit while it runs -- e.g. "Running EditMode tests…"
-- instead of a bare spinner or a numeric percentage progress bar.
Deliberately not a ``QProgressBar``: per spec this is about a human-readable
trail of *what's happening right now*, and most of this app's long-running
workers (a Unity test run, an AI review, a headless Unity build) have no
reliable total-step count to compute a percentage from anyway -- a fabricated
percentage would violate this app's "no fabricated data" principle just as
much as a fabricated metric would.

Wire-up: give a worker its own ``progress = Signal(str)`` and pass
``progress_slot=trail.add_step`` to ``ui.thread_utils.launch_worker``. Fully
optional on both ends -- a worker with no ``progress`` signal, or a screen
with no ``ProgressTrail``, behaves exactly as it did before this feature
existed. See ``ui.thread_utils.launch_worker`` for the connection itself.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QListWidget, QListWidgetItem, QVBoxLayout


class ProgressTrail(QFrame):
    """A small scrolling list of plain-language step descriptions.

    Stays hidden (``setVisible(False)``) until the first step arrives, so it
    never takes up space on a screen whose current action doesn't emit
    progress -- most of them, by design (see the module docstring).
    """

    def __init__(self, parent=None, *, max_height: int = 110) -> None:
        super().__init__(parent)
        self.setObjectName("ProgressTrail")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._list = QListWidget()
        self._list.setObjectName("ProgressTrailList")
        self._list.setFixedHeight(max_height)
        layout.addWidget(self._list)

        self.setVisible(False)

    def reset(self) -> None:
        """Clear the trail and hide it again -- call at the start of a new run."""
        self._list.clear()
        self.setVisible(False)

    def add_step(self, message: str) -> None:
        """Append one plain-language step and scroll to it.

        Shows the trail on its first step (see the class docstring) so it
        stays entirely out of the way for actions that never emit progress.
        """
        item = QListWidgetItem(message)
        self._list.addItem(item)
        self._list.scrollToItem(item)
        self.setVisible(True)

    def steps(self) -> list[str]:
        """The trail's current contents, oldest first -- mainly for tests."""
        return [self._list.item(i).text() for i in range(self._list.count())]
