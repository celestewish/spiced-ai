"""Art/Audio/Animation/VFX automation (Implementation Bible).

Shared foundation (Feature 0) that every discipline-specific automation
feature (#1-13 in SPICED_IMPLEMENTATION_BIBLE.md) builds on: a single
``Finding`` output contract and a ``BatchRunner`` that walks a directory of
assets and runs a per-file check.
"""

from spiced.automation.batch_runner import BatchRunner
from spiced.automation.finding import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STATUS_ERROR,
    STATUS_FLAGGED,
    STATUS_PASS,
    VALID_SEVERITIES,
    VALID_STATUSES,
    Finding,
    FindingItem,
    InvalidFindingError,
)

__all__ = [
    "BatchRunner",
    "Finding",
    "FindingItem",
    "InvalidFindingError",
    "STATUS_ERROR",
    "STATUS_FLAGGED",
    "STATUS_PASS",
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "VALID_STATUSES",
    "VALID_SEVERITIES",
]
