# Spiced — End-to-End Test Plan

**Scope:** the six features from the latest plan (Git connector, Godot connector, cross-feature rules/trigger subsystem, usage-based billing, Small-Team Mode RBAC, and extensibility roadmap note). Unit/integration tests are already done — this plan targets end-to-end flows: a real trigger event moving through connector → rules → billing → permissions, the way it would in production.

**Status note:** the last five commits implementing this plan exist locally and have not been pushed to remote yet. Run this plan against the local branch before pushing, so failures get caught pre-push.

---

## 0. Test Environment Setup

- [ ] Confirm Python version and dependency manager (`pyproject.toml` / `requirements.txt`) match CI
- [ ] Standardize on `pytest` + `pytest-asyncio` (if any connector/webhook code is async) for E2E orchestration
- [ ] Build fixture repos:
  - A small throwaway **Git** repo (local, not a real remote) with a realistic commit history, at least one binary asset, and one submodule, to exercise the Git connector without needing network access
  - A minimal **Godot** project directory (`project.godot`, a `.tscn` scene, a `.gd` script, one imported asset) to exercise the Godot connector
- [ ] Stand up a test double for billing (in-memory ledger) so E2E tests can assert on metered usage without hitting a real payment processor
- [ ] Seed at least 3 test accounts across tiers: Free, Small-Team, Studio/Publisher — needed for RBAC and billing-tier tests
- [ ] Decide where E2E tests live: `tests/e2e/` separate from existing `tests/unit/` and `tests/integration/`, so they can be run/skipped independently (E2E is typically slower)

---

## 1. Git Connector (feature 1)

Goal: prove the connector works as a first-class alongside the existing Unity-only scanners, not just in isolation.

| # | Scenario | Expected outcome |
|---|----------|-------------------|
| 1.1 | Point connector at fixture repo, run a full scan | Connector completes, emits scan-complete event, no crash on binary files |
| 1.2 | Repo with a submodule | Submodule is either scanned or explicitly skipped with a logged reason — not silently ignored |
| 1.3 | Repo with a large binary (e.g., 50MB+ fake asset) | No timeout/OOM; connector either streams or skips per size threshold |
| 1.4 | Repo + existing Unity scanner both configured on same project | Both connectors' events land in the same event/rules pipeline without collision or duplicate triggers |
| 1.5 | Auth failure (bad token / private repo without access) | Clear, typed error surfaced — not a generic exception bubbling up |
| 1.6 | Incremental scan (second run after 1 new commit) | Only the delta is processed, not a full re-scan (performance-relevant for indie repos scanned frequently) |

---

## 2. Godot Connector (feature 2)

Goal: confirm parity of experience with the Unity path, since Godot is the priority audience.

| # | Scenario | Expected outcome |
|---|----------|-------------------|
| 2.1 | Scan fixture Godot project | Detects `project.godot`, parses scene tree, identifies scripts and imported assets |
| 2.2 | GDScript-specific analysis (if Spiced does code analysis, not just asset scanning) | Script issues/patterns are detected the same way C# issues are for Unity |
| 2.3 | Version mismatch (project built on newer/older Godot than connector expects) | Graceful degradation with a version warning, not a hard failure |
| 2.4 | Godot + Git connector on the same project | Combined event stream reflects both source-control and engine-level changes without duplicate or conflicting triggers |
| 2.5 | Missing/corrupt `.tscn` file | Connector reports the specific broken file rather than aborting the whole scan |

---

## 3. Cross-Feature Rules/Trigger Subsystem (feature 3 — highest priority)

This is flagged as the feature the "workflow platform" positioning depends on, so it gets the deepest E2E coverage — this is where most of the actual bugs will hide.

