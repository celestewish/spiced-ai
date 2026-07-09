import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import HUMAN_CONTROL_RULES, build_unity_debug_prompt
from spiced.core.debugging import DebuggingService, ProviderNotReadyError
from spiced.core.unity_log_parser import parse_unity_log
from spiced.storage.database import Database
from spiced.storage.debug_sessions import DebugSessionRepository
from spiced.storage.projects import ProjectRepository

CANNED_RESPONSE = """Here's what looks most likely.

Likely issue:
A referenced object is null.

Evidence from the log:
- NullReferenceException
- HealthPickup.cs line 24

What to check in Unity:
- Inspector references

Safe next steps:
- Check the scene setup
- Verify the health component
- Reproduce the crash

I would not change yet:
- Do not delete the prefab
"""

NULL_REF_LOG = (
    "NullReferenceException: Object reference not set to an instance of an object\n"
    "HealthPickup.OnTriggerEnter2D (UnityEngine.Collider2D other) "
    "(at Assets/Scripts/HealthPickup.cs:24)\n"
)


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True, reply=CANNED_RESPONSE):
        self._available = available
        self._reply = reply
        self.last_prompt = None

    def is_available(self):
        return self._available

    def generate(self, prompt):
        self.last_prompt = prompt
        return AIResponse(text=self._reply, provider=self.name, model="fake-1")


def _service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    sessions = DebugSessionRepository(db)
    project = projects.create("Moonlit Depths", engine="Unity")
    return DebuggingService(sessions), project


def test_prompt_includes_human_control_rules():
    parsed = parse_unity_log(NULL_REF_LOG)
    prompt = build_unity_debug_prompt(parsed, project_name="Moonlit Depths")
    # Every human-control rule must be present verbatim.
    for rule in HUMAN_CONTROL_RULES:
        assert rule in prompt
    # And the detected evidence must be carried into the prompt.
    assert "NullReferenceException" in prompt
    assert "HealthPickup.cs" in prompt
    assert "24" in prompt


def test_prompt_forbids_auto_edit_language():
    parsed = parse_unity_log(NULL_REF_LOG)
    prompt = build_unity_debug_prompt(parsed).lower()
    assert "never claim you changed" in prompt
    assert "never suggest automatic code edits" in prompt


def test_analyze_saves_session_and_records_usage():
    service, project = _service()
    recorded = []
    analysis = service.analyze(
        FakeProvider(),
        NULL_REF_LOG,
        project=project,
        record_usage=recorded.append,
    )
    assert analysis.session is not None
    assert analysis.session.detected_error_type == "NullReferenceException"
    assert analysis.session.detected_file == "HealthPickup.cs"
    assert analysis.session.detected_line == 24
    assert analysis.session.suggested_next_steps  # extracted from "Safe next steps"
    assert recorded == ["fake"]


def test_analyze_without_project_does_not_save():
    service, _ = _service()
    analysis = service.analyze(FakeProvider(), NULL_REF_LOG, project=None)
    assert analysis.session is None
    assert analysis.parsed.primary.error_type == "NullReferenceException"


def test_analyze_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.analyze(FakeProvider(available=False), NULL_REF_LOG, project=project)
