"""Prompt templates for Spiced's AI steps.

The Unity debugging template encodes Spiced's human-centered rules directly in
the system guidance: the assistant explains and suggests, but never claims to
have changed files and never proposes automatic code edits. Parser output is
passed as structured evidence so the model builds on deterministic facts rather
than guessing from raw text.
"""

from __future__ import annotations

from spiced.connectors.unity_scan import OversizedAssetFinding
from spiced.core.accessibility_parser import ParsedAccessibility
from spiced.core.code_health_analyzer import LONG_FUNCTION_LINES, CodeHealthMetrics
from spiced.core.community.base import CommunityMessage
from spiced.core.feedback_classifier import FeedbackClassification
from spiced.core.feedback_parser import ParsedFeedback
from spiced.core.hardware_simulation import HardwareSimulationResult
from spiced.core.performance_parser import ParsedPerformance
from spiced.core.test_result_parser import ParsedTestResults
from spiced.core.unity_log_parser import ParsedError, ParsedLog
from spiced.core.version_check_parser import ParsedVersionCheck

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


# --- Small-Team Mode context (Phase B, section 4) ---------------------------
#
# Solo-Dev Mode is the default and stays terse: every builder below keeps its
# original prompt byte-for-byte when ``team_mode`` is left False. When a
# developer opts into Small-Team Mode *and* the active project is linked to a
# team, callers pass ``team_mode=True`` plus a short roster of teammates
# (display names/emails from TeamService.list_members) so the model can add
# routing *suggestions* — never an action Spiced performs itself. See
# app/services.py:team_prompt_context and core/team_service.py.


def _team_context_block(team_mode: bool, team_members: list[str] | None) -> str:
    if not team_mode:
        return ""
    roster = ", ".join(team_members) if team_members else "(no other teammates on this project yet)"
    return (
        "\n\nSmall-Team Mode is on for this project. Team roster (context only): "
        f"{roster}\n"
        "Add one more section after your reply above:\n\n"
        "Suggested routing (Team Mode only):\n"
        "- [Finding] -> possibly a fit for [teammate], because [short reason]\n"
        "- Write \"No specific routing suggestion.\" if nothing clearly maps to a teammate.\n\n"
        "This routing section is only a suggestion in your text reply. Spiced does not assign, "
        "notify, or message anyone automatically — the developer decides whether and how to "
        "route anything."
    )


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
    team_mode: bool = False,
    team_members: list[str] | None = None,
) -> str:
    """Assemble the full Unity debugging prompt from parser output.

    Only the small, relevant excerpt and structured error data are included —
    never the full log and never any project source files. ``team_mode`` /
    ``team_members`` are solo-safe defaults: left off, the prompt is byte-for-
    byte identical to Solo-Dev Mode's original output.
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
        f"{_team_context_block(team_mode, team_members)}"
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
    team_mode: bool = False,
    team_members: list[str] | None = None,
) -> str:
    """Assemble the test-result review prompt from parser output.

    Only the parsed summary and a trimmed excerpt are included — never the full
    output and never any project source files. ``team_mode`` / ``team_members``
    are solo-safe defaults: left off, the prompt is byte-for-byte identical to
    Solo-Dev Mode's original output.
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
        f"{_team_context_block(team_mode, team_members)}"
    )


# Rules specific to reviewing player feedback. Spiced organizes what players said
# and helps the developer decide — it never decides the game's design itself.
FEEDBACK_REVIEW_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Avoid exaggerated AI-speak and overpromising.",
    "Separate evidence from the feedback from your own assumptions.",
    "Separate likely bugs and technical issues from subjective design preferences.",
    "Do not treat all player feedback as objectively correct — players report experience, "
    "not decisions.",
    "Identify both player pain points and positive signals.",
    "Produce prioritized action items and explain why each one matters.",
    "If the sample is small or mixed, say so instead of overclaiming a trend.",
    "Never claim you changed the game, its design, or any files.",
    "Leave the final design judgment with the developer — you suggest, they decide.",
)

FEEDBACK_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each section short:

Here's what players seem to be telling you.

Overall read:
[Short summary with a sample-size caution if the batch is small or mixed]

Recurring themes:
- [Theme and supporting evidence]

Potential bugs or technical issues:
- [Issue and why it may be technical]

Confusion points:
- [Where players seem stuck or unclear]

