"""Tests for core.test_generator: draft generation + the approve/write flow.

Covers the "never write to disk except after an explicit per-file Approve"
rule and the "never silently overwrite an existing file" rule.
"""

from __future__ import annotations

import pytest

from spiced.ai.base import AIProvider, AIResponse
from spiced.core.test_generator import (
    NoUnityFolderError,
    ProviderNotReadyError,
    TestGeneratorService,
    extract_code_block,
    find_test_folder,
    next_available_path,
    suggested_class_name,
)
from spiced.storage.database import Database
from spiced.storage.generated_test_drafts import GeneratedTestDraftRepository
from spiced.storage.projects import ProjectRepository
from spiced.storage.test_cases import TestCaseRepository

CANNED = (
    "Here's a draft test file for InventorySystem.\n\n"
    "```csharp\n"
    "using NUnit.Framework;\n\n"
    "public class InventorySystemTests\n"
    "{\n"
    "    [Test]\n"
    "    public void AddItem_IncreasesCount()\n"
    "    {\n"
    "        Assert.Pass();\n"
    "    }\n"
    "}\n"
    "```\n\n"
    "Assumptions I made:\n- None.\n\n"
    "Before you approve this:\nReview it first."
)


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, available=True, text=CANNED):
        self._available = available
        self._text = text

    def is_available(self):
        return self._available

    def generate(self, prompt):
        return AIResponse(text=self._text, provider=self.name, model="fake-1")


