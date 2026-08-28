"""E2E §1 -- Git Connector (E2E_TEST_PLAN.md).

**Deviations from the plan, applied here (see the final report for the full
list):**

* §1.1's "emits scan-complete event" and §1.4's "both connectors' events
  land in the same event/rules pipeline" describe a wiring that doesn't
  exist: ``connectors.git_connector``/``core.git_integration`` are pure
  local read/write git plumbing (status/history/diff/stage/commit/discard)
  with no scan concept and no ``TriggerEvent`` adapter (contrast
  ``core.rules_engine.finding_to_event``/``animation_bug_event``, which are
  real). §1.1 here tests the real completion signal instead: ``repo_status``
  succeeding, with the binary asset showing up correctly, and no crash.
  §1.4 is folded into the cross-cutting suite (§7) using a real
  event-emitting feature, since there is nothing git-connector-specific to
  test for "lands in the same pipeline" -- git_connector never lands in it
  at all.
* §1.5 (auth failure / private repo) has no corresponding code path: this
  connector never clones/fetches/pushes/pulls -- every operation is against
  an already-checked-out local working tree, so there is no auth-required
  operation to fail. Flagged untestable, not silently skipped (see
  ``test_no_remote_auth_surface_exists`` below, which pins that fact down
  rather than just omitting the row).
* §1.6 ("only the delta is processed") describes an incremental-scan/cache
  mechanism this connector doesn't have (there is no "scan" here at all,
  cached or otherwise). Rewritten to what's real: ``repo_status``/
  ``file_history`` correctness after a second commit.
"""

from __future__ import annotations

import pytest
from conftest import add_large_binary, make_git_fixture_repo

from spiced.connectors import git_connector

# --- §1.1: full scan of the fixture repo, no crash on binary files ---------


def test_1_1_repo_status_completes_clean_with_binary_asset(tmp_path):
    repo = make_git_fixture_repo(tmp_path)

    status = git_connector.repo_status(repo)

    assert status.is_clean is True
    assert status.is_detached is False
    # The binary (icon.png) and the submodule commit are both already
    # committed by the fixture -- nothing outstanding, no crash reading them.
    assert status.staged == []
    assert status.unstaged == []


def test_1_1_diff_for_path_does_not_crash_on_binary_file(tmp_path):
    repo = make_git_fixture_repo(tmp_path)
    # git's own diff for a binary blob is empty/"Binary files differ" text,
    # never a traceback -- confirm diff_for_path survives being pointed at one.
    diff = git_connector.diff_for_path(repo, "art/icon.png")
    assert isinstance(diff, str)


# --- §1.2: submodule is explicitly handled, not silently ignored -----------


def test_1_2_submodule_commit_is_tracked_not_silently_dropped(tmp_path):
    repo = make_git_fixture_repo(tmp_path)

    history = git_connector.file_history(repo, "vendor/lib")

    # The submodule *pointer* (a single gitlink entry, not its file tree) has
    # its own history in the parent repo -- the "add vendored submodule"
    # commit -- proving the submodule is tracked as a real path, not skipped.
    assert len(history) == 1
    assert history[0].message == "add vendored submodule"


def test_1_2_submodule_working_tree_is_present_and_reachable(tmp_path):
    repo = make_git_fixture_repo(tmp_path)
    assert (repo / "vendor" / "lib" / "lib.gd").is_file()
    status = git_connector.repo_status(repo)
    # A freshly-added submodule shows clean at the parent level (its own
    # untracked-ness is a property of the submodule's own repo, not the
    # parent's) -- confirms no spurious dirty/untracked noise from it.
    assert status.is_clean is True


# --- §1.3: large binary (50MB+) -- no timeout/OOM ---------------------------


def test_1_3_large_binary_status_and_stage_do_not_hang_or_oom(tmp_path):
    repo = make_git_fixture_repo(tmp_path)
    add_large_binary(repo, "art/huge_texture.bin", 60 * 1024 * 1024)

    status = git_connector.repo_status(repo)
    assert "art/huge_texture.bin" in status.untracked

    result = git_connector.stage_paths(repo, ["art/huge_texture.bin"])
    assert result.staged == ["art/huge_texture.bin"]

    commit = git_connector.commit_staged(repo, "add huge texture")
    assert commit.message == "add huge texture"
    # Streams/handles it rather than choking -- confirmed by reaching here at
    # all within the test's normal timeout, plus a clean status afterward.
    assert git_connector.repo_status(repo).is_clean is True


# --- §1.4: rewritten -- see module docstring; folded into §7 cross-cutting -


def test_1_4_note_connector_events_pipeline_is_covered_in_cross_cutting():
    pytest.skip(
        "git_connector emits no events at all (see module docstring) -- "
        "there is nothing connector-specific to test for 'shares the "
        "pipeline with Unity'. The real event/rules pipeline is exercised "
        "in tests/e2e/test_e2e_07_cross_cutting.py against a feature that "
        "actually participates in it."
    )


# --- §1.5: no remote-auth surface exists ------------------------------------


def test_1_5_no_remote_auth_surface_exists():
    """Pins down (rather than silently skipping) that git_connector has no
    clone/fetch/pull/push -- every public function takes an already-checked-
    out local path. There is no way to reach an "auth failure" from this
    module as written; §1.5 is untestable against the real code, not merely
    unimplemented in this suite."""
    public_names = {n for n in git_connector.__dict__ if not n.startswith("_")}
    remote_ops = {"clone", "fetch", "pull", "push"}
    assert public_names.isdisjoint(remote_ops)


def test_1_5_not_a_repo_error_is_typed_not_a_bare_exception(tmp_path):
    """The one "clear, typed error, not a generic exception" scenario that
    *does* apply to this connector: opening a non-repo path."""
    with pytest.raises(git_connector.NotAGitRepositoryError):
        git_connector.repo_status(tmp_path)


# --- §1.6: rewritten -- incremental correctness, not a caching mechanism ---


def test_1_6_second_commit_is_reflected_without_a_full_rescan_mechanism(tmp_path):
    repo = make_git_fixture_repo(tmp_path)
    before = git_connector.file_history(repo, "README.md")
    assert len(before) == 1

    (repo / "README.md").write_text("# Fixture Game\n\nUpdated.\n", encoding="utf-8")
    git_connector.stage_paths(repo, ["README.md"])
    git_connector.commit_staged(repo, "update readme")

    after = git_connector.file_history(repo, "README.md")
    # Only the delta (the new commit) is visible as the newest entry -- this
    # connector has no scan cache to invalidate/warm since it has no scan at
    # all; "delta only" here just means git's own commit-walk, which is
    # inherently incremental. No performance claim beyond that is made.
    assert len(after) == 2
    assert after[0].message == "update readme"
    assert after[1].message == before[0].message
