"""Deterministic test-result parser.

Reads pasted or imported test output (plain text, JSON, or NUnit-style XML) and
extracts pass/fail/skipped counts, failure names, a relevant excerpt, and a
confidence level. It runs entirely locally and sends nothing anywhere — the AI
step builds on this structured output rather than re-parsing raw text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from xml.etree import ElementTree

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

FORMAT_TEXT = "text"
FORMAT_JSON = "json"
FORMAT_XML = "xml"

MAX_EXCERPT_CHARS = 2000
MAX_FAILURES = 50

# "PASS Player can move", "FAILED: thing", "SKIPPED - other"
_STATUS_LINE_RE = re.compile(
    r"^\s*(?P<status>PASS(?:ED)?|FAIL(?:ED)?|ERROR|SKIP(?:PED)?|BLOCKED|IGNORED)\b"
    r"[:\-\s]*(?P<name>.*)$",
    re.IGNORECASE,
)
# "Total: 5", "Passed: 2", "Failed : 2", "Skipped 1"
_SUMMARY_LINE_RE = re.compile(
    r"^\s*(?P<key>total|passed|pass|failed|fail|skipped|skip|blocked|ignored|errors?)\s*[:=]?\s*"
    r"(?P<value>\d+)\s*$",
    re.IGNORECASE,
)


def _status_bucket(status: str) -> str:
    s = status.upper()
    if s.startswith("PASS"):
        return "passed"
    if s.startswith(("FAIL", "ERROR")):
        return "failed"
    return "skipped"  # SKIP, SKIPPED, BLOCKED, IGNORED


@dataclass
class ParsedTestResults:
    source_format: str
    total: int
    passed: int
    failed: int
    skipped: int
    failures: list[str] = field(default_factory=list)
    excerpt: str = ""
    confidence: str = CONFIDENCE_LOW

    @property
    def has_results(self) -> bool:
        return self.total > 0 or bool(self.failures)

    def as_summary_dict(self) -> dict:
        return {
            "source_format": self.source_format,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "failures": self.failures,
            "confidence": self.confidence,
        }


def parse_test_results(text: str) -> ParsedTestResults:
    """Parse test output, auto-detecting JSON, XML, or plain text."""
    stripped = text.strip()
    if not stripped:
        return ParsedTestResults(FORMAT_TEXT, 0, 0, 0, 0, confidence=CONFIDENCE_LOW)

    if stripped[0] in "{[":
        parsed = _try_parse_json(stripped)
        if parsed is not None:
            return parsed
    if stripped[0] == "<":
        parsed = _try_parse_xml(stripped)
        if parsed is not None:
            return parsed
    return _parse_text(text)


def _cap(excerpt: str) -> str:
    if len(excerpt) > MAX_EXCERPT_CHARS:
        return excerpt[:MAX_EXCERPT_CHARS].rstrip() + "\n… (truncated)"
    return excerpt


def _parse_text(text: str) -> ParsedTestResults:
    line_counts = {"passed": 0, "failed": 0, "skipped": 0}
    summary: dict[str, int] = {}
    failures: list[str] = []
    relevant: list[str] = []
    lines = text.splitlines()

    for i, raw in enumerate(lines):
        line = raw.rstrip()

        # A pure "key: number" line is a summary, even though words like
        # "Passed"/"Failed" also match the status regex — summary wins here.
        summary_match = _SUMMARY_LINE_RE.match(line)
        if summary_match:
            key = summary_match.group("key").lower()
            value = int(summary_match.group("value"))
            summary[_normalize_summary_key(key)] = value
            relevant.append(line.strip())
            continue

        status_match = _STATUS_LINE_RE.match(line)
        if status_match:
            bucket = _status_bucket(status_match.group("status"))
            line_counts[bucket] += 1
            relevant.append(line.strip())
            name = status_match.group("name").strip()
            if bucket == "failed" and len(failures) < MAX_FAILURES:
                detail = _peek_detail(lines, i)
                failures.append(f"{name} — {detail}" if detail else (name or "(unnamed failure)"))
            continue

    passed = summary.get("passed", line_counts["passed"])
    failed = summary.get("failed", line_counts["failed"])
    skipped = summary.get("skipped", line_counts["skipped"])
    total = summary.get("total", passed + failed + skipped)

    confidence = _text_confidence(summary, line_counts, total)
    excerpt = _cap("\n".join(relevant)) if relevant else _cap(text.strip())
    return ParsedTestResults(
        FORMAT_TEXT, total, passed, failed, skipped, failures, excerpt, confidence
    )


def _normalize_summary_key(key: str) -> str:
    if key in ("pass", "passed"):
        return "passed"
    if key in ("fail", "failed", "error", "errors"):
        return "failed"
    if key in ("skip", "skipped", "blocked", "ignored"):
        return "skipped"
    return key  # "total"


def _peek_detail(lines: list[str], index: int) -> str | None:
    """Return the next non-empty line if it isn't itself a status/summary line."""
    for nxt in lines[index + 1 : index + 2]:
        candidate = nxt.strip()
        if candidate and not _STATUS_LINE_RE.match(candidate) and not _SUMMARY_LINE_RE.match(
            candidate
        ):
            return candidate
    return None