Positive signals:
- [What players liked or responded to]

Design preferences:
- [Subjective feedback that needs developer judgment]

Prioritized next actions:
- [Action, reason, and suggested priority]

What I would not assume yet:
- [Where the feedback is too thin, mixed, or subjective]"""


def _format_feedback_rules() -> str:
    return "\n".join(f"- {rule}" for rule in FEEDBACK_REVIEW_RULES)


def _format_feedback_evidence(
    parsed: ParsedFeedback, classification: FeedbackClassification
) -> str:
    lines = [
        f"- Detected format: {parsed.source_format}",
        f"- Parser confidence: {parsed.confidence}",
        f"- Entry count: {parsed.entry_count}",
    ]
    if parsed.detected_fields:
        lines.append(f"- Detected fields: {', '.join(parsed.detected_fields)}")
    if classification.counts:
        lines.append("- Local category counts (heuristic, not final):")
        for category, count in sorted(
            classification.counts.items(), key=lambda kv: kv[1], reverse=True
        ):
            lines.append(f"    • {category}: {count}")
    else:
        lines.append("- Local category counts: none detected")
    return "\n".join(lines)


def build_feedback_review_prompt(
    parsed: ParsedFeedback,
    classification: FeedbackClassification,
    *,
    project_name: str | None = None,
    source_label: str | None = None,
    team_mode: bool = False,
    team_members: list[str] | None = None,
) -> str:
    """Assemble the feedback-review prompt from parser + classifier output.

    Only the parsed summary, local category counts, and a trimmed excerpt are
    included — never full feedback files and never any project source files.
    ``team_mode`` / ``team_members`` are solo-safe defaults: left off, the
    prompt is byte-for-byte identical to Solo-Dev Mode's original output.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    source_line = (
        f"Feedback source: {source_label}" if source_label else "Feedback source: (unlabeled)"
    )
    confidence_note = ""
    if parsed.confidence == "low" or parsed.entry_count <= 2:
        confidence_note = (
            "\nThe sample looks small or hard to parse. Be explicit that conclusions are "
            "tentative and avoid overclaiming trends.\n"
        )

    return (
        "You are Spiced, a calm companion for indie game developers reviewing player "
        "feedback. You organize what players said and help the developer decide what to do "
        "next. You never decide the game's design for them and you never change their "
        "project.\n\n"
        "Follow these rules:\n"
        f"{_format_feedback_rules()}\n\n"
        f"{project_line}\n{source_line}\n{confidence_note}\n"
        "Feedback parsed by Spiced locally (deterministic, trustworthy):\n"
        f"{_format_feedback_evidence(parsed, classification)}\n\n"
        "Relevant feedback excerpt (already trimmed; do not ask for the full file):\n"
        "```\n"
        f"{parsed.excerpt}\n"
        "```\n\n"
        f"{FEEDBACK_RESPONSE_FORMAT}\n"
        f"{_team_context_block(team_mode, team_members)}"
    )


# Rules specific to interpreting performance/profiling numbers. Spiced never
# profiles the build itself — the developer already gathered these numbers.
PERFORMANCE_REVIEW_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Separate the parsed evidence from your own assumptions.",
    "For each flagged spike, suggest plausible, common causes tied to its location — but "
    "label them as likely guesses, not confirmed diagnoses.",
    "Never claim you ran a profiler — the developer gathered these numbers.",
    "Never claim you changed, edited, or fixed any files.",
    "Never suggest automatic changes; the developer decides what to change.",
    "If a target-hardware simulation is included, repeat its caveat: it is an estimate from "
    "measured numbers, not a real device test.",
    "If something is unclear or the sample is small, say so instead of overclaiming.",
)

PERFORMANCE_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each section short:

Here's what the performance numbers suggest.

Result summary:
- Samples read:
- Average fps:
- Peak memory:
- Longest load time:

Spikes worth a look:
- [Location, metric, and a plain-language plausible cause]

Target-hardware notes:
- [Only if a simulation was included; otherwise write "No hardware simulation requested."]

Suggested checks:
- [Step 1]
- [Step 2]

