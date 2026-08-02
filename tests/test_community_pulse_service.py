import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import COMMUNITY_PULSE_RULES, build_community_pulse_prompt
from spiced.core.community.mock_source import MockCommunitySource
from spiced.core.community_pulse import (
    CommunityPulseService,
    ProviderNotReadyError,
    SourceNotReadyError,
)
from spiced.storage.community_pulse import CommunityPulseRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

CANNED = """Here's this community pulse check-in.

What was read:
#mock-community, 5 messages

Overall vibe:
Generally positive with one performance note.

Recurring notes:
- Loading time mentioned once

Anything that sounds like a bug:
- Nothing that reads as a concrete bug.

What I would not assume yet:
- Small sample
"""


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


class UnavailableSource(MockCommunitySource):
    def is_available(self):
        return False


def _service():
    db = Database(":memory:")
    project = ProjectRepository(db).create("Moonlit Depths", engine="Unity")
    return CommunityPulseService(CommunityPulseRepository(db)), project


def test_prompt_is_transparent_about_what_was_read():
    source = MockCommunitySource()
    messages = source.fetch_recent()
    prompt = build_community_pulse_prompt(messages, channel_label=source.channel_label())
    for rule in COMMUNITY_PULSE_RULES:
        assert rule in prompt
    assert source.channel_label() in prompt
    assert str(len(messages)) in prompt


def test_check_in_saves_checkin_and_records_usage():
    service, project = _service()
    recorded = []
    result = service.check_in(
        FakeProvider(), MockCommunitySource(), project=project, record_usage=recorded.append
    )
    assert result.checkin is not None
    assert result.message_count == 5
    assert recorded == ["fake"]
    assert service.history(project.id)[0].id == result.checkin.id


def test_check_in_without_project_does_not_save():
    service, _ = _service()
    result = service.check_in(FakeProvider(), MockCommunitySource(), project=None)
    assert result.checkin is None


def test_check_in_raises_when_source_unavailable():
    service, project = _service()
    with pytest.raises(SourceNotReadyError):
        service.check_in(FakeProvider(), UnavailableSource(), project=project)


def test_check_in_raises_when_provider_unavailable():
    service, project = _service()
    with pytest.raises(ProviderNotReadyError):
        service.check_in(FakeProvider(available=False), MockCommunitySource(), project=project)
