"""Read-only scan of an Unreal project's C++ headers, backing Auto-Generated
Dev Docs for Unreal projects (Market-Viability Roadmap, Phase 3) -- the
Unreal counterpart to ``connectors.unity_docs_scan``/``connectors.
godot_docs_scan``.

Reuses ``unity_docs_scan``'s ``ScannedClass``/``ScannedMethod``/
``DevDocsScanResult`` dataclasses directly -- the same engine-agnostic shape
every docs-scan connector in this app returns, per that module's own
reasoning. Only the extraction regex is Unreal C++'s own.

**Format verification.** Grounded against two real files fetched from
``life-exe/UnrealTPSGame`` on GitHub: ``TPSCharacter.h`` (a typical
``UCLASS``-annotated Actor subclass) confirmed the idiomatic Unreal
convention this module targets -- a class declared ``UCLASS(...) \\n class
AFoo : public ABase`` with ``GENERATED_BODY()``, members grouped under
explicit ``public:``/``protected:``/``private:`` sections, and Doxygen-style
``/** ... */`` (both single-line and multi-line, with ``@param`` lines)
immediately preceding a declaration; and ``Battery.h`` (a plain,
non-``UObject`` C++ class) confirmed the simpler ``//`` / ``//!``-prefixed
line-comment style also appears in real Unreal codebases and needs support
too, and that a constructor declaration (``Battery(float PercentIn);``)
carries no return-type token before its name the way an ordinary method
does -- handled by ``_CONSTRUCTOR_RE`` as its own case.

**What is NOT independently verified**: this is a regex-based extraction
over C++, the most syntactically complex language any connector in this app
reads -- templates, macros, multi-line signatures, and preprocessor
conditionals can all defeat it. Matches Unity's own documented stance
("sufficient," not a real parser) and Unreal's own header style is more
macro-heavy than C#'s, so this should be read as a best-effort signature
scan, not a guarantee against every real-world header in the wild.

Nothing here is ever written back to the project; every function is a pure
read.
"""

from __future__ import annotations

import re
from pathlib import Path

from spiced.connectors.unity_docs_scan import DevDocsScanResult, ScannedClass, ScannedMethod

# A class declaration, with or without a leading Unreal API export macro
# (ATPS_API, UCLASS-annotated or plain). Deliberately permissive on the base
# class list so multiple inheritance / macro-wrapped base names don't break
# the match.
_CLASS_RE = re.compile(r"^\s*class\s+(?:\w+_API\s+)?(\w+)")
# Explicit access-specifier lines, which every idiomatic Unreal header uses
# rather than relying on the (rarely-intended) C++ default.
_ACCESS_RE = re.compile(r"^\s*(public|protected|private)\s*:\s*$")
# Known Unreal reflection macros -- lines that start with one of these are
# never a method declaration, only ever the macro's own invocation.
_MACRO_PREFIXES = (
    "UCLASS",
    "USTRUCT",
    "UENUM",
    "UPROPERTY",
    "UFUNCTION",
    "GENERATED_BODY",
    "GENERATED_USTRUCT_BODY",
)
_MACRO_LINE_RE = re.compile(r"^\s*(" + "|".join(_MACRO_PREFIXES) + r")\b")
# A constructor: the bare class name immediately followed by its parameter
# list and a terminator -- no return-type token precedes it, unlike every
# other method.
_CONSTRUCTOR_RE = re.compile(r"^\s*(\w+)\s*\(([^)]*)\)\s*(?:=\s*(?:default|delete)\s*)?;\s*$")
# An ordinary method declaration or inline definition: some return-type
# token(s) followed by whitespace, the method name, and a parameter list,
# ending in a declaration terminator or an inline body's opening brace.
_METHOD_RE = re.compile(
    r"^\s*(?:FORCEINLINE\s+|virtual\s+|static\s+|inline\s+|explicit\s+)*"
    r"[\w:<>,\s*&]+?\s+(\w+)\s*\(([^)]*)\)\s*(?:const\s*)?(?:override\s*)?[;{]"
)
_BLOCK_COMMENT_START_RE = re.compile(r"^/\*\*\s*(.*)$")
_BLOCK_COMMENT_END_RE = re.compile(r"^(.*?)\*/\s*$")
_LINE_COMMENT_RE = re.compile(r"^\s*//!?\s?(.*)$")