What I would not assume yet:
- [Unclear or missing context]"""


def _format_performance_rules() -> str:
    return "\n".join(f"- {rule}" for rule in PERFORMANCE_REVIEW_RULES)


def _format_parsed_performance(parsed: ParsedPerformance) -> str:
    lines = [
        f"- Detected format: {parsed.source_format}",
        f"- Parser confidence: {parsed.confidence}",
        f"- Samples: {parsed.sample_count}",
        f"- Average fps: {parsed.avg_fps if parsed.avg_fps is not None else 'n/a'}",
        f"- Minimum fps: {parsed.min_fps if parsed.min_fps is not None else 'n/a'}",
        f"- Peak memory (MB): "
        f"{parsed.peak_memory_mb if parsed.peak_memory_mb is not None else 'n/a'}",
        f"- Longest load time (s): "
        f"{parsed.max_load_time_s if parsed.max_load_time_s is not None else 'n/a'}",
    ]
    if parsed.spikes:
        lines.append("- Spikes detected by the local parser:")
        lines.extend(f"    • {spike.message} ({spike.severity})" for spike in parsed.spikes)
    else:
        lines.append("- Spikes: none identified by the parser")
    return "\n".join(lines)


def _format_hardware_simulation(simulation: HardwareSimulationResult | None) -> str:
    if simulation is None:
        return "No hardware simulation requested for this pass."
    lines = [
        f"- Target tier: {simulation.tier}",
        f"- Playable-fps threshold used: {simulation.playable_fps}",
        f"- Caveat: {simulation.caveat}",
    ]
    if simulation.at_risk_samples:
        lines.append("- Locations estimated below the playable threshold:")
        lines.extend(
            f"    • {s.location}: measured {s.measured_fps:g}fps -> "
            f"estimated {s.estimated_fps:g}fps"
            for s in simulation.at_risk_samples
        )
    else:
        lines.append("- No locations estimated below the playable threshold.")
    return "\n".join(lines)


def build_performance_review_prompt(
    parsed: ParsedPerformance,
    *,
    project_name: str | None = None,
    simulation: HardwareSimulationResult | None = None,
) -> str:
    """Assemble the performance-review prompt from parser (+ optional simulation) output.

    Only the parsed summary and a trimmed excerpt are included — never the full
    profiler export and never any project source files.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"

    return (
        "You are Spiced, a calm performance-QA companion for indie Unity developers. You "
        "interpret performance numbers the developer already gathered. You did not run any "
        "profiler and you never change their project.\n\n"
        "Follow these rules:\n"
        f"{_format_performance_rules()}\n\n"
        f"{project_line}\n\n"
        "Numbers parsed by Spiced locally (deterministic, trustworthy):\n"
        f"{_format_parsed_performance(parsed)}\n\n"
        "Target-hardware simulation (deterministic estimate, not a real device test):\n"
        f"{_format_hardware_simulation(simulation)}\n\n"
        "Relevant excerpt (already trimmed; do not ask for the full export):\n"
        "```\n"
        f"{parsed.excerpt}\n"
        "```\n\n"
        f"{PERFORMANCE_RESPONSE_FORMAT}\n"
    )


# Rules specific to the accessibility checklist. The checklist itself (contrast
# ratios, colorblind simulation, caption coverage) is computed deterministically;
# the AI only turns it into a scored, plain-language write-up with fixes.
ACCESSIBILITY_REVIEW_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Treat the checklist results as ground truth; do not recompute or second-guess the numbers.",
    "For each failing or warned check, give a specific, concrete fix, not a vague suggestion.",
    "Frame this as a prioritized checklist, never a shaming score.",
    "Never claim you changed, edited, or fixed any files.",
    "If a section has no data (e.g. no audio files listed), say it wasn't checked rather than "
    "assuming it passed.",
)

ACCESSIBILITY_RESPONSE_FORMAT = (
    """Structure your reply exactly like this, keeping each section short:

Here's the accessibility pass.

Overall score: [n/100, or "not enough data" if nothing was checked]

Contrast:
- [Each failing element and a specific fix]

Colorblind safety:
- [Each element that becomes hard to read under simulation, and a fix]

Captions:
- [Coverage and what's missing]

Controls & text scaling:
- [Status and what to add if unsupported]

Priority fixes:
- [Step 1]
- [Step 2]"""
)


def _format_accessibility_rules() -> str:
    return "\n".join(f"- {rule}" for rule in ACCESSIBILITY_REVIEW_RULES)


