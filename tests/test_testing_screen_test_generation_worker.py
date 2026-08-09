"""Tests for ui.screens.testing._TestCaseScriptWorker: the "Generate Unity
test script" button's worker for the Functional tab's test-case-to-script
generation flow.

No display is available in this environment, so this uses Qt's offscreen
platform plugin (same approach as test_testing_screen_build_worker.py) to
construct a real QObject headlessly, and calls ``run()`` directly rather
than going through a QThread.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.ai.base import AIProvider, AIResponse  # noqa: E402
from spiced.app.services import Services  # noqa: E402
from spiced.ui.screens.testing import _TestCaseScriptWorker  # noqa: E402

_app = QApplication.instance() or QApplication([])

CANNED = (
    "Here's a draft Unity test script for \"Player takes damage from spikes\".\n\n"
    "```csharp\n"
    "public class PlayerTakesDamageFromSpikesTests { }\n"
    "```\n\n"
    "Assumptions I made about your project:\n- None.\n\n"
    "Before you approve this:\nReview it first."
)


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_worker_emits_done_with_a_draft_for_the_selected_case(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    case = services.testing.create_case(
        project.id,
        "Player takes damage from spikes",
        steps="Walk into a spike trap",
        expected_result="Health decreases",
    )
    monkeypatch.setattr(services, "build_provider", lambda: FakeProvider())

    worker = _TestCaseScriptWorker(services, project, case)
    done = []
    worker.done.connect(done.append)
    worker.run()

    assert len(done) == 1
    result = done[0]
    assert result.draft.system_label == case.title
    assert "PlayerTakesDamageFromSpikesTests" in result.draft.draft_text


def test_worker_emits_failed_when_provider_not_ready(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    case = services.testing.create_case(project.id, "Some test case")
    monkeypatch.setattr(services, "build_provider", lambda: FakeProvider(available=False))

    worker = _TestCaseScriptWorker(services, project, case)
    failed = []
    worker.failed.connect(failed.append)
    worker.run()

    assert len(failed) == 1
    assert "isn't ready" in failed[0]


def test_worker_records_usage_via_services(monkeypatch, tmp_path):
    services = _services(tmp_path)
    project = services.projects.create_project("Moonlit Depths")
    case = services.testing.create_case(project.id, "Some test case")
    monkeypatch.setattr(services, "build_provider", lambda: FakeProvider())

    recorded = []
    monkeypatch.setattr(services.usage, "record_prompt", recorded.append)

    worker = _TestCaseScriptWorker(services, project, case)
    worker.run()

    assert recorded == ["fake"]
