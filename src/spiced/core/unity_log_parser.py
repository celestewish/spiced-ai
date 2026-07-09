"""Deterministic Unity log parser.

Extracts common Unity errors (runtime exceptions and compiler CS errors) from a
pasted or imported log. It groups repeated errors, keeps a small relevant
excerpt, and never sends anything anywhere — it just produces structured data
for the AI step to build on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePath, PurePosixPath, PureWindowsPath

CATEGORY_EXCEPTION = "exception"
CATEGORY_COMPILER = "compiler"

# "NullReferenceException: Object reference not set to an instance of an object"
_EXCEPTION_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z_][A-Za-z0-9_.]*(?:Exception|Error))\s*:\s*(?P<msg>.*)$"
)
# Stack frame location: "(at Assets/Scripts/HealthPickup.cs:24)"
_FRAME_RE = re.compile(r"\(at\s+(?P<path>.+?):(?P<line>\d+)\)")
# Compiler error: "Assets/Scripts/Player.cs(12,20): error CS0103: The name ..."
_COMPILER_RE = re.compile(
    r"(?P<path>[^\s(]+\.cs)\((?P<line>\d+),\d+\):\s*error\s+(?P<code>CS\d+):\s*(?P<msg>.*)"
)

MAX_EXCERPT_CHARS = 2000
MAX_STACK_FRAMES = 6


def _script_from_path(path: str | None) -> str | None:
    if not path:
        return None
    # Handle both Unix- and Windows-style separators regardless of host OS.
    cls: type[PurePath] = PureWindowsPath if "\\" in path else PurePosixPath
    return cls(path).name or None


@dataclass
class ParsedError:
    category: str
    error_type: str
    message: str
    file: str | None = None
    script: str | None = None
    line: int | None = None
    count: int = 1
    stack_excerpt: list[str] = field(default_factory=list)

    @property
    def signature(self) -> tuple:
        return (self.category, self.error_type, self.file, self.line)


@dataclass
class ParsedLog:
    errors: list[ParsedError]
    total_lines: int
    excerpt: str

    @property
    def primary(self) -> ParsedError | None:
        return self.errors[0] if self.errors else None

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


def parse_unity_log(text: str) -> ParsedLog:
    lines = text.splitlines()
    ordered: list[ParsedError] = []
    grouped: dict[tuple, ParsedError] = {}
    current: ParsedError | None = None

    def commit(err: ParsedError) -> None:
        existing = grouped.get(err.signature)
        if existing is None:
            grouped[err.signature] = err
            ordered.append(err)
        else:
            existing.count += 1
            if not existing.stack_excerpt and err.stack_excerpt:
                existing.stack_excerpt = err.stack_excerpt

    for raw in lines:
        line = raw.rstrip()

        compiler = _COMPILER_RE.search(line)
        if compiler:
            if current is not None:
                commit(current)
                current = None
            err = ParsedError(
                category=CATEGORY_COMPILER,
                error_type=compiler.group("code"),
                message=compiler.group("msg").strip(),
                file=compiler.group("path"),
                script=_script_from_path(compiler.group("path")),
                line=int(compiler.group("line")),
                stack_excerpt=[line.strip()],
            )
            commit(err)
            continue

        header = _EXCEPTION_RE.match(line)
        if header:
            if current is not None:
                commit(current)
            current = ParsedError(
                category=CATEGORY_EXCEPTION,
                error_type=header.group("type"),
                message=header.group("msg").strip(),
                stack_excerpt=[line.strip()],
            )
            continue

        frame = _FRAME_RE.search(line)
        if frame and current is not None:
            path = frame.group("path").strip()
            frame_line = int(frame.group("line"))
            if len(current.stack_excerpt) < MAX_STACK_FRAMES:
                current.stack_excerpt.append(line.strip())
            # Prefer the first frame that points at the user's own Assets code.
            prefers_assets = current.file is None or (
                "Assets" in path and "Assets" not in (current.file or "")
            )
            if prefers_assets:
                current.file = path
                current.line = frame_line
                current.script = _script_from_path(path)
            continue

        # A blank line ends the current exception block.
        if not line.strip() and current is not None:
            commit(current)
            current = None

    if current is not None:
        commit(current)

    excerpt = _build_excerpt(ordered)
    return ParsedLog(errors=ordered, total_lines=len(lines), excerpt=excerpt)


def _build_excerpt(errors: list[ParsedError]) -> str:
    """Join the most relevant lines from the top errors, capped in size."""
    parts: list[str] = []
    for err in errors:
        parts.extend(err.stack_excerpt or [f"{err.error_type}: {err.message}"])
    excerpt = "\n".join(parts)
    if len(excerpt) > MAX_EXCERPT_CHARS:
        excerpt = excerpt[:MAX_EXCERPT_CHARS].rstrip() + "\n… (truncated)"
    return excerpt