def _format_accessibility_checklist(parsed: ParsedAccessibility) -> str:
    if parsed.source_format != "json" or not (
        parsed.contrast_checks or parsed.caption_total or parsed.controls_remappable is not None
        or parsed.text_scaling_supported is not None
    ):
        return "No structured checklist data was provided — only a free-text excerpt below."

    lines = [f"- Overall score: {parsed.score if parsed.score is not None else 'n/a'}"]
    if parsed.contrast_checks:
        lines.append("- Contrast checks:")
        for c in parsed.contrast_checks:
            cb = f", colorblind-safe: {c.colorblind_safe}" if c.colorblind_safe is not None else ""
            lines.append(f"    • {c.name}: {c.ratio:.2f}:1 ({'pass' if c.passes else 'fail'}){cb}")
    if parsed.caption_total:
        lines.append(
            f"- Caption coverage: {parsed.caption_covered}/{parsed.caption_total} "
            f"({parsed.caption_coverage_pct}%)"
        )
    if parsed.controls_remappable is not None:
        lines.append(f"- Controls remappable: {parsed.controls_remappable}")
    if parsed.text_scaling_supported is not None:
        lines.append(f"- Text scaling supported: {parsed.text_scaling_supported}")
    if parsed.findings:
        lines.append("- Findings:")
        lines.extend(f"    • [{f.severity}] {f.message}" for f in parsed.findings)
    return "\n".join(lines)


def build_accessibility_review_prompt(
    parsed: ParsedAccessibility, *, project_name: str | None = None
) -> str:
    """Assemble the accessibility-review prompt from the deterministic checklist.

    Only the computed checklist and a trimmed excerpt are included — never any
    project source files or full asset lists.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    return (
        "You are Spiced, a calm accessibility-QA companion for indie Unity developers. You "
        "turn a deterministic accessibility checklist into a scored, actionable write-up. You "
        "never change their project.\n\n"
        "Follow these rules:\n"
        f"{_format_accessibility_rules()}\n\n"
        f"{project_line}\n\n"
        "Checklist computed by Spiced locally (deterministic, trustworthy — WCAG contrast math "
        "and a standard colorblind-simulation matrix):\n"
        f"{_format_accessibility_checklist(parsed)}\n\n"
        "Relevant excerpt (already trimmed):\n"
        "```\n"
        f"{parsed.excerpt}\n"
        "```\n\n"
        f"{ACCESSIBILITY_RESPONSE_FORMAT}\n"
    )


# Rules specific to Version-Aware Suggestions. The deprecated-API hits are
# already deterministic and correct (from a curated rule table); the AI only
# adds narrative framing and a one-line rationale per hit.
VERSION_CHECK_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Treat each detected hit as ground truth; do not invent additional deprecated APIs beyond "
    "what was detected.",
    "For each hit, give a short, concrete rationale for switching, using the reason provided.",
    "Never claim you changed, edited, or fixed any files.",
    "Never suggest automatic code edits; the developer applies changes themselves.",
    "If no hits were found, say so plainly rather than inventing a concern.",
    "Make clear this list is a curated, known-deprecations check, not a full API audit.",
)

VERSION_CHECK_RESPONSE_FORMAT = (
    """Structure your reply exactly like this, keeping each section short:

Here's the outdated-API review.

Findings:
- [Line, old API, replacement, and a one-line rationale — one bullet per hit]