def _text_confidence(summary: dict, line_counts: dict, total: int) -> str:
    if total <= 0:
        return CONFIDENCE_LOW
    have_summary = "total" in summary or "passed" in summary or "failed" in summary
    line_total = line_counts["passed"] + line_counts["failed"] + line_counts["skipped"]
    if have_summary and line_total > 0:
        summary_total = summary.get(
            "total",
            summary.get("passed", 0) + summary.get("failed", 0) + summary.get("skipped", 0),
        )
        if summary_total == line_total:
            return CONFIDENCE_HIGH
    if have_summary or line_total > 0:
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_LOW


def _try_parse_json(text: str) -> ParsedTestResults | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    tests = None
    if isinstance(data, list):
        tests = data
    elif isinstance(data, dict):
        for key in ("tests", "results", "testcases", "cases"):
            if isinstance(data.get(key), list):
                tests = data[key]
                break

    passed = failed = skipped = 0
    failures: list[str] = []

    if tests is not None:
        for item in tests:
            if not isinstance(item, dict):
                continue
            status = str(
                item.get("status") or item.get("result") or item.get("outcome") or ""
            )
            bucket = _status_bucket(status) if status else _bool_bucket(item)
            name = str(item.get("name") or item.get("title") or item.get("test") or "test")
            if bucket == "passed":
                passed += 1
            elif bucket == "failed":
                failed += 1
                if len(failures) < MAX_FAILURES:
                    msg = item.get("message") or item.get("error") or ""
                    failures.append(f"{name} — {msg}".strip(" —") if msg else name)
            else:
                skipped += 1
        total = len(tests)
        confidence = CONFIDENCE_HIGH
    elif isinstance(data, dict):
        # Top-level count fields, e.g. {"passed": 2, "failed": 2, "skipped": 1}.
        passed = _int(data, "passed", "pass")
        failed = _int(data, "failed", "fail", "errors")
        skipped = _int(data, "skipped", "skip", "blocked")
        total = _int(data, "total", "tests") or (passed + failed + skipped)
        raw_failures = data.get("failures") or data.get("failed_tests") or []
        if isinstance(raw_failures, list):
            failures = [str(f) for f in raw_failures[:MAX_FAILURES]]
        confidence = CONFIDENCE_MEDIUM if (total or passed or failed) else CONFIDENCE_LOW
    else:
        return None

    excerpt = _cap(json.dumps(data)[:MAX_EXCERPT_CHARS]) if isinstance(data, (dict, list)) else ""
    return ParsedTestResults(
        FORMAT_JSON, total, passed, failed, skipped, failures, excerpt, confidence
    )


def _bool_bucket(item: dict) -> str:
    if item.get("passed") is True or item.get("success") is True:
        return "passed"
    if item.get("passed") is False or item.get("success") is False:
        return "failed"
    if item.get("skipped") is True:
        return "skipped"
    return "skipped"


def _int(data: dict, *keys: str) -> int:
    for key in keys:
        value = data.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return 0


def _try_parse_xml(text: str) -> ParsedTestResults | None:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None

    cases = list(root.iter("test-case"))
    passed = failed = skipped = 0
    failures: list[str] = []

    for case in cases:
        result = (case.get("result") or "").lower()
        name = case.get("name") or case.get("fullname") or "test"
        if result.startswith("pass") or result == "success":
            passed += 1
        elif result.startswith(("fail", "error")):
            failed += 1
            if len(failures) < MAX_FAILURES:
                message = _xml_failure_message(case)
                failures.append(f"{name} — {message}" if message else name)
        elif result:
            skipped += 1

    if cases:
        total = len(cases)
        confidence = CONFIDENCE_HIGH
    else:
        # Fall back to summary attributes on the root (e.g. NUnit <test-run>).
        total = _attr_int(root, "total", "testcasecount")
        passed = _attr_int(root, "passed")
        failed = _attr_int(root, "failed")
        skipped = _attr_int(root, "skipped", "inconclusive")
        if not any((total, passed, failed, skipped)):
            return None
        if not total:
            total = passed + failed + skipped
        confidence = CONFIDENCE_MEDIUM

    excerpt = _cap(text.strip())
    return ParsedTestResults(
        FORMAT_XML, total, passed, failed, skipped, failures, excerpt, confidence
    )


def _xml_failure_message(case: ElementTree.Element) -> str | None:
    for tag in ("message", "failure/message"):
        node = case.find(tag)
        if node is not None and node.text:
            return node.text.strip().splitlines()[0][:200]
    return None


def _attr_int(element: ElementTree.Element, *names: str) -> int:
    for name in names:
        value = element.get(name)
        if value and value.isdigit():
            return int(value)
    return 0
