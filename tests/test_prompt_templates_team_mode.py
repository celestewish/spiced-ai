"""Team Mode extensions to the prompt builders (Phase B, section 4).

Asserts two things for each extended builder: (1) the default/solo-mode
output is unchanged from before these params existed, and (2) team_mode=True
adds a routing-suggestion section that is explicit about being a suggestion
only, never an action Spiced performs.
"""

from __future__ import annotations

from spiced.ai.prompt_templates import (
    build_feedback_review_prompt,
    build_session_summary_prompt,
    build_test_review_prompt,
    build_unity_debug_prompt,
)
from spiced.core.feedback_classifier import classify
from spiced.core.feedback_parser import parse_feedback
from spiced.core.test_result_parser import parse_test_results
from spiced.core.unity_log_parser import parse_unity_log

NULL_REF_LOG = (
    "NullReferenceException: Object reference not set to an instance of an object\n"
    "HealthPickup.OnTriggerEnter2D (UnityEngine.Collider2D other) "
    "(at Assets/Scripts/HealthPickup.cs:24)\n"
)

FEEDBACK_TEXT = (
    "The dash and movement feel amazing.\n"
    "The pause menu is broken, it froze the game.\n"
    "I fell through the platform near the start.\n"
)

TEST_RESULTS_TEXT = "PASS: Movement\nFAIL: Save/Load corrupts on quit\n"


def _assert_no_team_content(prompt: str) -> None:
    assert "Small-Team Mode is on" not in prompt
    assert "Suggested routing" not in prompt


def _assert_team_content(prompt: str, team_members: list[str]) -> None:
    assert "Small-Team Mode is on for this project." in prompt
    assert "Suggested routing (Team Mode only):" in prompt
    assert "Spiced does not assign, notify, or message anyone automatically" in prompt
    for member in team_members:
        assert member in prompt


# --- build_unity_debug_prompt -------------------------------------------------


def test_debug_prompt_default_omits_team_content():
    parsed = parse_unity_log(NULL_REF_LOG)
    solo = build_unity_debug_prompt(parsed, project_name="Moonlit Depths")
    _assert_no_team_content(solo)


def test_debug_prompt_default_matches_explicit_solo_call():
    parsed = parse_unity_log(NULL_REF_LOG)
    default = build_unity_debug_prompt(parsed, project_name="Moonlit Depths")
    explicit = build_unity_debug_prompt(
        parsed, project_name="Moonlit Depths", team_mode=False, team_members=None
    )
    assert default == explicit


def test_debug_prompt_team_mode_adds_routing_section():
    parsed = parse_unity_log(NULL_REF_LOG)
    prompt = build_unity_debug_prompt(
        parsed,
        project_name="Moonlit Depths",
        team_mode=True,
        team_members=["ari@example.com", "sam@example.com"],
    )
    _assert_team_content(prompt, ["ari@example.com", "sam@example.com"])


def test_debug_prompt_team_mode_without_members_still_labeled():
    parsed = parse_unity_log(NULL_REF_LOG)
    prompt = build_unity_debug_prompt(parsed, team_mode=True, team_members=None)
    assert "no other teammates on this project yet" in prompt


# --- build_feedback_review_prompt --------------------------------------------


def test_feedback_prompt_default_omits_team_content():
    parsed = parse_feedback(FEEDBACK_TEXT)
    solo = build_feedback_review_prompt(parsed, classify(parsed.entries))
    _assert_no_team_content(solo)


def test_feedback_prompt_team_mode_adds_routing_section():
    parsed = parse_feedback(FEEDBACK_TEXT)
    prompt = build_feedback_review_prompt(
        parsed,
        classify(parsed.entries),
        team_mode=True,
        team_members=["ari@example.com"],
    )
    _assert_team_content(prompt, ["ari@example.com"])


# --- build_test_review_prompt ------------------------------------------------


def test_test_review_prompt_default_omits_team_content():
    parsed = parse_test_results(TEST_RESULTS_TEXT)
    solo = build_test_review_prompt(parsed, project_name="Moonlit Depths")
    _assert_no_team_content(solo)


def test_test_review_prompt_team_mode_adds_routing_section():
    parsed = parse_test_results(TEST_RESULTS_TEXT)
    prompt = build_test_review_prompt(
        parsed,
        project_name="Moonlit Depths",
        team_mode=True,
        team_members=["sam@example.com"],
    )
    _assert_team_content(prompt, ["sam@example.com"])


# --- build_session_summary_prompt --------------------------------------------


def test_session_summary_prompt_default_omits_team_content():
    prompt = build_session_summary_prompt(
        since="2026-08-03 09:00:00",
        tested=["Test run: 3 passed / 0 failed"],
        fixed=["Pause menu freeze"],
        open_items=["Onboarding confusion"],
        project_name="Moonlit Depths",
    )
    _assert_no_team_content(prompt)
    assert "Tested:" in prompt
    assert "Fixed:" in prompt
    assert "Still open:" in prompt


def test_session_summary_prompt_empty_categories_say_so():
    prompt = build_session_summary_prompt(
        since="2026-08-03 09:00:00", tested=[], fixed=[], open_items=[]
    )
    assert "none recorded" in prompt


def test_session_summary_prompt_team_mode_adds_routing_section():
    prompt = build_session_summary_prompt(
        since="2026-08-03 09:00:00",
        tested=["Test run: 3 passed / 0 failed"],
        fixed=[],
        open_items=["Onboarding confusion"],
        team_mode=True,
        team_members=["ari@example.com"],
    )
    _assert_team_content(prompt, ["ari@example.com"])


def test_session_summary_prompt_never_mentions_raw_timing_as_wellbeing():
    # Guards the explicit Phase B constraint: session summaries never carry
    # duration/lateness framed as a wellbeing signal (that's local-only
    # Crunch-Pattern Awareness material, reserved for a later phase).
    prompt = build_session_summary_prompt(
        since="2026-08-03 09:00:00", tested=[], fixed=[], open_items=[]
    )
    lower = prompt.lower()
    assert "crunch" not in lower
    assert "how late" not in lower
    assert "worked late" not in lower