If clean:
[Only if no hits: a short, honest note that none of Spiced's known deprecations were found]

What this does not cover:
[A short reminder that this checks a curated list, not the full Unity API surface]"""
)


def _format_version_check_rules() -> str:
    return "\n".join(f"- {rule}" for rule in VERSION_CHECK_RULES)


def _format_version_check_hits(parsed: ParsedVersionCheck) -> str:
    if not parsed.hits:
        return "No known-deprecated API calls were detected by the local scanner."
    lines = [f"- {len(parsed.hits)} hit(s) detected by the local scanner:"]
    for hit in parsed.hits:
        lines.append(
            f"    • Line {hit.line_number}: {hit.api_name} -> {hit.replacement} "
            f"(deprecated in {hit.deprecated_in}). Reason: {hit.reason}"
        )
    return "\n".join(lines)


def build_version_check_prompt(
    parsed: ParsedVersionCheck, *, project_name: str | None = None
) -> str:
    """Assemble the version-check prompt from the deterministic scan.

    Only the detected hits and a trimmed excerpt are included — never the full
    pasted script.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    return (
        "You are Spiced, a calm companion helping an indie Unity developer stay current on "
        "engine API changes. You never change their project.\n\n"
        "Follow these rules:\n"
        f"{_format_version_check_rules()}\n\n"
        f"{project_line}\n\n"
        "Deprecated-API hits detected by Spiced locally (deterministic, trustworthy):\n"
        f"{_format_version_check_hits(parsed)}\n\n"
        "Relevant excerpt (already trimmed; do not ask for the full script):\n"
        "```\n"
        f"{parsed.excerpt}\n"
        "```\n\n"
        f"{VERSION_CHECK_RESPONSE_FORMAT}\n"
    )


# Rules specific to the Code Health Dashboard. Framed as prioritized
# suggestions, never a score that shames the developer.
CODE_HEALTH_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Be non-judgmental: this is a heads-up, not a grade. Never shame the developer's code.",
    "Treat the computed metrics as ground truth; do not recompute or second-guess the numbers.",
    "Frame findings as prioritized, optional suggestions the developer can act on later.",
    "Be explicit that this only reflects the one file pasted in, not the whole project.",
    "Never claim you changed, edited, or fixed any files.",
    "Never suggest automatic refactors; the developer decides what to change.",
)

CODE_HEALTH_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each section short:

Here's a quick code-health read on this file.

Overview:
- Lines: / Functions: / Average function length:

Worth a look (not urgent):
- [Longest functions, duplicate blocks, or heavy branching — plain language, one bullet each]

Housekeeping:
- [TODO/FIXME count and whether it's worth a pass]

Not covered:
[A short reminder this only reflects this one file, not the whole project]"""


def _format_code_health_rules() -> str:
    return "\n".join(f"- {rule}" for rule in CODE_HEALTH_RULES)


def _format_code_health_metrics(metrics: CodeHealthMetrics) -> str:
    avg_length = metrics.average_function_length
    avg_length_text = avg_length if avg_length is not None else "n/a"
    lines = [
        f"- Lines: {metrics.line_count}",
        f"- Functions: {metrics.function_count}",
        f"- Average function length: {avg_length_text}",
        f"- Branching/condition count (rough complexity proxy): {metrics.branch_count}",
        f"- TODO/FIXME/HACK markers: {metrics.todo_count}",
        f"- Repeated 4+ line blocks: {metrics.duplicate_blocks}",
    ]
    if metrics.longest_functions:
        lines.append(f"- Functions at or over {LONG_FUNCTION_LINES} lines:")
        lines.extend(
            f"    • {f.name} (line {f.start_line}, {f.length} lines)"
            for f in metrics.longest_functions
        )
    return "\n".join(lines)


def build_code_health_prompt(
    metrics: CodeHealthMetrics, *, excerpt: str, project_name: str | None = None
) -> str:
    """Assemble the code-health prompt from deterministic metrics.

    Only the computed metrics and a trimmed excerpt are included — never the
    full pasted file.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    return (
        "You are Spiced, a calm companion giving an indie developer a non-judgmental read on "
        "one file's code health. You never change their project.\n\n"
        "Follow these rules:\n"
        f"{_format_code_health_rules()}\n\n"
        f"{project_line}\n\n"
        "Metrics computed by Spiced locally (deterministic, trustworthy):\n"
        f"{_format_code_health_metrics(metrics)}\n\n"
        "Relevant excerpt (already trimmed; do not ask for the full file):\n"
        "```\n"
        f"{excerpt}\n"
        "```\n\n"
        f"{CODE_HEALTH_RESPONSE_FORMAT}\n"
    )


# Rules specific to Community Pulse Check-ins. This is a light, high-level
# temperature check — not a replacement for the full Feedback Review flow.
COMMUNITY_PULSE_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "This is a periodic, high-level sentiment check-in, not a deep feedback analysis.",
    "Be explicit about exactly what was read (the channel) and how many messages.",
    "Separate general sentiment from anything that sounds like a concrete bug report.",
    "Do not treat any message as objectively correct — this is informal chatter, not a survey.",
    "Never claim you posted, reacted, or wrote anything back to the community.",
    "Never claim you changed the game, its design, or any files.",
    "If the sample is small, say so instead of overclaiming a trend.",
)

