"""E2E §6 -- Extensibility (roadmap only).

E2E_TEST_PLAN.md §6 is explicit that this needs no E2E tests yet: "No E2E
tests needed yet since this is explicitly deferred." Confirmed against the
actual code -- there is no public API / plugin architecture in this
codebase to test (no ``src/spiced/api/``, no plugin loader, no third-party
auth-scoping surface). This file exists only so the suite has a section-6
marker matching the plan's own numbering, per the plan's own instruction:
*"Flag in this doc so it isn't accidentally skipped later: when a public
API/plugin architecture ships, add an E2E suite for third-party auth
scoping and rate limits before it goes live."*
"""

from __future__ import annotations

import pytest


def test_no_public_plugin_api_exists_yet():
    """Sanity check that §6 is still correctly deferred, not silently
    stale: if a public API package ever appears, this test starts failing
    and should be replaced with the real §6 E2E suite the plan calls for."""
    import importlib.util

    assert importlib.util.find_spec("spiced.api") is None
    assert importlib.util.find_spec("spiced.plugins") is None


def test_extensibility_e2e_suite_is_intentionally_deferred():
    pytest.skip(
        "§6 is roadmap-only per E2E_TEST_PLAN.md -- no third-party auth-"
        "scoping/rate-limit surface exists to test yet. See this module's "
        "docstring for the trigger condition to un-defer it."
    )