def _service_and_project(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("Moonlit Depths", engine="Unity")
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    service = TestGeneratorService(GeneratedTestDraftRepository(db))
    return service, project


# --- extract_code_block / suggested_class_name / next_available_path --------


def test_extract_code_block_pulls_fenced_csharp():
    code = extract_code_block(CANNED)
    assert code.startswith("using NUnit.Framework;")
    assert "```" not in code


def test_extract_code_block_falls_back_to_whole_text_when_no_fence():
    assert extract_code_block("just some text") == "just some text"


def test_suggested_class_name_from_class_declaration():
    assert suggested_class_name("public class FooTests {}", None) == "FooTests"


def test_suggested_class_name_falls_back_to_system_label():
    name = suggested_class_name("nothing to see here", "Inventory System!")
    assert name == "InventorySystemTests"


def test_suggested_class_name_generic_fallback():
    assert suggested_class_name("nothing useful", None) == "GeneratedTests"


def test_next_available_path_appends_suffix_when_taken(tmp_path):
    existing = tmp_path / "FooTests.cs"
    existing.write_text("existing", encoding="utf-8")
    result = next_available_path(existing)
    assert result == tmp_path / "FooTests_2.cs"


def test_next_available_path_returns_same_path_when_free(tmp_path):
    target = tmp_path / "FooTests.cs"
    assert next_available_path(target) == target


def test_find_test_folder_prefers_existing_editmode(tmp_path):
    (tmp_path / "Assets" / "Tests" / "EditMode").mkdir(parents=True)
    assert find_test_folder(tmp_path) == tmp_path / "Assets" / "Tests" / "EditMode"


def test_find_test_folder_falls_back_to_default(tmp_path):
    assert find_test_folder(tmp_path) == tmp_path / "Assets" / "Tests" / "EditMode"


# --- generate_draft -----------------------------------------------------------


def test_generate_draft_raises_when_provider_unavailable(tmp_path):
    service, project = _service_and_project(tmp_path)
    with pytest.raises(ProviderNotReadyError):
        service.generate_draft(FakeProvider(available=False), project, "class Foo {}")


def test_generate_draft_never_writes_to_disk(tmp_path):
    service, project = _service_and_project(tmp_path)
    result = service.generate_draft(
        FakeProvider(), project, "public class Inventory {}", system_label="InventorySystem"
    )
    assert result.draft.written_path is None
    assert result.draft.approved is False
    assert not list((tmp_path / "Assets").rglob("*.cs")) if (tmp_path / "Assets").exists() else True


def test_generate_draft_saves_extracted_code_not_full_response(tmp_path):
    service, project = _service_and_project(tmp_path)
    result = service.generate_draft(FakeProvider(), project, "public class Inventory {}")
    assert result.draft.draft_text is not None
    assert "```" not in result.draft.draft_text
    assert "Here's a draft" not in result.draft.draft_text
    # The full response (with commentary) is still available separately.
    assert "Assumptions I made" in result.response_text


# --- approve_and_write ---------------------------------------------------------


def test_approve_and_write_raises_without_unity_folder():
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("No Folder")
    service = TestGeneratorService(GeneratedTestDraftRepository(db))
    draft = service._drafts.create(project.id, "Foo", "excerpt", "public class FooTests {}", "fake")
    with pytest.raises(NoUnityFolderError):
        service.approve_and_write(project, draft.id)


def test_approve_and_write_writes_the_file(tmp_path):
    service, project = _service_and_project(tmp_path)
    result = service.generate_draft(FakeProvider(), project, "public class Inventory {}")
    draft = service.approve_and_write(project, result.draft.id)
    assert draft.approved is True
    assert draft.written_path is not None
    written = tmp_path / "Assets" / "Tests" / "EditMode" / "InventorySystemTests.cs"
    assert written.is_file()
    assert "AddItem_IncreasesCount" in written.read_text(encoding="utf-8")


def test_approve_and_write_uses_edited_text(tmp_path):
    service, project = _service_and_project(tmp_path)
    result = service.generate_draft(FakeProvider(), project, "public class Inventory {}")
    edited = "public class InventorySystemTests { /* edited by developer */ }"
    draft = service.approve_and_write(project, result.draft.id, edited_text=edited)
    written = tmp_path / draft.written_path[len(str(tmp_path)) + 1 :]
    assert "edited by developer" in written.read_text(encoding="utf-8")


def test_approve_and_write_never_clobbers_existing_file(tmp_path):
    service, project = _service_and_project(tmp_path)
    test_folder = tmp_path / "Assets" / "Tests" / "EditMode"
    test_folder.mkdir(parents=True)
    existing = test_folder / "InventorySystemTests.cs"
    existing.write_text("// hand-written, do not touch", encoding="utf-8")

    result = service.generate_draft(FakeProvider(), project, "public class Inventory {}")
    draft = service.approve_and_write(project, result.draft.id)

    assert draft.written_path != str(existing)
    assert draft.written_path.endswith("InventorySystemTests_2.cs")
    # The original file was left completely untouched.
    assert existing.read_text(encoding="utf-8") == "// hand-written, do not touch"


def test_approve_and_write_overwrite_true_replaces_target(tmp_path):
    service, project = _service_and_project(tmp_path)
    test_folder = tmp_path / "Assets" / "Tests" / "EditMode"
    test_folder.mkdir(parents=True)
    existing = test_folder / "InventorySystemTests.cs"
    existing.write_text("old content", encoding="utf-8")

    result = service.generate_draft(FakeProvider(), project, "public class Inventory {}")
    draft = service.approve_and_write(project, result.draft.id, overwrite=True)

    assert draft.written_path == str(existing)
    assert "old content" not in existing.read_text(encoding="utf-8")


# --- generate_draft_from_test_case ---------------------------------------------
#
# Distinct from generate_draft above: the source here is one of the
# developer's own already-created QA test cases (title/steps/expected), not
# a pasted script -- see ui.screens.testing's "Generate a Unity test script"
# section on the Functional tab, which lets the developer pick one of their
# existing test cases and generate a script from it.

CASE_CANNED = (
    "Here's a draft Unity test script for \"Player takes damage from spikes\".\n\n"
    "```csharp\n"
    "using NUnit.Framework;\n\n"
    "public class PlayerTakesDamageFromSpikesTests\n"
    "{\n"
    "    [Test]\n"
    "    public void Player_LosesHealth_WhenTouchingSpikes()\n"
    "    {\n"
    "        Assert.Pass();\n"
    "    }\n"
    "}\n"
    "```\n\n"
    "Assumptions I made about your project:\n- None.\n\n"
    "Before you approve this:\nReview it first."
)


def _service_project_and_case(tmp_path):
    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("Moonlit Depths", engine="Unity")
    project = repo.set_unity_folder(project.id, str(tmp_path), "unknown")
    service = TestGeneratorService(GeneratedTestDraftRepository(db))
    case = TestCaseRepository(db).create(
        project.id,
        "Player takes damage from spikes",
        steps="1. Walk player into a spike trap\n2. Observe health bar",
        expected_result="Player health decreases by the spike's configured damage amount",
    )
    return service, project, case


def test_generate_draft_from_test_case_raises_when_provider_unavailable(tmp_path):
    service, project, case = _service_project_and_case(tmp_path)
    with pytest.raises(ProviderNotReadyError):
        service.generate_draft_from_test_case(FakeProvider(available=False), project, case)


def test_generate_draft_from_test_case_never_writes_to_disk(tmp_path):
    service, project, case = _service_project_and_case(tmp_path)
    result = service.generate_draft_from_test_case(FakeProvider(text=CASE_CANNED), project, case)
    assert result.draft.written_path is None
    assert result.draft.approved is False


def test_generate_draft_from_test_case_saves_extracted_code_and_labels_by_title(tmp_path):
    service, project, case = _service_project_and_case(tmp_path)
    result = service.generate_draft_from_test_case(FakeProvider(text=CASE_CANNED), project, case)
    assert result.draft.draft_text is not None
    assert "```" not in result.draft.draft_text
    assert result.draft.system_label == case.title
    # The test case's own fields are what's kept as the excerpt/audit trail
    # -- there's no pasted source code for this flow.
    assert case.title in result.draft.source_excerpt
    assert case.steps in result.draft.source_excerpt
    assert case.expected_result in result.draft.source_excerpt


def test_generate_draft_from_test_case_prompt_includes_case_fields():
    captured = {}

    class CapturingProvider(FakeProvider):
        def generate(self, prompt):
            captured["prompt"] = prompt
            return super().generate(prompt)

    db = Database(":memory:")
    repo = ProjectRepository(db)
    project = repo.create("Moonlit Depths", engine="Unity")
    case = TestCaseRepository(db).create(
        project.id,
        "Player takes damage from spikes",
        steps="Walk into a spike trap",
        expected_result="Health decreases",
    )
    service = TestGeneratorService(GeneratedTestDraftRepository(db))
    service.generate_draft_from_test_case(CapturingProvider(text=CASE_CANNED), project, case)

    prompt = captured["prompt"]
    assert "Player takes damage from spikes" in prompt
    assert "Walk into a spike trap" in prompt
    assert "Health decreases" in prompt
    # This flow has no pasted source code -- the prompt shouldn't claim there is any.
    assert "Source code the developer supplied" not in prompt


def test_generate_draft_from_test_case_can_then_be_approved_and_written(tmp_path):
    service, project, case = _service_project_and_case(tmp_path)
    result = service.generate_draft_from_test_case(FakeProvider(text=CASE_CANNED), project, case)
    draft = service.approve_and_write(project, result.draft.id)
    assert draft.approved is True
    written = tmp_path / "Assets" / "Tests" / "EditMode" / "PlayerTakesDamageFromSpikesTests.cs"
    assert written.is_file()
    assert "Player_LosesHealth_WhenTouchingSpikes" in written.read_text(encoding="utf-8")
