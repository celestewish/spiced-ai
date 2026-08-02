"""Regression Tracking: match new failures against previously seen ones.

Every debugging session's primary error and every test-result failure gets a
deterministic signature. Spiced keeps a lightweight, deduplicated history of
those signatures (open or resolved) and checks each new one against it before
recording it — so a repeat surfaces as "this resembles a bug from before"
instead of being re-diagnosed from scratch. Matching is local and heuristic;
nothing here is sent to an AI provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from spiced.storage.known_issues import KnownIssue, KnownIssueRepository

MATCH_EXACT = "exact"
MATCH_SIMILAR = "similar"

_SIMILARITY_THRESHOLD = 0.5
_MIN_SIGNIFICANT_WORDS = 2
_WORD_RE = re.compile(r"[a-z0-9]+")


def normalize_text(text: str) -> str:
    """Lowercase and collapse to alphanumeric words for signature/matching use."""
    return " ".join(_WORD_RE.findall((text or "").lower()))


def debug_signature(error_type: str, location: str | None) -> str:
    return f"debug::{normalize_text(error_type)}::{normalize_text(location or '')}"


def failure_signature(failure_name: str) -> str:
    return f"test::{normalize_text(failure_name)[:160]}"


@dataclass(frozen=True)
class RegressionMatch:
    issue: KnownIssue
    kind: str  # MATCH_EXACT | MATCH_SIMILAR
    score: float

    @property
    def note(self) -> str:
        when = self.issue.resolved_at or self.issue.first_seen_at
        if self.issue.status == "resolved":
            return (
                f"Resembles \"{self.issue.title}\", marked resolved on {when}. "
                "If this is back, it may be a regression."
            )
        return f"Matches an already-tracked open issue \"{self.issue.title}\" (first seen {when})."


@dataclass(frozen=True)
class RegressionOutcome:
    issue: KnownIssue
    match: RegressionMatch | None


class RegressionService:
    """Cross-references new failures against a project's known-issue history."""

    def __init__(self, issues: KnownIssueRepository) -> None:
        self._issues = issues

    def note_issue(
        self,
        project_id: int,
        source: str,
        signature: str,
        title: str,
        category: str | None = None,
    ) -> RegressionOutcome:
        """Check ``signature``/``title`` against history, then record it.

        Returns the (now upserted) known issue and a match, if any pre-existing
        issue looks like the same bug.
        """
        existing = self._issues.find(project_id, signature)
        match: RegressionMatch | None = None
        if existing is not None:
            match = RegressionMatch(issue=existing, kind=MATCH_EXACT, score=1.0)
        else:
            fuzzy = self._best_fuzzy_match(project_id, signature, title)
            if fuzzy is not None:
                match = fuzzy

        issue = self._issues.upsert(project_id, signature, source, title, category)
        return RegressionOutcome(issue=issue, match=match)

    def _best_fuzzy_match(
        self, project_id: int, signature: str, title: str
    ) -> RegressionMatch | None:
        words = set(normalize_text(title).split())
        if len(words) < _MIN_SIGNIFICANT_WORDS:
            return None
        best_issue: KnownIssue | None = None
        best_score = 0.0
        for candidate in self._issues.list_for_project(project_id):
            if candidate.signature == signature:
                continue
            candidate_words = set(normalize_text(candidate.title).split())
            if len(candidate_words) < _MIN_SIGNIFICANT_WORDS:
                continue
            overlap = words & candidate_words
            union = words | candidate_words
            score = len(overlap) / len(union) if union else 0.0
            if score > best_score:
                best_score = score
                best_issue = candidate
        if best_issue is not None and best_score >= _SIMILARITY_THRESHOLD:
            return RegressionMatch(issue=best_issue, kind=MATCH_SIMILAR, score=best_score)
        return None

    def list_for_project(self, project_id: int) -> list[KnownIssue]:
        return self._issues.list_for_project(project_id)

    def mark_resolved(self, issue_id: int) -> KnownIssue:
        return self._issues.mark_resolved(issue_id)

    def mark_open(self, issue_id: int) -> KnownIssue:
        return self._issues.mark_open(issue_id)
