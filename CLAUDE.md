# Spiced — Test Generation Config

## Context
Python project. Code-level (unit/integration) tests for the current 6-feature rollout are already complete. This config is for the **end-to-end test suite** described in `E2E_TEST_PLAN.md` — write and run those tests from that doc, in order (sections 1 → 7).

## Test framework
- `pytest` (+ `pytest-asyncio` if any connector/webhook/event code is async)
- E2E tests live in `tests/e2e/`, separate from `tests/unit/` and `tests/integration/`
- Use fixture repos/projects described in `E2E_TEST_PLAN.md` §0 — build them under `tests/e2e/fixtures/` if they don't exist yet

## Generation rules
- Work through `E2E_TEST_PLAN.md` one numbered section at a time. Write the tests for a section, run them, resolve failures, then move to the next section.
- For every failing test: diagnose whether the bug is in the feature code (one of the 5 pending local commits) or in the test's expectation, before changing anything. State which, briefly, before fixing.
- Section 3 (rules/trigger subsystem) and section 7 (cross-cutting flows) are the highest-priority sections — they test the feature the product's core positioning depends on. Do not skip or shortcut these even under time pressure.
- Billing tests (section 4) must assert exact ledger values, not just "no error" — this is metered revenue, treat correctness as a hard requirement.
- Prefer real fixture data (a real small Git repo, a real minimal Godot project) over mocks where feasible, since these are E2E tests validating real integration behavior, not unit isolation.
- Avoid hitting real network/payment endpoints — use the in-memory billing ledger double specified in the plan.
- Target: every row in the plan's tables becomes at least one test. Flag any row you could not test (and why) rather than silently skipping it.

## After all sections pass
Report a short summary: which sections passed clean, which needed fixes (and what was fixed — code or test), and confirm section 7 (cross-cutting) is green before recommending the 5 pending commits be pushed.