COMMUNITY_PULSE_RESPONSE_FORMAT = (
    """Structure your reply exactly like this, keeping each section short:

Here's this community pulse check-in.

What was read:
[Channel and message count]

Overall vibe:
[Short, honest read — with a sample-size caution if the batch is small]

Recurring notes:
- [Theme and supporting evidence]

Anything that sounds like a bug:
- [Only if something concrete came up; otherwise "Nothing that reads as a concrete bug."]

What I would not assume yet:
- [Where this is too thin or informal to be a real trend]"""
)


def _format_community_pulse_rules() -> str:
    return "\n".join(f"- {rule}" for rule in COMMUNITY_PULSE_RULES)


def _format_community_messages(messages: list[CommunityMessage]) -> str:
    if not messages:
        return "No messages were read."
    lines = []
    for msg in messages:
        text = msg.text.strip().replace("\n", " ")
        if len(text) > 200:
            text = text[:197] + "..."
        lines.append(f"- {msg.author}: {text}")
    return "\n".join(lines)


# Rules specific to Session Summaries (Phase B, section 4). Spiced only
# recaps evidence it was handed from local repositories — it never claims to
# have tested or fixed anything itself.
SESSION_SUMMARY_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Base the recap strictly on the tested/fixed/open evidence given; never invent items.",
    "Never claim you tested, fixed, or changed anything yourself — the developer and their "
    "tools did the work; you are only recapping it.",
    "Keep it short — a devlog-style recap, not a full report.",
    "If a category (tested/fixed/open) has nothing in it, say so plainly rather than padding.",
    "If the window covers very little activity, say that honestly instead of inflating it.",
)

SESSION_SUMMARY_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each \
section short:

Session recap.

Tested:
- [item, or "Nothing tested and recorded in this window."]

Fixed:
- [item, or "Nothing marked fixed in this window."]

Still open:
- [item, or "Nothing open right now."]

One-line summary:
[a single short sentence suitable for a devlog entry]"""


def _format_session_summary_rules() -> str:
    return "\n".join(f"- {rule}" for rule in SESSION_SUMMARY_RULES)


def _format_session_bullets(label: str, items: list[str]) -> str:
    if not items:
        return f"- {label}: none recorded"
    lines = [f"- {label}:"]
    lines.extend(f"    • {item}" for item in items)
    return "\n".join(lines)


def build_session_summary_prompt(
    *,
    since: str,
    tested: list[str],
    fixed: list[str],
    open_items: list[str],
    project_name: str | None = None,
    team_mode: bool = False,
    team_members: list[str] | None = None,
) -> str:
    """Assemble the session-summary prompt from locally-gathered evidence.

    ``tested``/``fixed``/``open_items`` are short plain-text lines already
    pulled from local repositories (test runs/cases, known issues, feedback
    tasks) by ``core.session_summary`` — never raw logs or feedback text.
    ``team_mode`` / ``team_members`` are solo-safe defaults: left off, the
    prompt is byte-for-byte identical to Solo-Dev Mode's output.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"

    return (
        "You are Spiced, a calm companion recapping an indie developer's work session. You "
        "turn already-gathered local evidence into a short devlog-style summary. You never "
        "claim to have done the work yourself and you never change their project.\n\n"
        "Follow these rules:\n"
        f"{_format_session_summary_rules()}\n\n"
        f"{project_line}\n"
        f"Window: since {since}\n\n"
        "Evidence gathered by Spiced locally (deterministic, trustworthy):\n"
        f"{_format_session_bullets('Tested', tested)}\n"
        f"{_format_session_bullets('Fixed', fixed)}\n"
        f"{_format_session_bullets('Still open', open_items)}\n\n"
        f"{SESSION_SUMMARY_RESPONSE_FORMAT}\n"
        f"{_team_context_block(team_mode, team_members)}"
    )


