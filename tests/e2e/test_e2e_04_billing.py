"""E2E §4 -- Billing (E2E_TEST_PLAN.md), rewritten to match the real
implementation, per the explicit direction to rewrite this section rather
than mark it N/A or build the missing feature.

**Why this section is rewritten wholesale.** E2E_TEST_PLAN.md's §4 describes
a metered usage ledger: exact increments per billable action, concurrent-
action race conditions, overage billing at a tier threshold, and migrating
"the old mock counter" onto a "real ledger". None of that exists.
``core.usage_counter`` (module docstring, verbatim): *"Usage-based metered
billing (per-prompt overage) stays explicitly deferred -- flat tiers only."*
The real Phase 5 feature is: (a) ``core.billing_service.BillingService``
returns Stripe-hosted Checkout/Portal URLs for the user to complete a
purchase in their own browser (the app never touches a card number or a
usage count for billing purposes), and (b) ``core.usage_counter.
UsageCounter.current_plan`` resolves the *tier* (not a metered balance) from
that real subscription when signed in, falling back to a local, freely-
editable "preview" plan setting otherwise. What follows tests (b) and (a)
directly, and folds in what actually stands in for each plan row:

* §4.1/§4.2 (exact ledger increment / concurrent-action race) -- no ledger
  exists to assert on. See ``test_4_1_4_2_no_metered_ledger_exists``, which
  pins down its absence rather than silently dropping the row.
* §4.3 (crosses tier threshold mid-period, overage) -- there is no usage
  threshold to cross; flat tiers only. Rewritten as a plan-*resolution*
  test: which plan applies depends on the real subscription's current
  ``status``, tested directly.
* §4.4 (migration from the old mock counter) -- real and testable as
  written: the local mock plan setting must not corrupt or get clobbered by
  a real subscription once one exists, and must still work standalone when
  none does.
* §4.5 (rule-driven usage metered the same as direct usage) -- no metering
  exists for either. Rewritten: a rules-engine-created task (§3) is
  unaffected by the acting team's billing tier, cross-referenced with §3.5.
* §4.6 (downgrade mid-period reflects tier at time of usage) -- no
  time-of-usage tracking exists (there is no usage-to-plan attribution at
  all, metered or otherwise). Flagged untestable rather than invented.
"""

from __future__ import annotations

import pytest
from tests.e2e.conftest import _NOW, build_e2e_services

from spiced.backend_client.api_client import BackendAPIError, Subscription
from spiced.core.plans import PLANS

# --- §4.1 / §4.2: rewritten -- no metered ledger exists ---------------------


def test_4_1_4_2_no_metered_ledger_exists(tmp_path):
    """core.billing_service.BillingService has no method that increments,
    reads, or reconciles a usage ledger -- only checkout/portal session
    creation and subscription lookup. Pinned down explicitly rather than
    silently dropping §4.1/§4.2."""
    from spiced.core import billing_service

    public_methods = {
        name for name in vars(billing_service.BillingService) if not name.startswith("_")
    }
    assert public_methods == {"current_subscription", "start_checkout", "open_billing_portal"}


# --- §4.3: rewritten -- plan resolution from real subscription status ------


def test_4_3_active_subscription_resolves_to_its_real_plan(tmp_path):
    services, backend = build_e2e_services()
    services.auth.log_in("dev@example.com", "hunter2")
    backend.subscriptions["user-dev"] = Subscription(
        id="sub-1",
        user_id="user-dev",
        team_id=None,
        plan_key="studio",
        stripe_customer_id="cus-1",
        stripe_subscription_id="sub-stripe-1",
        status="active",
        current_period_end=None,
        created_at=_NOW,
    )

    plan = services.usage.current_plan()

    assert plan.key == "studio"
    assert plan.is_unlimited is True


@pytest.mark.parametrize("status", ["active", "trialing", "past_due"])
def test_4_3_usable_statuses_all_grant_their_plan(tmp_path, status):
    services, backend = build_e2e_services()
    services.auth.log_in("dev@example.com", "hunter2")
    backend.subscriptions["user-dev"] = Subscription(
        id="sub-1",
        user_id="user-dev",
        team_id=None,
        plan_key="indie",
        stripe_customer_id="cus-1",
        stripe_subscription_id="sub-stripe-1",
        status=status,
        current_period_end=None,
        created_at=_NOW,
    )

    assert services.usage.current_plan().key == "indie"


@pytest.mark.parametrize("status", ["canceled", "unpaid", "incomplete"])
def test_4_3_non_usable_statuses_fall_back_to_local_plan_not_the_stale_subscription(
    tmp_path, status
):
    services, backend = build_e2e_services()
    services.auth.log_in("dev@example.com", "hunter2")
    services.usage.set_plan("free")
    backend.subscriptions["user-dev"] = Subscription(
        id="sub-1",
        user_id="user-dev",
        team_id=None,
        plan_key="studio",
        stripe_customer_id="cus-1",
        stripe_subscription_id="sub-stripe-1",
        status=status,
        current_period_end=None,
        created_at=_NOW,
    )

    plan = services.usage.current_plan()

    # A canceled/unpaid/incomplete subscription must NOT still grant its
    # plan -- this is the one place §4.3's "overage/tier-boundary" intent
    # maps onto real behavior: access is gated by subscription status, just
    # not by a usage counter.
    assert plan.key == "free"


