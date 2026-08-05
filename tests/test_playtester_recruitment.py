"""Tests for core.playtester_recruitment: draft prompt + local sign-up CRUD.

The local sign-up list is the scoped-down "distribution flow" per spec —
these tests cover create/list/status-update/delete, and that no email or
build-distribution side effect ever happens (there's nothing in the service
that could send one).
"""

from __future__ import annotations

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.prompt_templates import build_playtester_recruitment_prompt
from spiced.core.playtester_recruitment import (
    STATUS_CONFIRMED,
    STATUS_INVITED,
    STATUS_TESTED,
    PlaytesterRecruitmentService,
    ProviderNotReadyError,
)
from spiced.storage.database import Database
from spiced.storage.playtester_signups import PlaytesterSignupRepository
from spiced.storage.projects import ProjectRepository

CANNED = "Here's a draft recruitment post."


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True):
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=CANNED, provider=self.name, model="fake-1")


def test_build_playtester_recruitment_prompt_includes_inputs():
    prompt = build_playtester_recruitment_prompt(
        needs_description="new co-op mode",
        target_platform="Windows/Steam",
        timeframe="next 2 weeks",
    )
    assert "new co-op mode" in prompt
    assert "Windows/Steam" in prompt
    assert "next 2 weeks" in prompt
    assert "never post, recruit, or distribute anything yourself" in prompt


def test_draft_post_raises_when_provider_not_ready():
    db = Database(":memory:")
    service = PlaytesterRecruitmentService(PlaytesterSignupRepository(db))
    with pytest.raises(ProviderNotReadyError):
        service.draft_post(
            FakeProvider(available=False),
            needs_description="x",
            target_platform="y",
            timeframe="z",
        )


def test_draft_post_returns_response_text():
    db = Database(":memory:")
    service = PlaytesterRecruitmentService(PlaytesterSignupRepository(db))
    result = service.draft_post(
        FakeProvider(), needs_description="x", target_platform="y", timeframe="z"
    )
    assert result.response_text == CANNED
    assert result.provider == "fake"


def test_signup_crud_flow():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = PlaytesterRecruitmentService(PlaytesterSignupRepository(db))

    signup = service.add_signup(project.id, "Ari", "ari@example.com")
    assert signup.status == STATUS_INVITED

    signups = service.list_signups(project.id)
    assert len(signups) == 1
    assert signups[0].name == "Ari"

    updated = service.set_status(signup.id, STATUS_CONFIRMED)
    assert updated.status == STATUS_CONFIRMED

    updated = service.set_status(signup.id, STATUS_TESTED)
    assert updated.status == STATUS_TESTED

    service.delete_signup(signup.id)
    assert service.list_signups(project.id) == []


def test_add_signup_requires_a_name():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = PlaytesterRecruitmentService(PlaytesterSignupRepository(db))
    with pytest.raises(ValueError):
        service.add_signup(project.id, "  ", None)


def test_set_status_rejects_unknown_status():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    project = projects.create("Moonlit Depths")
    service = PlaytesterRecruitmentService(PlaytesterSignupRepository(db))
    signup = service.add_signup(project.id, "Ari", None)
    with pytest.raises(ValueError):
        service.set_status(signup.id, "banned")