| # | Scenario | Expected outcome |
|---|----------|-------------------|
| 3.1 | Single connector event fires a single matching rule | Rule executes exactly once, correct payload |
| 3.2 | One event matches multiple rules | All matching rules fire; order is deterministic (define and test the ordering guarantee) |
| 3.3 | Rule chaining — output of Rule A triggers Rule B | Chain completes without infinite loop; add an explicit test for a rule that could self-trigger (cycle detection) |
| 3.4 | Simultaneous events from Git connector + Godot connector on the same project within the same window | No dropped events, no race condition double-firing a rule |
| 3.5 | Rule references a feature/tier the account doesn't have access to | Rule fails closed (doesn't execute) with a clear reason, not a silent no-op |
| 3.6 | High event volume (burst of 100+ events) | Trigger layer queues/throttles rather than dropping events or crashing |
| 3.7 | Rule execution failure mid-chain | Partial failure is logged/recoverable; doesn't corrupt state for unrelated rules |

---

## 4. Usage-Based Billing (feature 4)

Goal: this replaces a mock counter, so correctness here is financially load-bearing — test it like a payments feature, not a nice-to-have.

| # | Scenario | Expected outcome |
|---|----------|-------------------|
| 4.1 | Single billable action (e.g., one scan) | Ledger increments by exactly the right amount |
| 4.2 | Concurrent billable actions from same account | No double-count / lost update (classic race condition to check explicitly) |
| 4.3 | Account crosses tier threshold mid-billing-period | Overage handled per pricing rule (blocked, billed, or throttled — confirm which and test that one) |
| 4.4 | Migration case: account that was using the old mock counter | Historical mock data doesn't corrupt the new real ledger on cutover |
| 4.5 | Billing event tied to a rules-subsystem trigger (feature 3) | Rule-driven usage is metered the same as direct user actions — nothing "free" just because it was automated |
| 4.6 | Downgrade mid-period | Metering correctly reflects the tier in effect at time of usage, not current tier |

---

## 5. Small-Team Mode RBAC (feature 5)

Goal: confirm this is baseline-solid before it's compared against ShotGrid/Flow by a studio buyer.

| # | Scenario | Expected outcome |
|---|----------|-------------------|
| 5.1 | Admin role performs a restricted action | Succeeds |
| 5.2 | Non-admin role attempts same restricted action | Blocked with a clear permission error, not a 500 |
| 5.3 | Role change mid-session | Permission takes effect without requiring re-login (or, if it does require re-auth, that's the confirmed expected behavior — test whichever is true) |
| 5.4 | RBAC interacting with billing tier (e.g., a permission that's Studio-tier-only) | Correct combined gate — team role AND account tier both enforced, not just one |
| 5.5 | RBAC interacting with rules subsystem — rule created by a lower-permission user | Rule execution respects the creating user's permission scope, not an elevated system-level scope |

---

## 6. Extensibility (feature 6 — roadmap only)

No E2E tests needed yet since this is explicitly deferred. Flag in this doc so it isn't accidentally skipped later: **when a public API / plugin architecture ships, add an E2E suite for third-party auth scoping and rate limits before it goes live** — that's the RBAC-style risk class repeating in a new place.

---

## 7. Cross-Cutting E2E Scenarios (full-stack, all features together)

These are the scenarios that actually validate the "workflow platform" story end to end:

1. Developer pushes a commit to the fixture Git repo → Git connector detects it → fires a rule in the trigger subsystem → rule action is metered in billing → action is only visible to users with the right RBAC role.
2. Same as above, but the account is at its usage cap when the commit lands — confirm the rule either queues, blocks, or bills overage per the defined policy (don't leave this undefined).
3. A Godot-project change and a Git commit land within the same second — confirm the rules subsystem processes both without dropping either.

---

## 8. Running This via Claude Code

Suggested flow:
1. Have Claude Code read this doc plus the actual feature code (the 5 unpushed local commits) before writing any test.
2. Generate E2E tests section-by-section (1 → 7), running each section's tests after writing them, not all at the end — catch failures early against the real local commits.
3. For each failing test, have Claude Code determine whether the bug is in the code or the test expectation before "fixing" anything.
4. Once section 7 (cross-cutting) passes locally, that's the signal it's safe to push the 5 pending commits.
5. After push, the paired GitHub Actions workflow (`e2e-tests.yml`) re-runs this suite on every PR against `main`.

See `CLAUDE.md` for the generation ruleset and `.github/workflows/e2e-tests.yml` for the CI wiring.
