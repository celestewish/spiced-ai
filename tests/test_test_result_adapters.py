"""Tests for core.test_result_adapters: normalizing GUT (JUnit XML) and
Unreal Automation (JSON) test-run output into the generic
``{"tests": [...]}`` shape core.test_result_parser._try_parse_json already
understands.

The GUT sample below matches JUnit's real, documented shape (``<testcase>``,
pass/fail signaled by a child ``<failure>``/``<skipped>`` element) -- the one
this codebase's own test_result_parser deliberately does NOT recognize (it
only understands NUnit3's ``<test-case result="...">``), which is exactly
the regression this adapter exists to avoid: feeding real GUT output into
the unmodified pipeline would previously have silently misparsed it.
"""

from __future__ import annotations

import json

from spiced.core.test_result_adapters import (
    godot_junit_to_generic_json,
    unreal_report_to_generic_json,
)
from spiced.core.test_result_parser import parse_test_results

_GUT_JUNIT_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
  <testsuite name="TestPlayer" tests="3" failures="1" skipped="1">
    <testcase classname="TestPlayer" name="test_moves_forward" />
    <testcase classname="TestPlayer" name="test_takes_damage">
      <failure message="Expected health to be 80, got 100">assert_eq failed</failure>
    </testcase>
    <testcase classname="TestPlayer" name="test_respawns">
      <skipped />
    </testcase>
  </testsuite>
</testsuites>
"""


def test_godot_junit_adapter_extracts_passed_failed_skipped():
    generic_json = godot_junit_to_generic_json(_GUT_JUNIT_SAMPLE)
    data = json.loads(generic_json)

    statuses = {t["name"]: t["status"] for t in data["tests"]}
    assert statuses["TestPlayer.test_moves_forward"] == "passed"
    assert statuses["TestPlayer.test_takes_damage"] == "failed"
    assert statuses["TestPlayer.test_respawns"] == "skipped"


def test_godot_junit_adapter_carries_the_failure_message():
    data = json.loads(godot_junit_to_generic_json(_GUT_JUNIT_SAMPLE))
    failed = next(t for t in data["tests"] if t["status"] == "failed")
    assert "Expected health to be 80" in failed["message"]


def test_godot_junit_adapter_feeds_the_real_parser_correctly():
    """End-to-end: the adapter's output, run through the actual
    test_result_parser (unmodified), produces correct counts -- confirming
    this fixes the real misparse regression, not just that the adapter's
    own output looks plausible in isolation."""
    parsed = parse_test_results(godot_junit_to_generic_json(_GUT_JUNIT_SAMPLE))
    assert parsed.total == 3
    assert parsed.passed == 1
    assert parsed.failed == 1
    assert parsed.skipped == 1


def test_godot_junit_adapter_never_raises_on_malformed_xml():
    data = json.loads(godot_junit_to_generic_json("not xml at all"))
    assert data == {"tests": []}


def test_unreal_adapter_reads_a_tests_list_shape():
    report = json.dumps(
        {
            "tests": [
                {"testDisplayName": "Physics.Gravity", "state": "Success"},
                {"testDisplayName": "AI.Pathing", "state": "Fail"},
                {"testDisplayName": "UI.MainMenu", "state": "NotRun"},
            ]
        }
    )
    data = json.loads(unreal_report_to_generic_json(report))
    statuses = {t["name"]: t["status"] for t in data["tests"]}
    assert statuses["Physics.Gravity"] == "passed"
    assert statuses["AI.Pathing"] == "failed"
    assert statuses["UI.MainMenu"] == "skipped"


def test_unreal_adapter_reads_a_top_level_count_shape():
    report = json.dumps({"succeeded": 5, "failed": 2})
    data = json.loads(unreal_report_to_generic_json(report))
    assert data == {"passed": 5, "failed": 2, "skipped": 0, "total": 7}


def test_unreal_adapter_never_raises_on_an_unrecognized_shape():
    """The real schema is unverified against a real run (see module
    docstring) -- confirms an unexpected shape degrades to an empty test
    list rather than crashing."""
    data = json.loads(unreal_report_to_generic_json(json.dumps({"something": "unexpected"})))
    assert data == {"tests": []}


def test_unreal_adapter_never_raises_on_malformed_json():
    data = json.loads(unreal_report_to_generic_json("not json"))
    assert data == {"tests": []}
