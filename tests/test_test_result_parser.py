from spiced.core.test_result_parser import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    FORMAT_JSON,
    FORMAT_TEXT,
    FORMAT_XML,
    parse_test_results,
)

MANUAL_TEXT = """Test run summary
Total: 5
Passed: 2
Failed: 2
Skipped: 1

PASS Player can move left and right
PASS Jump reaches expected height
FAIL Player takes damage from spikes
  Expected health to drop but it stayed the same
FAIL Health pickup restores health
  Health stayed at 0 after pickup
SKIPPED Boss fight balance (needs level 3)
"""


def test_manual_text_scenario_counts_and_failures():
    parsed = parse_test_results(MANUAL_TEXT)
    assert parsed.source_format == FORMAT_TEXT
    assert parsed.total == 5
    assert parsed.passed == 2
    assert parsed.failed == 2
    assert parsed.skipped == 1
    assert parsed.confidence == CONFIDENCE_HIGH
    joined = " ".join(parsed.failures)
    assert "Player takes damage from spikes" in joined
    assert "Health pickup restores health" in joined
    # The peeked detail line is attached to the failure.
    assert "stayed" in joined.lower()


def test_repeated_failures_each_captured():
    text = "FAIL Flaky login\nFAIL Flaky login\nFAIL Flaky login\n"
    parsed = parse_test_results(text)
    assert parsed.failed == 3
    assert len(parsed.failures) == 3


def test_empty_input_is_low_confidence():
    parsed = parse_test_results("   \n  ")
    assert parsed.total == 0
    assert parsed.confidence == CONFIDENCE_LOW


def test_json_list_of_tests():
    payload = (
        '[{"name": "moves", "status": "pass"},'
        ' {"name": "jumps", "status": "fail", "message": "too low"},'
        ' {"name": "boss", "status": "skipped"}]'
    )
    parsed = parse_test_results(payload)
    assert parsed.source_format == FORMAT_JSON
    assert parsed.total == 3
    assert parsed.passed == 1
    assert parsed.failed == 1
    assert parsed.skipped == 1
    assert any("jumps" in f for f in parsed.failures)


def test_json_top_level_counts():
    parsed = parse_test_results('{"passed": 4, "failed": 1, "skipped": 2}')
    assert parsed.source_format == FORMAT_JSON
    assert parsed.passed == 4
    assert parsed.failed == 1
    assert parsed.skipped == 2
    assert parsed.total == 7


def test_nunit_xml_test_cases():
    xml = (
        '<test-run>'
        '<test-case name="Moves" result="Passed" />'
        '<test-case name="Jumps" result="Failed">'
        '<failure><message>height too low</message></failure>'
        '</test-case>'
        '<test-case name="Boss" result="Skipped" />'
        '</test-run>'
    )
    parsed = parse_test_results(xml)
    assert parsed.source_format == FORMAT_XML
    assert parsed.total == 3
    assert parsed.passed == 1
    assert parsed.failed == 1
    assert parsed.skipped == 1
    assert any("Jumps" in f for f in parsed.failures)


def test_excerpt_is_capped():
    huge = "PASS line\n" * 5000
    parsed = parse_test_results(huge)
    assert len(parsed.excerpt) <= 2100  # cap + truncation marker
