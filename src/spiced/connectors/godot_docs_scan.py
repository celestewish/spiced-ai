"""Read-only scan of a Godot project's GDScript files, backing Auto-Generated
Dev Docs for Godot projects (Market-Viability Roadmap, Phase 2) -- the Godot
counterpart to ``connectors.unity_docs_scan``.

Reuses ``unity_docs_scan``'s ``ScannedClass``/``ScannedMethod``/
``DevDocsScanResult`` dataclasses directly rather than defining parallel
Godot-specific ones -- the shape (a class, its doc comment, its public
methods each with their own doc comment) is genuinely engine-agnostic; only
the extraction regex needs to be GDScript's own, per the roadmap's own call
that this "needs its own regex, not a port" of the C# one.

**Format verification.** Grounded against a real, non-trivial GDScript file
(``player.gd`` from the official ``godotengine/godot-demo-projects`` repo,
``2d/dodge_the_creeps``), not assumed from documentation. That sample
confirmed: most gameplay scripts have **no** ``class_name`` line at all (the
file is only ever referenced by path, e.g. as an attached ``Script``
resource) -- this module falls back to the file's stem as the class name in
that case, mirroring how such a script is actually identified everywhere
else in a Godot project; that GDScript uses tab indentation with top-level
``func`` declarations unindented; and that engine-callback methods
(``_ready``, ``_process``, ``_on_body_entered``, ...) are conventionally
prefixed with ``_`` -- treated the same way Unity's scan only extracts
``public`` methods, this module only extracts non-underscore-prefixed
``func`` declarations as a script's "public" surface.

Nothing here is ever written back to the project; every function is a pure
read.
"""

from __future__ import annotations

import re
from pathlib import Path

from spiced.connectors.godot_scan import iter_resources
from spiced.connectors.unity_docs_scan import DevDocsScanResult, ScannedClass, ScannedMethod

_CLASS_NAME_RE = re.compile(r"^class_name\s+(\w+)")
# Top-level (unindented) function declarations only -- GDScript has no
# concept of a "public" keyword, so the leading-underscore convention (engine
# callbacks and script-private helpers) is treated as this scan's equivalent
# of Unity's "public methods only" filter.
_FUNC_RE = re.compile(r"^func\s+([a-zA-Z]\w*)\s*\(([^)]*)\)")
_DOC_COMMENT_RE = re.compile(r"^\s*##\s?(.*)$")
_LINE_COMMENT_RE = re.compile(r"^\s*#\s?(.*)$")


def _join_comment(lines: list[str]) -> str | None:
    cleaned = [line for line in lines if line.strip()]
    return "\n".join(cleaned) if cleaned else None


def _leading_file_doc(lines: list[str]) -> str | None:
    """A comment block at the very top of the file, before any code -- the
    conventional place for a file-header doc comment on a GDScript file that
    has no ``class_name`` line (the common case for a script attached
    directly to a scene node, per ``player.gd``)."""
    buffer: list[str] = []
    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            continue
        doc_match = _DOC_COMMENT_RE.match(raw_line)
        line_match = _LINE_COMMENT_RE.match(raw_line)
        if doc_match:
            buffer.append(doc_match.group(1).strip())
            continue
        if line_match:
            buffer.append(line_match.group(1).strip())
            continue
        break  # first non-comment, non-blank line ends the file header
    return _join_comment(buffer)


def _scan_file(text: str, rel_path: str) -> ScannedClass:
    """One GDScript file is one class -- unlike C#, GDScript files don't
    nest multiple top-level classes, so this returns a single ``ScannedClass``
    rather than a list."""
    lines = text.splitlines()
    stem = Path(rel_path).stem
    scanned = ScannedClass(name=stem, file=rel_path, doc_comment=_leading_file_doc(lines))
    comment_buffer: list[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped:
            comment_buffer = []
            continue

        doc_match = _DOC_COMMENT_RE.match(raw_line)
        if doc_match:
            comment_buffer.append(doc_match.group(1).strip())
            continue
        line_match = _LINE_COMMENT_RE.match(raw_line)
        if line_match:
            comment_buffer.append(line_match.group(1).strip())
            continue

        class_name_match = _CLASS_NAME_RE.match(raw_line)
        if class_name_match:
            scanned.name = class_name_match.group(1)
            # A comment immediately preceding class_name is more specific
            # than the file header and overrides it.
            if comment_buffer:
                scanned.doc_comment = _join_comment(comment_buffer)
            comment_buffer = []
            continue

        func_match = _FUNC_RE.match(raw_line)
        if func_match and not func_match.group(1).startswith("_"):
            scanned.methods.append(
                ScannedMethod(
                    name=func_match.group(1),
                    signature=stripped.rstrip(":").strip(),
                    doc_comment=_join_comment(comment_buffer),
                )
            )
            comment_buffer = []
            continue

        # Any other code line breaks the "immediately preceding" chain.
        comment_buffer = []

    return scanned


def scan_scripts(project_path: str | Path) -> DevDocsScanResult:
    """Scan every ``.gd`` file in the project for its class name (or file
    stem, if it has no ``class_name`` line) and public (non-``_``-prefixed)
    methods.

    Returns an empty result (never raises) if the project has no readable
    ``.gd`` files -- callers (``core.dev_docs``) are expected to have
    already validated the project has a connected folder at all.
    """
    root = Path(project_path)
    classes: list[ScannedClass] = []
    file_count = 0
    for asset in iter_resources(root):
        if asset.suffix.lower() != ".gd":
            continue
        try:
            text = asset.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_count += 1
        rel = asset.relative_to(root).as_posix()
        classes.append(_scan_file(text, rel))
    return DevDocsScanResult(classes=classes, file_count=file_count)