def build_community_pulse_prompt(
    messages: list[CommunityMessage],
    *,
    channel_label: str,
    project_name: str | None = None,
) -> str:
    """Assemble the community-pulse prompt from recently read messages.

    Only a trimmed, per-message excerpt is included — never the full channel
    history and never anything from DMs (sources only read one public channel).
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    return (
        "You are Spiced, a calm companion giving an indie developer a light community-sentiment "
        "check-in. You never post or react anywhere and you never change their project.\n\n"
        "Follow these rules:\n"
        f"{_format_community_pulse_rules()}\n\n"
        f"{project_line}\n"
        f"Channel read: {channel_label}\n"
        f"Messages read: {len(messages)}\n\n"
        "Messages (already trimmed):\n"
        f"{_format_community_messages(messages)}\n\n"
        f"{COMMUNITY_PULSE_RESPONSE_FORMAT}\n"
    )


# Rules specific to Changelog Generation (Phase D, section 6). Spiced drafts
# patch notes from the developer's own git history + locally-resolved known
# issues; it never publishes anything and the developer reviews/edits first.
CHANGELOG_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Base the draft strictly on the commit messages and resolved-issue titles given; never "
    "invent changes that aren't reflected in that evidence.",
    "Group related commits into short, player-facing bullet points rather than listing every "
    "commit verbatim — commit messages are for developers, patch notes are for players.",
    "Skip purely internal commits (formatting, dependency bumps, CI/build tooling) unless "
    "nothing else is available.",
    "Never claim you tested, verified, or shipped anything — you are only drafting notes from "
    "history the developer already has.",
    "Never claim you published, posted, or released this anywhere.",
    "If the commit history is thin, vague, or hard to turn into player-facing notes, say so "
    "plainly rather than padding with generic phrasing.",
)

CHANGELOG_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each section short:

Here's a draft changelog from your recent history.

Highlights:
- [Player-facing bullet, grouped from related commits]

Fixes:
- [Player-facing bullet for bug fixes, drawing on resolved known issues where relevant]

Other changes:
- [Anything notable that isn't a highlight or fix]

What I would double-check:
- [Anything in the commit history that was too vague to turn into a confident bullet]"""


def _format_changelog_rules() -> str:
    return "\n".join(f"- {rule}" for rule in CHANGELOG_RULES)


def build_changelog_prompt(
    *,
    git_log_excerpt: str,
    commit_range: str,
    resolved_issue_titles: list[str],
    project_name: str | None = None,
) -> str:
    """Assemble the changelog-draft prompt from the game project's own git log.

    Only a trimmed, already-local ``git log`` excerpt and known-issue titles
    are included — never source diffs or file contents, and never anything
    from Spiced's own repository.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    issues_block = (
        "\n".join(f"- {title}" for title in resolved_issue_titles)
        if resolved_issue_titles
        else "- (none resolved in this window)"
    )
    log_block = git_log_excerpt.strip() or "(no commits found in this window)"

    return (
        "You are Spiced, a calm companion drafting patch notes for an indie Unity developer "
        "from their own game project's git history. The developer reviews and edits this draft "
        "before using it anywhere — you never publish anything.\n\n"
        "Follow these rules:\n"
        f"{_format_changelog_rules()}\n\n"
        f"{project_line}\n"
        f"Commit range: {commit_range}\n\n"
        "Git log read locally from the game project (one-line-per-commit, oldest rules may "
        "still apply — do not ask for the full diff):\n"
        "```\n"
        f"{log_block}\n"
        "```\n\n"
        "Known issues Spiced has tracked as resolved in this window (deterministic, local):\n"
        f"{issues_block}\n\n"
        f"{CHANGELOG_RESPONSE_FORMAT}\n"
    )


# Rules specific to the Asset Optimization Sweep (Phase D). The findings are
# already deterministic (a local file-size/extension scan and a GUID
# cross-reference); the AI only turns them into a plain-language, prioritized
# summary. Spiced never resizes, recompresses, or deletes anything itself.
ASSET_SCAN_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Treat the scan findings as ground truth; do not recompute or second-guess the numbers.",
    "Frame findings as prioritized, optional suggestions — never claim you changed, "
    "recompressed, resized, or deleted anything, because you did not and cannot.",
    "For orphaned/unused assets, repeat the caveat that this is a best-effort signal: an asset "
    "loaded dynamically (Resources.Load, Addressables) or from a package would not be detected.",
    "If a category (oversized files, orphaned assets) has nothing in it, say so plainly rather "
    "than padding.",
)

ASSET_SCAN_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping each section \
short:

Here's the asset sweep.

Oversized or uncompressed files:
- [File, size, and a plain-language suggestion — or "None found." if the list is empty]

Possibly orphaned assets:
- [File — or "None found." if the list is empty]

What this does not know:
[A short, honest reminder that "orphaned" is best-effort, not certainty]

Suggested next steps:
- [Step 1]
- [Step 2]"""


def _format_asset_scan_rules() -> str:
    return "\n".join(f"- {rule}" for rule in ASSET_SCAN_RULES)


