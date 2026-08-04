"""Read-only scan of a Unity project's C# scripts, backing Auto-Generated Dev Docs.

``connectors.unity_scan`` already walks ``Assets/`` recursively for the Asset
Optimization Sweep and Code Health's naming/dead-reference checks — this
module reuses its file-listing helper (``iter_assets``) but is otherwise
separate territory: it reads the *contents* of ``.cs`` files rather than
just their names/sizes, so it lives in its own file rather than growing
``unity_scan.py`` past what it's documented to do.

Extraction is deliberately regex-based, not a real C# parser — matching the
plan's own call that this is "sufficient" for turning signatures into a
living plain-language summary. It finds ``class`` declarations and
``public`` method signatures, plus any ``///`` XML doc comment or plain
``//`` comment block immediately preceding a declaration (best-effort intent
signal, not guaranteed accurate for cases like preprocessor directives,
partial classes, or multi-line signatures — see the caveat baked into
``dev_docs``'s AI prompt). Nothing here is ever written back to the project;
every function is a pure read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from spiced.connectors.unity_scan import iter_assets

_CLASS_RE = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*"  # optional attribute(s), e.g. [Serializable]
    r"(?:public|internal|private|protected)?\s*"
    r"(?:static\s+|abstract\s+|sealed\s+|partial\s+)*"
    r"class\s+(\w+)"
)
# A public member with a parameter list — covers ordinary methods and
# constructors alike. Deliberately permissive on the return-type token so
# generics (``List<int>``) and nullable/array types don't break the match.
_METHOD_RE = re.compile(
    r"^\s*public\s+(?:static\s+|virtual\s+|override\s+|abstract\s+|async\s+|sealed\s+)*"
    r"([\w<>\[\],\.\s]+?)\s+(\w+)\s*\(([^)]*)\)"
)
_XML_DOC_RE = re.compile(r"^\s*///\s?(.*)$")
_LINE_COMMENT_RE = re.compile(r"^\s*//\s?(.*)$")


@dataclass(frozen=True)
class ScannedMethod:
    name: str
    signature: str
    doc_comment: str | None = None


@dataclass
class ScannedClass:
    name: str
    file: str  # relative to the project root, forward-slashed
    doc_comment: str | None = None
    methods: list[ScannedMethod] = field(default_factory=list)


@dataclass(frozen=True)
class DevDocsScanResult:
    classes: list[ScannedClass] = field(default_factory=list)
    file_count: int = 0

    @property
    def class_count(self) -> int:
        return len(self.classes)

    @property
    def method_count(self) -> int:
        return sum(len(c.methods) for c in self.classes)

    def as_summary_dict(self) -> dict:
        """The raw scan, saved verbatim as ``dev_docs_snapshots.source_summary_json``."""
        return {
            "file_count": self.file_count,
            "class_count": self.class_count,
            "method_count": self.method_count,
            "classes": [
                {
                    "name": c.name,
                    "file": c.file,
                    "doc_comment": c.doc_comment,
                    "methods": [
                        {"name": m.name, "signature": m.signature, "doc_comment": m.doc_comment}
                        for m in c.methods
                    ],
                }
                for c in self.classes
            ],
        }


def _join_comment(lines: list[str]) -> str | None:
    cleaned = [line for line in lines if line.strip()]
    return "\n".join(cleaned) if cleaned else None


def _scan_file(text: str, rel_path: str) -> list[ScannedClass]:
    classes: list[ScannedClass] = []
    current: ScannedClass | None = None
    comment_buffer: list[str] = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            comment_buffer = []
            continue

        xml_doc_match = _XML_DOC_RE.match(raw_line)
        if xml_doc_match:
            comment_buffer.append(xml_doc_match.group(1).strip())
            continue

        line_comment_match = _LINE_COMMENT_RE.match(raw_line)
        if line_comment_match:
            comment_buffer.append(line_comment_match.group(1).strip())
            continue

        class_match = _CLASS_RE.match(raw_line)
        if class_match:
            current = ScannedClass(
                name=class_match.group(1),
                file=rel_path,
                doc_comment=_join_comment(comment_buffer),
            )
            classes.append(current)
            comment_buffer = []
            continue

        method_match = _METHOD_RE.match(raw_line) if current is not None else None
        if method_match:
            current.methods.append(
                ScannedMethod(
                    name=method_match.group(2),
                    signature=stripped.rstrip("{").strip(),
                    doc_comment=_join_comment(comment_buffer),
                )
            )
            comment_buffer = []
            continue

        # Any other code line breaks the "immediately preceding" chain.
        comment_buffer = []

    return classes


def scan_scripts(project_path: str | Path) -> DevDocsScanResult:
    """Scan every ``.cs`` file under ``Assets/`` for classes/public methods.

    Returns an empty result (never raises) if the project has no ``Assets/``
    folder — callers (``core.dev_docs``) are expected to have already
    validated the project has a connected folder at all.
    """
    root = Path(project_path)
    classes: list[ScannedClass] = []
    file_count = 0
    for asset in iter_assets(root):
        if asset.suffix.lower() != ".cs":
            continue
        try:
            text = asset.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_count += 1
        rel = asset.relative_to(root).as_posix()
        classes.extend(_scan_file(text, rel))
    return DevDocsScanResult(classes=classes, file_count=file_count)
