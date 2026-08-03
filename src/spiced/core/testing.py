"""Automated Testing use-cases.

Two responsibilities, both human-centered:

1. Manual test cases — the developer authors and tracks them; Spiced only
   stores them and never runs anything. This works with no AI provider at all.
2. Test-result review — parse test output locally, ask the selected provider
   for a calm summary + retest checklist, and save a compact run. The output
   can come from a pasted/imported result set, or (opt-in, per project) from
   Spiced launching the project's own Unity Test Runner — either way it's the
   same parse -> analyze pipeline from this point on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spiced.ai.base import AIProvider
from spiced.ai.prompt_templates import build_test_review_prompt
from spiced.core.regression import RegressionOutcome, RegressionService, failure_signature
from spiced.core.test_result_parser import ParsedTestResults, parse_test_results
from spiced.storage.known_issues import SOURCE_TEST
from spiced.storage.projects import Project
from spiced.storage.test_cases import TestCase, TestCaseRepository
from spiced.storage.test_runs import TestRun, TestRunRepository

SOURCE_PASTE = "paste"
SOURCE_FILE = "file"
SOURCE_UNITY_RUN = "unity_run"


@dataclass(frozen=True)
class TestReview:
    parsed: ParsedTestResults
    response_text: str
    provider: str
    retest_checklist: list[str]
    run: TestRun | None
    regression_outcomes: list[RegressionOutcome] = field(default_factory=list)


class ProviderNotReadyError(RuntimeError):
    """Raised when the selected provider has no usable credentials."""


class TestingService:
    """Manual test-case management plus AI-assisted result review."""

    def __init__(
        self,
        cases: TestCaseRepository,
        runs: TestRunRepository,
        regression: RegressionService | None = None,
    ) -> None:
        self._cases = cases
        self._runs = runs
        self._regression = regression

    # --- Manual test cases (no provider needed) ---------------------------

    def create_case(
        self,
        project_id: int,
        title: str,
        category: str = "General",
        priority: str = "Medium",
        steps: str | None = None,
        expected_result: str | None = None,
    ) -> TestCase:
        return self._cases.create(
            project_id=project_id,
            title=title,
            category=category,
            priority=priority,
            steps=steps,
            expected_result=expected_result,
        )

    def set_status(
        self, test_case_id: int, status: str, failure_note: str | None = None
    ) -> TestCase:
        return self._cases.set_status(test_case_id, status, failure_note)

    def update_case(
        self,
        test_case_id: int,
        *,
        title: str,
        category: str = "General",
        priority: str = "Medium",
        steps: str | None = None,
        expected_result: str | None = None,
        status: str = "Not Run",
        failure_note: str | None = None,
    ) -> TestCase:
        return self._cases.update(
            test_case_id,
            title=title,
            category=category,
            priority=priority,
            steps=steps,
            expected_result=expected_result,
            status=status,
            failure_note=failure_note,
        )

    def delete_case(self, test_case_id: int) -> None:
        """Delete a manual test case. Saved test-run history is untouched."""
        self._cases.delete(test_case_id)

    def list_cases(self, project_id: int) -> list[TestCase]:
        return self._cases.list_for_project(project_id)

    def get_case(self, test_case_id: int) -> TestCase:
        return self._cases.get(test_case_id)

    # --- Result parsing + review ------------------------------------------

    def parse(self, results_text: str) -> ParsedTestResults:
        return parse_test_results(results_text)

    def analyze(
        self,
        provider: AIProvider,
        results_text: str,
        *,
        project: Project | None = None,
        source_type: str = SOURCE_PASTE,
        source_filename: str | None = None,
        record_usage=None,
        team_mode: bool = False,
        team_members: list[str] | None = None,
    ) -> TestReview:
        """Parse results, ask the provider for a review, and save a run.

        ``record_usage`` is called with the provider name after a successful
        reply so the usage counter can increment. ``team_mode``/``team_members``
        are Small-Team Mode context (Phase B); left at their defaults, behavior
        is identical to Solo-Dev Mode.
        """
        if not provider.is_available():
            raise ProviderNotReadyError(
                f"The {provider.display_name()} provider isn't ready. You can still create and "
                "track test cases without it. To analyze results, add its API key to a local "
                ".env file (see .env.example), or switch to the Mock provider in Settings."
            )

        parsed = self.parse(results_text)
        prompt = build_test_review_prompt(
            parsed,
            project_name=project.name if project else None,
            team_mode=team_mode,
            team_members=team_members,
        )
        response = provider.generate(prompt)
        if record_usage is not None:
            record_usage(response.provider)

        checklist = _extract_retest_checklist(response.text)
        run = None
        regression_outcomes: list[RegressionOutcome] = []
        if project is not None:
            regression_outcomes = self._note_regressions(project.id, parsed)
            run = self._runs.create(
                project_id=project.id,
                source_type=source_type,
                source_filename=source_filename,
                raw_excerpt=parsed.excerpt or None,
                parsed_summary=parsed.as_summary_dict(),
                ai_summary=_summarize(response.text),
                retest_checklist=checklist or None,
                provider=response.provider,
            )

        return TestReview(
            parsed=parsed,
            response_text=response.text,
            provider=response.provider,
            retest_checklist=checklist,
            run=run,
            regression_outcomes=regression_outcomes,
        )

    def _note_regressions(
        self, project_id: int, parsed: ParsedTestResults
    ) -> list[RegressionOutcome]:
        if self._regression is None:
            return []
        outcomes = []
        for failure in parsed.failures:
            signature = failure_signature(failure)
            outcomes.append(
                self._regression.note_issue(project_id, SOURCE_TEST, signature, failure)
            )
        return outcomes

    def known_issues(self, project_id: int):
        return self._regression.list_for_project(project_id) if self._regression else []

    def mark_issue_resolved(self, issue_id: int):
        if self._regression is None:
            raise RuntimeError("Regression tracking is not configured.")
        return self._regression.mark_resolved(issue_id)

    def mark_issue_open(self, issue_id: int):
        if self._regression is None:
            raise RuntimeError("Regression tracking is not configured.")
        return self._regression.mark_open(issue_id)

    def history(self, project_id: int, limit: int = 20) -> list[TestRun]:
        return self._runs.list_for_project(project_id, limit=limit)


def _summarize(response_text: str, limit: int = 240) -> str:
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.lower().startswith("here's what"):
            return stripped[:limit]
    return response_text.strip()[:limit]


def _extract_retest_checklist(response_text: str) -> list[str]:
    """Pull the bullet list under the 'Retest checklist:' heading, if present."""
    steps: list[str] = []
    capturing = False
    for line in response_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("retest checklist"):
            capturing = True
            continue
        if capturing:
            if stripped.startswith(("-", "*")):
                steps.append(stripped.lstrip("-* ").strip())
            elif stripped and stripped.endswith(":"):
                break
    return steps
