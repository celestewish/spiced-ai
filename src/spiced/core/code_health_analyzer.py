"""Deterministic code-health metrics for one pasted/imported C# script.

Scoped deliberately to a single file the developer pastes in — Spiced does not
scan a whole project (see README: no deep static analysis of the whole
project). It's a lightweight, local proxy for "is this file getting tangled,"
not a real complexity analyzer: function boundaries are found with brace
counting, and "complexity" is a count of branching keywords, not a certified
cyclomatic-complexity computation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FUNCTION_START_RE = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*"  # attributes, e.g. [SerializeField]
    r"(?:public|private|protected|internal|static|virtual|override|async|\s)+"
    r"[\w<>\[\],\s]+?\s+(?P<name>\w+)\s*\([^;{]*\)\s*(?:where[^{]*)?\{?\s*$"
)
_BRANCH_KEYWORDS_RE = re.compile(
    r"\b(if|else if|for|foreach|while|switch|case|catch)\b|&&|\|\||\?\s*[^:]+:"
)
_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK)\b", re.IGNORECASE)

LONG_FUNCTION_LINES = 40
DUPLICATE_BLOCK_SIZE = 4


@dataclass
class FunctionMetrics:
    name: str
    start_line: int
    end_line: int

    @property
    def length(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass
class CodeHealthMetrics:
    line_count: int = 0
    functions: list[FunctionMetrics] = field(default_factory=list)
    branch_count: int = 0
    todo_count: int = 0
    duplicate_blocks: int = 0

    @property
    def function_count(self) -> int:
        return len(self.functions)

    @property
    def average_function_length(self) -> float | None:
        if not self.functions:
            return None
        return round(sum(f.length for f in self.functions) / len(self.functions), 1)

    @property
    def longest_functions(self) -> list[FunctionMetrics]:
        return sorted(
            (f for f in self.functions if f.length >= LONG_FUNCTION_LINES),
            key=lambda f: f.length,
            reverse=True,
        )

    def as_summary_dict(self) -> dict:
        return {
            "line_count": self.line_count,
            "function_count": self.function_count,
            "average_function_length": self.average_function_length,
            "longest_functions": [
                {"name": f.name, "start_line": f.start_line, "length": f.length}
                for f in self.longest_functions
            ],
            "branch_count": self.branch_count,
            "todo_count": self.todo_count,
            "duplicate_blocks": self.duplicate_blocks,
        }


def analyze_code_health(code_text: str) -> CodeHealthMetrics:
    lines = code_text.splitlines()
    functions = _find_functions(lines)
    branch_count = sum(len(_BRANCH_KEYWORDS_RE.findall(line)) for line in lines)
    todo_count = sum(len(_TODO_RE.findall(line)) for line in lines)
    duplicate_blocks = _count_duplicate_blocks(lines)
    return CodeHealthMetrics(
        line_count=len(lines),
        functions=functions,
        branch_count=branch_count,
        todo_count=todo_count,
        duplicate_blocks=duplicate_blocks,
    )


def _find_functions(lines: list[str]) -> list[FunctionMetrics]:
    functions: list[FunctionMetrics] = []
    i = 0
    while i < len(lines):
        match = _FUNCTION_START_RE.match(lines[i])
        if match and "(" in lines[i]:
            start = i
            depth = lines[i].count("{") - lines[i].count("}")
            j = i
            if depth <= 0:
                # Opening brace is on a following line; scan forward for it.
                j += 1
                while j < len(lines) and "{" not in lines[j]:
                    j += 1
                if j < len(lines):
                    depth = lines[j].count("{") - lines[j].count("}")
            while depth > 0 and j + 1 < len(lines):
                j += 1
                depth += lines[j].count("{") - lines[j].count("}")
            functions.append(
                FunctionMetrics(name=match.group("name"), start_line=start + 1, end_line=j + 1)
            )
            i = j + 1
        else:
            i += 1
    return functions


def _count_duplicate_blocks(lines: list[str]) -> int:
    normalized = [ln.strip() for ln in lines if ln.strip()]
    if len(normalized) < DUPLICATE_BLOCK_SIZE * 2:
        return 0
    seen: dict[tuple, int] = {}
    for i in range(len(normalized) - DUPLICATE_BLOCK_SIZE + 1):
        block = tuple(normalized[i : i + DUPLICATE_BLOCK_SIZE])
        seen[block] = seen.get(block, 0) + 1
    return sum(1 for count in seen.values() if count > 1)
