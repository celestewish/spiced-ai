"""Prompt templates for Spiced's AI steps.

The Unity debugging template encodes Spiced's human-centered rules directly in
the system guidance: the assistant explains and suggests, but never claims to
have changed files and never proposes automatic code edits. Parser output is
passed as structured evidence so the model builds on deterministic facts rather
than guessing from raw text.
"""

from __future__ import annotations

from spiced.core.test_result_parser import ParsedTestResults
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


# Rules specific to reviewing test results. Spiced interprets results the
# developer gathered; it never ran the tests itself.
TEST_REVIEW_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Separate the parsed evidence from your own assumptions.",
    "Summarize the main quality risk areas the results point to.",
    "Produce a concrete retest checklist the developer can follow in Unity.",
    "Never claim that you ran these tests — the developer gathered these results.",
    "Never claim you changed, edited, or fixed any files.",
    "Never suggest automatic changes; the developer decides what to change.",
    "If something is unclear, ask for more context instead of pretending certainty.",
    "Recommend asking the developer before running any commands in a future phase.",
)

TEST_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each section short:

Here's what the test results suggest.

Result summary:
- Total detected:
- Passed:
- Failed:
- Skipped or blocked:

Main risks:
- [Risk area and why it matters]

Failures to inspect:
- [Failure name or description]

Retest checklist:
- [Step 1]
- [Step 2]
- [Step 3]

What I would not assume yet:
- [Unclear or missing context]"""


def _format_test_rules() -> str:
    return "\n".join(f"- {rule}" for rule in TEST_REVIEW_RULES)


def _format_parsed_results(results: ParsedTestResults) -> str:
    lines = [
        f"- Detected format: {results.source_format}",
        f"- Parser confidence: {results.confidence}",
        f"- Total detected: {results.total}",
        f"- Passed: {results.passed}",
        f"- Failed: {results.failed}",
        f"- Skipped/blocked: {results.skipped}",
    ]
    if results.failures:
        lines.append("- Failures:")
        lines.extend(f"    • {name}" for name in results.failures)
    else:
        lines.append("- Failures: none identified by the parser")
    return "\n".join(lines)


def build_test_review_prompt(
    results: ParsedTestResults,
    *,
    project_name: str | None = None,
) -> str:
    """Assemble the test-result review prompt from parser output.

    Only the parsed summary and a trimmed excerpt are included — never the full
    output and never any project source files.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    confidence_note = ""
    if results.confidence == "low":
        confidence_note = (
            "\nThe parser is not confident it read these results correctly. Be explicit "
            "about that uncertainty and ask for clearer output if needed.\n"
        )

    return (
        "You are Spiced, a calm QA companion for indie Unity developers. You review test "
        "results the developer already gathered and help them decide what to verify next. "
        "You did not run these tests and you never change their project.\n\n"
        "Follow these rules:\n"
        f"{_format_test_rules()}\n\n"
        f"{project_line}\n{confidence_note}\n"
        "Results parsed by Spiced locally (deterministic, trustworthy):\n"
        f"{_format_parsed_results(results)}\n\n"
        "Relevant result excerpt (already trimmed; do not ask for the full output):\n"
        "```\n"
        f"{results.excerpt}\n"
        "```\n\n"
        f"{TEST_RESPONSE_FORMAT}\n"
    )
