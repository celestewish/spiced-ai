"""Shared automation Finding schema (Implementation Bible, Feature 0).

Every automation feature (#1-13 in SPICED_IMPLEMENTATION_BIBLE.md) returns
one ``Finding`` in this exact shape, regardless of discipline (audio, art,
animation, VFX) -- this is what lets all of them plug into the same
Testing/Debugging results UI, the same chatbox summarization, and the same
regression-tracking history, instead of each feature inventing its own
report shape. See the Bible's section 0, "Output contract".
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone

STATUS_PASS = "pass"
STATUS_FLAGGED = "flagged"
STATUS_ERROR = "error"
VALID_STATUSES = {STATUS_PASS, STATUS_FLAGGED, STATUS_ERROR}

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"
VALID_SEVERITIES = {SEVERITY_INFO, SEVERITY_WARNING, SEVERITY_ERROR}


class InvalidFindingError(ValueError):
    """Raised when a Finding or FindingItem is constructed with an out-of-schema value."""


@dataclass(frozen=True)
class FindingItem:
    asset_path: str
    severity: str
    message: str
    detail: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in VALID_SEVERITIES:
            raise InvalidFindingError(
                f"severity must be one of {sorted(VALID_SEVERITIES)}, got {self.severity!r}"
            )

    def as_dict(self) -> dict:
        return {
            "asset_path": self.asset_path,
            "severity": self.severity,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Finding:
    feature_id: str
    project_id: str
    status: str
    summary: str
    items: list[FindingItem] = field(default_factory=list)
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise InvalidFindingError(
                f"status must be one of {sorted(VALID_STATUSES)}, got {self.status!r}"
            )

    @property
    def severity_counts(self) -> dict[str, int]:
        counts = {SEVERITY_INFO: 0, SEVERITY_WARNING: 0, SEVERITY_ERROR: 0}
        for item in self.items:
            counts[item.severity] += 1
        return counts

    def as_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "run_id": self.run_id,
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "status": self.status,
            "summary": self.summary,
            "items": [item.as_dict() for item in self.items],
        }

    @staticmethod
    def status_for(items: Iterable[FindingItem]) -> str:
        """Roll a list of items up into an overall run status: any 'error'
        severity item makes the whole run 'error', any 'warning' (with no
        errors) makes it 'flagged', otherwise 'pass'."""
        severities = {item.severity for item in items}
        if SEVERITY_ERROR in severities:
            return STATUS_ERROR
        if SEVERITY_WARNING in severities:
            return STATUS_FLAGGED
        return STATUS_PASS
