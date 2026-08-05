"""Wishlist/Analytics Summary use-case (Phase G, section 7, Phase 2 tier).

Scope decision: there is no public, OAuth-free Steam or itch wishlist/
analytics API — both would require registering an OAuth application and
per-platform approval this session cannot provision, so a live integration
is not realistic here. Instead the developer exports their own analytics
numbers (wishlists, conversion %, traffic sources) as a small, documented
CSV and pastes/imports it; Spiced diffs it against the previous import for
the same project and summarizes the trend in plain language — "what's
working, what's flat, what changed since last import." This is a paste/
import workflow, not a live API integration; see the in-UI note on the
Marketing screen.

Documented format — one ``metric,value`` pair per line, header row required:

    metric,value
    wishlists,1240
    conversion_pct,3.8
    visits,15300
    top_referrer,twitter

Any subset of these (or extra metrics) is accepted; unrecognized metric
names are still diffed (numerically if parseable, otherwise as opaque
strings) even though Spiced has no specific plain-language framing for them
beyond the four documented above.

The diff/summary here is purely local and deterministic — no AI call is
needed to say "wishlists went from 1240 to 1400," so this feature works
fully offline and free, unlike most of the other AI-backed features in this
phase.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field

from spiced.storage.projects import Project
from spiced.storage.wishlist_analytics_imports import (
    WishlistAnalyticsImport,
    WishlistAnalyticsImportRepository,
)

MAX_RAW_EXCERPT_CHARS = 4000


class InvalidAnalyticsFormatError(RuntimeError):
    """Raised when the pasted/imported text isn't valid ``metric,value`` CSV."""


@dataclass(frozen=True)
class MetricChange:
    metric: str
    previous: str | None
    current: str
    delta: float | None  # only set for numeric metrics with a parseable previous value


@dataclass(frozen=True)
class WishlistAnalyticsDigest:
    metrics: dict[str, str]
    changes: list[MetricChange]
    is_first_import: bool
    summary_lines: list[str] = field(default_factory=list)
    saved_import: WishlistAnalyticsImport | None = None


def parse_metrics_csv(text: str) -> dict[str, str]:
    reader = csv.DictReader(io.StringIO(text.strip()))
    fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "metric" not in fieldnames or "value" not in fieldnames:
        raise InvalidAnalyticsFormatError(
            'Expected a CSV with "metric,value" columns, e.g.:\n'
            "metric,value\nwishlists,1240\nconversion_pct,3.8\nvisits,15300\ntop_referrer,twitter"
        )
    metrics: dict[str, str] = {}
    for row in reader:
        # DictReader keys follow the original header casing, so look up by
        # whichever key case-folds to "metric"/"value".
        name = value = None
        for key, val in row.items():
            if key is None:
                continue
            key_lower = key.strip().lower()
            if key_lower == "metric":
                name = (val or "").strip()
            elif key_lower == "value":
                value = (val or "").strip()
        if name:
            metrics[name] = value or ""
    if not metrics:
        raise InvalidAnalyticsFormatError("No metric rows found in the pasted/imported CSV.")
    return metrics


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def diff_metrics(previous: dict[str, str] | None, current: dict[str, str]) -> list[MetricChange]:
    changes = []
    for name, value in current.items():
        prev_value = previous.get(name) if previous else None
        delta = None
        if prev_value is not None:
            cur_f, prev_f = _as_float(value), _as_float(prev_value)
            if cur_f is not None and prev_f is not None:
                delta = cur_f - prev_f
        changes.append(MetricChange(metric=name, previous=prev_value, current=value, delta=delta))
    return changes


def summarize_digest(changes: list[MetricChange], is_first_import: bool) -> list[str]:
    """Plain-language "what's working, what's flat, what changed" lines.

    Purely local/deterministic — no AI call, no network. A short heuristic
    gloss, not a replacement for the developer reading the actual numbers.
    """
    if is_first_import:
        return ["First import for this project — nothing to compare against yet."]
    lines = []
    for change in changes:
        if change.delta is None:
            if change.previous is not None and change.previous != change.current:
                lines.append(
                    f"{change.metric}: changed from {change.previous} to {change.current}."
                )
            continue
        if change.delta > 0:
            lines.append(
                f"{change.metric}: up from {change.previous} to {change.current} "
                f"(+{change.delta:g})."
            )
        elif change.delta < 0:
            lines.append(
                f"{change.metric}: down from {change.previous} to {change.current} "
                f"({change.delta:g})."
            )
        else:
            lines.append(f"{change.metric}: flat at {change.current}.")
    if not lines:
        lines.append("Nothing changed since the last import.")
    return lines


class WishlistAnalyticsService:
    def __init__(self, imports: WishlistAnalyticsImportRepository) -> None:
        self._imports = imports

    def import_csv(
        self, project: Project, text: str, *, source_filename: str | None = None
    ) -> WishlistAnalyticsDigest:
        metrics = parse_metrics_csv(text)
        previous = self._imports.latest_for_project(project.id)
        previous_metrics = previous.metrics if previous else None
        changes = diff_metrics(previous_metrics, metrics)
        is_first = previous is None
        summary_lines = summarize_digest(changes, is_first)

        saved = self._imports.create(
            project_id=project.id,
            metrics_json=json.dumps(metrics),
            raw_excerpt=text.strip()[:MAX_RAW_EXCERPT_CHARS] or None,
            source_filename=source_filename,
        )
        return WishlistAnalyticsDigest(
            metrics=metrics,
            changes=changes,
            is_first_import=is_first,
            summary_lines=summary_lines,
            saved_import=saved,
        )

    def history(self, project_id: int, limit: int = 20) -> list[WishlistAnalyticsImport]:
        return self._imports.list_for_project(project_id, limit=limit)
