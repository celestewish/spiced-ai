"""Prompt templates for Spiced's AI steps.

The Unity debugging template encodes Spiced's human-centered rules directly in
the system guidance: the assistant explains and suggests, but never claims to
have changed files and never proposes automatic code edits. Parser output is
passed as structured evidence so the model builds on deterministic facts rather
than guessing from raw text.
"""

from __future__ import annotations

from spiced.core.unity_log_parser import ParsedError, ParsedLog

# Human-control rules. Kept as discrete lines so tests can assert their presence
# and so the voice stays consistent across providers.
HUMAN_CONTROL_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Avoid exaggerated AI-speak and overpromising.",
    "Clearly separate evidence from the log from your own assumptions.",
    "Never claim you changed, edited, or fixed any files — you cannot touch the project.",
    "Never suggest automatic code edits or patches; the developer stays in control.",
    "Give verification steps the developer can check before trying any fix.",
    "Use precise Unity terminology (scenes, prefabs, components, Inspector) when it helps.",
    "If the evidence is incomplete, say what is missing instead of pretending certainty.",
)

RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each section short:

Here's what looks most likely.

Likely issue:
[Plain-language explanation]

Evidence from the log:
- [Exception/error type]
- [File and line if available]
- [Relevant stack trace line]

What to check in Unity:
- [Scene/object/component check]
- [Inspector check]
- [Prefab/reference check]

Safe next steps:
- [Step 1]
- [Step 2]
- [Step 3]

I would not change yet:
- [Risky or premature change]"""


def _format_rules() -> str:
    return "\n".join(f"- {rule}" for rule in HUMAN_CONTROL_RULES)


def _format_error(err: ParsedError) -> str:
    lines = [f"- Type: {err.error_type} ({err.category})"]
    if err.message:
        lines.append(f"  Message: {err.message}")
    if err.script:
        lines.append(f"  Script: {err.script}")
    if err.file:
        lines.append(f"  File: {err.file}")
    if err.line is not None:
        lines.append(f"  Line: {err.line}")
    if err.count > 1:
        lines.append(f"  Repeated: {err.count} times")
    return "\n".join(lines)


def _format_detected_errors(parsed: ParsedLog) -> str:
    if not parsed.has_errors:
        return (
            "The local parser did not recognize a specific Unity error. Work only "
            "from the excerpt below and say clearly if it is not enough to be sure."
        )
    return "\n".join(_format_error(err) for err in parsed.errors)


def build_unity_debug_prompt(
    parsed: ParsedLog,
    *,
    project_name: str | None = None,
    unity_version: str | None = None,
) -> str:
    """Assemble the full Unity debugging prompt from parser output.

    Only the small, relevant excerpt and structured error data are included —
    never the full log and never any project source files.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    version_line = f"Unity version: {unity_version}" if unity_version else "Unity version: unknown"

    return (
        "You are Spiced, a calm debugging companion for indie Unity developers. "
        "You help the developer understand a problem and decide what to do next. "
        "You never take control of their project.\n\n"
        "Follow these rules:\n"
        f"{_format_rules()}\n\n"
        f"{project_line}\n{version_line}\n\n"
        "Errors detected by Spiced's local parser (deterministic, trustworthy):\n"
        f"{_format_detected_errors(parsed)}\n\n"
        "Relevant log excerpt (already trimmed; do not ask for the full log):\n"
        "```\n"
        f"{parsed.excerpt}\n"
        "```\n\n"
        f"{RESPONSE_FORMAT}\n"
    )
