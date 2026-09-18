"""TutorialFinishDialog: the tutorial's closing hand-off -- both buttons
close the dialog, and only "Connect a project" also asks the caller to
navigate there.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other widget tests.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ui.tutorial.finish_dialog import TutorialFinishDialog  # noqa: E402
from spiced.ui.widgets.pill_button import PillButton  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _button(dialog: TutorialFinishDialog, text: str) -> PillButton:
    matches = [b for b in dialog.findChildren(PillButton) if b.text() == text]
    assert len(matches) == 1, f"expected exactly one {text!r} button, found {len(matches)}"
    return matches[0]


def test_maybe_later_closes_without_requesting_a_project_connect():
    dialog = TutorialFinishDialog()
    requests = []
    dialog.connect_project_requested.connect(lambda: requests.append(True))

    _button(dialog, "Maybe later").click()

    assert requests == []
    assert dialog.result() == TutorialFinishDialog.DialogCode.Accepted


def test_connect_a_project_emits_the_request_then_closes():
    dialog = TutorialFinishDialog()
    requests = []
    dialog.connect_project_requested.connect(lambda: requests.append(True))

    _button(dialog, "Connect a project").click()

    assert requests == [True]
    assert dialog.result() == TutorialFinishDialog.DialogCode.Accepted