def _join_comment(lines: list[str]) -> str | None:
    # A same-line "/** text **/" (a doubled closing asterisk, seen in real
    # Unreal headers) leaves one stray leading/trailing "*" once "*/" itself
    # is stripped off by the block-comment-end match -- rstrip as well as
    # lstrip to clean that up, not just the leading "*" every other line
    # (a real multi-line block's own "* text" prefix) needs.
    cleaned = [line.strip().strip("*").strip() for line in lines if line.strip()]
    cleaned = [line for line in cleaned if line]
    return "\n".join(cleaned) if cleaned else None


def _scan_file(text: str, rel_path: str) -> list[ScannedClass]:
    classes: list[ScannedClass] = []
    current: ScannedClass | None = None
    current_access = "private"  # C++'s real default for `class` (not `struct`)
    comment_buffer: list[str] = []
    in_block_comment = False

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if in_block_comment:
            end_match = _BLOCK_COMMENT_END_RE.match(raw_line)
            if end_match:
                if end_match.group(1).strip():
                    comment_buffer.append(end_match.group(1))
                in_block_comment = False
            else:
                comment_buffer.append(raw_line)
            continue

        if not stripped:
            comment_buffer = []
            continue

        start_match = _BLOCK_COMMENT_START_RE.match(stripped)
        if start_match:
            same_line_end = _BLOCK_COMMENT_END_RE.match(start_match.group(1))
            if same_line_end:
                comment_buffer.append(same_line_end.group(1))
            else:
                comment_buffer.append(start_match.group(1))
                in_block_comment = True
            continue

        line_comment_match = _LINE_COMMENT_RE.match(raw_line)
        if line_comment_match:
            comment_buffer.append(line_comment_match.group(1).strip())
            continue

        access_match = _ACCESS_RE.match(raw_line)
        if access_match:
            current_access = access_match.group(1)
            comment_buffer = []
            continue

        if _MACRO_LINE_RE.match(stripped):
            # A reflection macro's own invocation line -- doesn't reset the
            # doc-comment buffer, since the real declaration it documents is
            # usually the next line, not this one.
            continue

        class_match = _CLASS_RE.match(raw_line)
        if class_match:
            current = ScannedClass(
                name=class_match.group(1), file=rel_path, doc_comment=_join_comment(comment_buffer)
            )
            classes.append(current)
            current_access = "private"
            comment_buffer = []
            continue

        if current is not None and current_access == "public":
            constructor_match = _CONSTRUCTOR_RE.match(raw_line)
            if constructor_match and constructor_match.group(1) == current.name:
                current.methods.append(
                    ScannedMethod(
                        name=constructor_match.group(1),
                        signature=stripped,
                        doc_comment=_join_comment(comment_buffer),
                    )
                )
                comment_buffer = []
                continue

            method_match = _METHOD_RE.match(raw_line)
            if method_match:
                current.methods.append(
                    ScannedMethod(
                        name=method_match.group(1),
                        signature=stripped.rstrip("{").strip(),
                        doc_comment=_join_comment(comment_buffer),
                    )
                )
                comment_buffer = []
                continue

        # Any other code line breaks the "immediately preceding" chain.
        comment_buffer = []

    return classes


def scan_headers(project_path: str | Path) -> DevDocsScanResult:
    """Scan every ``.h``/``.hpp`` file under ``Source/`` for class/public
    method signatures. Returns an empty result (never raises) if the
    project has no readable headers -- callers (``core.dev_docs``) are
    expected to have already validated the project has a connected folder
    at all.
    """
    root = Path(project_path)
    source_dir = root / "Source"
    classes: list[ScannedClass] = []
    file_count = 0
    if not source_dir.is_dir():
        return DevDocsScanResult(classes=classes, file_count=file_count)
    for header in sorted(source_dir.rglob("*")):
        if not header.is_file() or header.suffix.lower() not in (".h", ".hpp"):
            continue
        try:
            text = header.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        file_count += 1
        rel = header.relative_to(root).as_posix()
        classes.extend(_scan_file(text, rel))
    return DevDocsScanResult(classes=classes, file_count=file_count)