def _format_oversized_findings(findings: list[OversizedAssetFinding]) -> str:
    if not findings:
        return "- None found by the local scan."
    lines = []
    for f in findings[:20]:
        mb = f.size_bytes / (1024 * 1024)
        lines.append(f"- [{f.kind}] {f.path} ({mb:.1f} MB): {f.reason}")
    if len(findings) > 20:
        lines.append(f"- ...and {len(findings) - 20} more (showing the largest 20).")
    return "\n".join(lines)


def _format_orphaned_assets(paths: list[str]) -> str:
    if not paths:
        return "- None found by the local scan."
    return "\n".join(f"- {p}" for p in paths)


def build_asset_scan_prompt(
    oversized: list[OversizedAssetFinding],
    orphaned_assets: list[str],
    *,
    orphan_caveat: str,
    project_name: str | None = None,
) -> str:
    """Assemble the asset-sweep prompt from the deterministic local scan.

    Only file paths, sizes, and short reasons are included — never file
    contents, and Spiced never reads anything outside the project's own
    ``Assets/`` folder.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    return (
        "You are Spiced, a calm companion giving an indie Unity developer a read-only asset "
        "health sweep. You never modify, recompress, resize, or delete anything.\n\n"
        "Follow these rules:\n"
        f"{_format_asset_scan_rules()}\n\n"
        f"{project_line}\n\n"
        "Oversized/uncompressed-format findings from the local scan (deterministic, trustworthy):\n"
        f"{_format_oversized_findings(oversized)}\n\n"
        "Possibly-orphaned assets from the local scan "
        f"({orphan_caveat}):\n"
        f"{_format_orphaned_assets(orphaned_assets)}\n\n"
        f"{ASSET_SCAN_RESPONSE_FORMAT}\n"
    )


# Rules specific to the Store Page / Build Checklist's optional AI commentary
# (Phase D). The checklist items are a small, deterministic, static dataset;
# the AI only adds a brief, honest narrative gloss on top.
RELEASE_CHECKLIST_RULES: tuple[str, ...] = (
    "Respond in English unless the developer asks for another language.",
    "Speak like a calm, professional companion — a helpful teammate, not a hype machine.",
    "Treat the checklist items as ground truth; do not invent additional platform-specific "
    "numeric limits Spiced hasn't already listed.",
    "Explicitly repeat that platform requirements can change, and the developer should verify "
    "current specifics against the platform's own docs before shipping.",
    "Never claim you changed, submitted, or published anything on the developer's behalf.",
    "Keep this brief — this is a gloss on an already-complete checklist, not a new one.",
)

RELEASE_CHECKLIST_RESPONSE_FORMAT = """Structure your reply exactly like this, keeping it short:

Here's a quick read on your {platform} checklist.

Worth prioritizing first:
- [1-3 items from the checklist that matter most to tackle early, and why]

Easy to overlook:
- [1-2 items developers commonly forget, if any stand out from the list]

Reminder:
[A short, honest note that platform specifics change — verify against current docs]"""


def _format_release_checklist_rules() -> str:
    return "\n".join(f"- {rule}" for rule in RELEASE_CHECKLIST_RULES)


def build_release_checklist_prompt(checklist, *, project_name: str | None = None) -> str:
    """Assemble the optional AI-commentary prompt for a ``ReleaseChecklist``.

    The checklist itself (``core.release_checklist.build_checklist``) is a
    small, deterministic, static dataset that works with no provider at all
    — this prompt only adds a brief narrative gloss on top of it.
    """
    project_line = f"Project: {project_name}" if project_name else "Project: (unnamed)"
    items_block = "\n".join(f"- {item.text}" for item in checklist.items)
    return (
        "You are Spiced, a calm companion helping an indie Unity developer think through a "
        f"{checklist.platform_label} release checklist. You never submit or publish anything "
        "yourself.\n\n"
        "Follow these rules:\n"
        f"{_format_release_checklist_rules()}\n\n"
        f"{project_line}\n"
        f"Platform: {checklist.platform_label}\n\n"
        "Checklist items (deterministic, static — Spiced computed these locally, not the AI):\n"
        f"{items_block}\n\n"
        f"{RELEASE_CHECKLIST_RESPONSE_FORMAT.format(platform=checklist.platform_label)}\n"
    )
