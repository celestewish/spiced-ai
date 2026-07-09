"""Deterministic feedback parser.

Reads pasted or imported player feedback (plain text, Markdown notes, CSV rows,
or JSON arrays/objects) and normalizes it into feedback entries with an entry
count, detected fields, a relevant excerpt, and a confidence level. It runs
entirely locally and sends nothing anywhere — the classifier and AI step build
on this structured output rather than re-parsing raw text.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"

FORMAT_TEXT = "text"
FORMAT_MARKDOWN = "markdown"
FORMAT_CSV = "csv"
FORMAT_JSON = "json"

MAX_EXCERPT_CHARS = 2000
MAX_ENTRIES = 200

# Columns/keys that obviously carry the feedback text.
_TEXT_FIELDS = ("comment", "comments", "feedback", "review", "text", "message", "note", "notes",
                "response", "body")
# Other obvious fields worth surfacing to the AI.
_META_FIELDS = ("rating", "score", "stars", "bug", "category", "source", "author", "name",
                "user", "player", "playtester")

# "Playtester 1: ...", "Alex - ...", "[Survey] ..."
_LABEL_RE = re.compile(r"^\s*(?P<label>[\w .#'\-]{1,40}?)\s*[:\-–]\s+(?P<body>.+)$")
_BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<body>.+)$")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+")


@dataclass
class FeedbackEntry:
    text: str
    author: str | None = None
    rating: str | None = None
    fields: dict = field(default_factory=dict)


@dataclass
class ParsedFeedback:
    source_format: str
    entry_count: int
    entries: list[FeedbackEntry] = field(default_factory=list)
    detected_fields: list[str] = field(default_factory=list)
    excerpt: str = ""
    confidence: str = CONFIDENCE_LOW

    @property
    def has_entries(self) -> bool:
        return self.entry_count > 0

    def as_summary_dict(self) -> dict:
        return {
            "source_format": self.source_format,
            "entry_count": self.entry_count,
            "detected_fields": self.detected_fields,
            "confidence": self.confidence,
        }


def _cap(text: str) -> str:
    if len(text) > MAX_EXCERPT_CHARS:
        return text[:MAX_EXCERPT_CHARS].rstrip() + "\n… (truncated)"
    return text


def _split_label(line: str) -> tuple[str | None, str]:
    """Split "Playtester 1: body" into (label, body); label only if it looks like one."""
    match = _LABEL_RE.match(line)
    if match:
        label = match.group("label").strip()
        # A label shouldn't itself be a full sentence.
        if label and " " not in label.strip(". ") or len(label.split()) <= 4:
            return label, match.group("body").strip()
    return None, line.strip()


def parse_feedback(text: str, *, filename: str | None = None) -> ParsedFeedback:
    """Parse feedback, auto-detecting JSON, CSV, Markdown, or plain text.

    ``filename`` (when known) biases format detection by extension but content
    is always inspected too.
    """
    stripped = text.strip()
    if not stripped:
        return ParsedFeedback(FORMAT_TEXT, 0, confidence=CONFIDENCE_LOW)

    ext = ""
    if filename and "." in filename:
        ext = filename.rsplit(".", 1)[1].lower()

    if stripped[0] in "{[" or ext == "json":
        parsed = _try_parse_json(stripped)
        if parsed is not None:
            return parsed
    if ext == "csv" or _looks_like_csv(stripped):
        parsed = _try_parse_csv(stripped)
        if parsed is not None:
            return parsed
    if ext == "md" or _looks_like_markdown(stripped):
        return _parse_markdown(text)
    return _parse_text(text)


def _looks_like_markdown(text: str) -> bool:
    for line in text.splitlines():
        if _BULLET_RE.match(line) or _HEADING_RE.match(line):
            return True
    return False


def _looks_like_csv(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    reader = csv.reader(io.StringIO(text))
    counts = [len(row) for row in reader if row]
    if len(counts) < 2:
        return False
    # Consistent multi-column rows, or a header naming a known feedback field.
    first = next(csv.reader(io.StringIO(lines[0])), [])
    header_hit = any(cell.strip().lower() in _TEXT_FIELDS + _META_FIELDS for cell in first)
    consistent = counts[0] >= 2 and counts.count(counts[0]) >= max(2, int(len(counts) * 0.8))
    return header_hit or consistent


def _parse_text(text: str) -> ParsedFeedback:
    entries: list[FeedbackEntry] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        author, body = _split_label(line)
        entries.append(FeedbackEntry(text=body, author=author))
        if len(entries) >= MAX_ENTRIES:
            break
    confidence = CONFIDENCE_MEDIUM if entries else CONFIDENCE_LOW
    return ParsedFeedback(
        FORMAT_TEXT, len(entries), entries, [], _cap(text.strip()), confidence
    )


def _parse_markdown(text: str) -> ParsedFeedback:
    entries: list[FeedbackEntry] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or _HEADING_RE.match(line):
            continue
        bullet = _BULLET_RE.match(line)
        content = bullet.group("body").strip() if bullet else line.strip()
        author, body = _split_label(content)
        entries.append(FeedbackEntry(text=body, author=author))
        if len(entries) >= MAX_ENTRIES:
            break
    confidence = CONFIDENCE_MEDIUM if entries else CONFIDENCE_LOW
    return ParsedFeedback(
        FORMAT_MARKDOWN, len(entries), entries, [], _cap(text.strip()), confidence
    )


def _try_parse_csv(text: str) -> ParsedFeedback | None:
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        return None

    header = [cell.strip() for cell in rows[0]]
    header_lower = [h.lower() for h in header]
    text_cols = [i for i, h in enumerate(header_lower) if h in _TEXT_FIELDS]
    meta_cols = {h: i for i, h in enumerate(header_lower) if h in _META_FIELDS}
    detected = [header[i] for i in text_cols] + [header[meta_cols[h]] for h in meta_cols]

    entries: list[FeedbackEntry] = []
    for row in rows[1:]:
        cells = [c.strip() for c in row]
        if text_cols:
            body = " ".join(cells[i] for i in text_cols if i < len(cells) and cells[i]).strip()
        else:
            body = " ".join(c for c in cells if c).strip()
        if not body:
            continue
        author = _cell(cells, meta_cols, ("author", "name", "user", "player", "playtester"))
        rating = _cell(cells, meta_cols, ("rating", "score", "stars"))
        entries.append(FeedbackEntry(text=body, author=author, rating=rating))
        if len(entries) >= MAX_ENTRIES:
            break

    if not entries:
        return None
    confidence = CONFIDENCE_HIGH if detected else CONFIDENCE_MEDIUM
    return ParsedFeedback(
        FORMAT_CSV, len(entries), entries, detected, _cap(text.strip()), confidence
    )


def _cell(cells: list[str], meta_cols: dict, keys: tuple[str, ...]) -> str | None:
    for key in keys:
        idx = meta_cols.get(key)
        if idx is not None and idx < len(cells) and cells[idx]:
            return cells[idx]
    return None


def _try_parse_json(text: str) -> ParsedFeedback | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    items = None
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("feedback", "entries", "comments", "responses", "results", "items"):
            if isinstance(data.get(key), list):
                items = data[key]
                break
        if items is None:
            items = [data]
    if items is None:
        return None

    entries: list[FeedbackEntry] = []
    detected: list[str] = []
    for item in items:
        if isinstance(item, str):
            body = item.strip()
            author = rating = None
        elif isinstance(item, dict):
            body = _dict_text(item, detected)
            author = _dict_first(item, ("author", "name", "user", "player", "playtester"))
            rating = _dict_first(item, ("rating", "score", "stars"))
        else:
            continue
        if not body:
            continue
        entries.append(FeedbackEntry(text=body, author=author, rating=rating))
        if len(entries) >= MAX_ENTRIES:
            break

    if not entries:
        return None
    confidence = CONFIDENCE_HIGH if detected else CONFIDENCE_MEDIUM
    excerpt = _cap(json.dumps(data)[:MAX_EXCERPT_CHARS])
    # Preserve first-seen order without duplicates.
    seen: list[str] = []
    for name in detected:
        if name not in seen:
            seen.append(name)
    return ParsedFeedback(FORMAT_JSON, len(entries), entries, seen, excerpt, confidence)


def _dict_text(item: dict, detected: list[str]) -> str:
    for key in item:
        if key.lower() in _TEXT_FIELDS:
            detected.append(key)
            value = item[key]
            return str(value).strip() if value is not None else ""
    # No obvious text field: fall back to the longest string value.
    strings = [(k, v) for k, v in item.items() if isinstance(v, str) and v.strip()]
    if strings:
        key, value = max(strings, key=lambda kv: len(kv[1]))
        return value.strip()
    return ""


def _dict_first(item: dict, keys: tuple[str, ...]) -> str | None:
    lower = {k.lower(): k for k in item}
    for key in keys:
        if key in lower and item[lower[key]] not in (None, ""):
            return str(item[lower[key]]).strip()
    return None