# --- §4.4: migration from the old mock counter -- real and testable --------


def test_4_4_local_mock_plan_still_works_standalone_with_no_subscription(tmp_path):
    """A solo/offline developer (never signed in, or signed in with no
    Stripe subscription) keeps the original mock-counter behavior --
    Spiced never gates a local-only workflow behind a purchase."""
    services, _backend = build_e2e_services()
    services.usage.set_plan("indie")

    assert services.usage.current_plan().key == "indie"
    assert services.usage.status().plan.key == "indie"


def test_4_4_real_subscription_does_not_corrupt_the_local_mock_setting(tmp_path):
    """The migration-safety concern §4.4 is really after: does gaining a
    real subscription corrupt the pre-existing local mock plan setting?
    It must not -- current_plan just prefers the real one while it's usable;
    the mock setting is left untouched underneath and still readable."""
    services, backend = build_e2e_services()
    services.auth.log_in("dev@example.com", "hunter2")
    services.usage.set_plan("free")  # pre-existing local "mock counter" state
    backend.subscriptions["user-dev"] = Subscription(
        id="sub-1",
        user_id="user-dev",
        team_id=None,
        plan_key="studio",
        stripe_customer_id="cus-1",
        stripe_subscription_id="sub-stripe-1",
        status="active",
        current_period_end=None,
        created_at=_NOW,
    )

    assert services.usage.current_plan().key == "studio"  # real subscription wins

    # Cancel the subscription -- the original local setting is still there,
    # unharmed, and takes over again exactly as if the subscription had
    # never existed.
    backend.subscriptions["user-dev"] = Subscription(
        id="sub-1",
        user_id="user-dev",
        team_id=None,
        plan_key="studio",
        stripe_customer_id="cus-1",
        stripe_subscription_id="sub-stripe-1",
        status="canceled",
        current_period_end=None,
        created_at=_NOW,
    )
    assert services.usage.current_plan().key == "free"


def test_4_4_backend_hiccup_during_migration_falls_back_safely(tmp_path, monkeypatch):
    """A billing lookup failure (backend down mid-migration, expired token,
    ...) must degrade to the local mock plan, never raise into the caller."""
    services, backend = build_e2e_services()
    services.auth.log_in("dev@example.com", "hunter2")
    services.usage.set_plan("indie")

    def _boom():
        raise BackendAPIError("simulated outage")

    monkeypatch.setattr(backend, "get_subscription", _boom)

    assert services.usage.current_plan().key == "indie"  # never raises


# --- §4.5: rewritten -- no metering asymmetry exists between rule-driven ---
# and direct usage; see test_e2e_03_rules_engine.py's §3.5 test for the
# rules-engine half of this. Kept here too for §4's own row coverage.


def test_4_5_billing_tier_never_gates_whether_a_rule_fires(tmp_path):
    from tests.e2e.conftest import seed_team_with_tiered_accounts

    from spiced.automation.finding import SEVERITY_WARNING
    from spiced.core.rules_engine import ACTION_CREATE_TASK, TriggerEvent, evaluate_rules

    services, backend = build_e2e_services()
    project = services.projects.create_project("Fixture Game", engine="Godot")
    team, _uuid, accounts = seed_team_with_tiered_accounts(services, backend, project)
    assert accounts["member"].tier == "free"  # the acting/creating account is free-tier
    backend.add_trigger_rule(
        team.id, "audio.loudness_normalize", SEVERITY_WARNING, ACTION_CREATE_TASK
    )

    event = TriggerEvent(
        event_kind="audio.loudness_normalize",
        project_id=project.id,
        severity=SEVERITY_WARNING,
        summary="2 file(s) too loud",
        source_feature_id="audio.loudness_normalize",
        run_id="r1",
    )
    results = evaluate_rules(services, event)

    # Nothing about the team's tier is even consulted -- the rule-driven
    # task is created exactly as it would be for a studio-tier team.
    assert results[0].performed is True
    assert len(backend.tasks) == 1


# --- §4.6: no time-of-usage attribution exists at all -----------------------


def test_4_6_no_usage_to_plan_time_attribution_exists():
    """current_plan() always reflects the *current* subscription lookup --
    there is no stored record of which plan was active when a given prompt/
    action happened, metered or otherwise, so a "downgrade mid-period,
    billed at the old rate" scenario has nothing to assert against. Flagged
    untestable, not invented."""
    from spiced.core.usage_counter import UsageCounter

    public_methods = {name for name in vars(UsageCounter) if not name.startswith("_")}
    assert "record_prompt" in public_methods
    # record_prompt takes no plan/tier argument -- a recorded prompt carries
    # no association with the plan that was active at the time.
    import inspect

    params = inspect.signature(UsageCounter.record_prompt).parameters
    assert set(params) == {"self", "provider", "kind"}


def test_sanity_plans_used_above_exist_in_the_real_plan_table():
    assert {"free", "indie", "studio"} <= set(PLANS)
