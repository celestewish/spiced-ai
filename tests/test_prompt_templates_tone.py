"""Tone/hedging rules shared across every AI prompt builder in ai.prompt_templates.

Every one of the 24 rule tuples in that module opens with the same "how to
speak" line -- the single highest-leverage place to make Spiced's responses
read as more approachable to a developer newer to the industry, and to keep
accuracy caveats honest without tipping into generic "no guarantees" hedging.
"""

from __future__ import annotations

from spiced.ai import prompt_templates

# DRAFT_TRANSLATION_RULES is deliberately excluded: it drives a literal,
# line-by-line machine translation pass, not a Spiced-the-companion response,
# so the shared "how to speak" line doesn't apply there.
_EXCLUDED_RULE_TUPLES = {"DRAFT_TRANSLATION_RULES"}

_RULE_TUPLE_NAMES = [
    name
    for name in dir(prompt_templates)
    if name.endswith("_RULES")
    and name not in _EXCLUDED_RULE_TUPLES
    and isinstance(getattr(prompt_templates, name), tuple)
]


def test_every_rule_set_asks_for_plain_language_for_newcomers():
    assert _RULE_TUPLE_NAMES, "expected at least one *_RULES tuple in prompt_templates"
    for name in _RULE_TUPLE_NAMES:
        rules = " ".join(getattr(prompt_templates, name))
        assert "newer to the industry" in rules, f"{name} is missing the plain-language rule"
        assert "not a hype machine" in rules, f"{name} is missing the honesty-without-hype rule"


def test_asset_scan_rules_state_the_orphaned_asset_limit_without_hedging():
    rules = " ".join(prompt_templates.ASSET_SCAN_RULES).lower()
    assert "resources.load" in rules
    assert "best-effort signal" not in rules
