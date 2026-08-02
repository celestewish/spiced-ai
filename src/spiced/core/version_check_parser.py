"""Deterministic scanner for known-deprecated Unity API usage.

Scans pasted/imported C# line by line against the curated rule table in
``deprecated_api_rules``. This runs fully offline and needs no AI provider —
the AI step (when used) only adds narrative framing around these exact,
already-correct hits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spiced.core.deprecated_api_rules import DEPRECATED_API_RULES

MAX_EXCERPT_CHARS = 2000
MAX_HITS = 100


@dataclass
class DeprecatedApiHit:
    line_number: int
    line_text: str
    api_name: str
    replacement: str
    reason: str
    deprecated_in: str


@dataclass
class ParsedVersionCheck:
    hits: list[DeprecatedApiHit] = field(default_factory=list)
    line_count: int = 0
    excerpt: str = ""

    @property
    def has_hits(self) -> bool:
        return bool(self.hits)

    def as_summary_dict(self) -> dict:
        return {
            "line_count": self.line_count,
            "hits": [
                {
                    "line_number": h.line_number,
                    "api_name": h.api_name,
                    "replacement": h.replacement,
                    "reason": h.reason,
                    "deprecated_in": h.deprecated_in,
                }
                for h in self.hits
            ],
        }


def scan_for_deprecated_apis(code_text: str) -> ParsedVersionCheck:
    lines = code_text.splitlines()
    hits: list[DeprecatedApiHit] = []
    for i, line in enumerate(lines, start=1):
        for rule in DEPRECATED_API_RULES:
            if rule.pattern.search(line):
                hits.append(
                    DeprecatedApiHit(
                        line_number=i,
                        line_text=line.strip(),
                        api_name=rule.api_name,
                        replacement=rule.replacement,
                        reason=rule.reason,
                        deprecated_in=rule.deprecated_in,
                    )
                )
                if len(hits) >= MAX_HITS:
                    break
        if len(hits) >= MAX_HITS:
            break

    excerpt = "\n".join(f"L{h.line_number}: {h.line_text}" for h in hits) or code_text.strip()
    if len(excerpt) > MAX_EXCERPT_CHARS:
        excerpt = excerpt[:MAX_EXCERPT_CHARS].rstrip() + "\n… (truncated)"
    return ParsedVersionCheck(hits=hits, line_count=len(lines), excerpt=excerpt)
