"""Tests for core.precommit_hook: install/uninstall + the "don't clobber a
foreign hook" rule.

Uses real ``git`` subprocess calls (via ``_git``) rather than faking a bare
``.git`` directory, since ``is_git_repo``/``hooks_dir`` now delegate to git
itself (``git rev-parse``) instead of guessing from the filesystem -- an
empty ``.git`` directory with no real repo structure underneath it is *not*
recognized by git, so the old "just mkdir .git" fake no longer applies.
"""

from __future__ import annotations

import subprocess

import pytest

from spiced.core.precommit_hook import (
    HOOK_MARKER,
    ForeignHookExistsError,
    NotAGitRepoError,
    hooks_dir,
    install_hook,
    is_git_repo,
    is_spiced_hook,
    uninstall_hook,
)


def _git(*args: str, cwd) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True)


def _make_repo(tmp_path):
    _git("init", "-q", cwd=tmp_path)
    return tmp_path


def test_is_git_repo_false_without_dot_git(tmp_path):
    assert is_git_repo(tmp_path) is False


def test_is_git_repo_true_with_dot_git(tmp_path):
    _make_repo(tmp_path)
    assert is_git_repo(tmp_path) is True


def test_is_git_repo_true_for_subdirectory_of_repo_root(tmp_path):
    """A Unity folder nested inside the actual repo root must still be
    detected as being in a git repo -- .git/hooks only exists at the true
    top-level, not necessarily at the connected project folder."""
    _make_repo(tmp_path)
    nested = tmp_path / "unity-project" / "Assets"
    nested.mkdir(parents=True)
    assert is_git_repo(nested) is True


def test_hooks_dir_resolves_to_true_repo_root_for_nested_folder(tmp_path):
    _make_repo(tmp_path)
    nested = tmp_path / "unity-project"
    nested.mkdir()
    assert hooks_dir(nested) == (tmp_path / ".git" / "hooks").resolve()


def test_hooks_dir_raises_when_not_a_git_repo(tmp_path):
    with pytest.raises(NotAGitRepoError):
        hooks_dir(tmp_path)


def test_install_hook_raises_when_not_a_git_repo(tmp_path):
    with pytest.raises(NotAGitRepoError):
        install_hook(tmp_path)


def test_install_hook_writes_a_working_hook(tmp_path):
    _make_repo(tmp_path)
    result = install_hook(tmp_path, python_executable="python")
    hook_path = hooks_dir(tmp_path) / "pre-commit"
    assert result.hook_path == str(hook_path)
    assert hook_path.is_file()
    text = hook_path.read_text(encoding="utf-8")
    assert HOOK_MARKER in text
    assert "spiced.core.precommit_check" in text
    assert "exit 0" in text
    assert str(tmp_path) in text


def test_install_hook_installs_at_true_repo_root_for_nested_project(tmp_path):
    """The hook must land in the real repo's hooks dir even when the
    connected Unity folder is a subdirectory of the repo root -- but the
    check script must still be told about the original (nested) project
    folder, not the resolved repo root."""
    _make_repo(tmp_path)
    nested = tmp_path / "unity-project"
    nested.mkdir()

    result = install_hook(nested, python_executable="python")

    hook_path = (tmp_path / ".git" / "hooks" / "pre-commit").resolve()
    assert result.hook_path == str(hook_path)
    assert hook_path.is_file()
    text = hook_path.read_text(encoding="utf-8")
    assert str(nested) in text


def test_install_hook_is_idempotent(tmp_path):
    _make_repo(tmp_path)
    install_hook(tmp_path, python_executable="python")
    # Installing again over its own previous hook must not raise.
    result = install_hook(tmp_path, python_executable="python")
    assert result.installed is True


def test_install_hook_refuses_to_overwrite_foreign_hook(tmp_path):
    _make_repo(tmp_path)
    hooks = hooks_dir(tmp_path)
    hooks.mkdir(parents=True, exist_ok=True)
    foreign = hooks / "pre-commit"
    foreign.write_text("#!/bin/sh\necho 'my own hook'\n", encoding="utf-8")

    with pytest.raises(ForeignHookExistsError):
        install_hook(tmp_path)

    # The foreign hook must be left completely untouched.
    assert foreign.read_text(encoding="utf-8") == "#!/bin/sh\necho 'my own hook'\n"


def test_is_spiced_hook_true_when_nothing_there_yet(tmp_path):
    hook_path = tmp_path / "pre-commit"
    assert is_spiced_hook(hook_path) is True


def test_is_spiced_hook_false_for_foreign_content(tmp_path):
    hook_path = tmp_path / "pre-commit"
    hook_path.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    assert is_spiced_hook(hook_path) is False


def test_uninstall_hook_removes_spiced_hook(tmp_path):
    _make_repo(tmp_path)
    install_hook(tmp_path, python_executable="python")
    assert uninstall_hook(tmp_path) is True
    assert not (hooks_dir(tmp_path) / "pre-commit").exists()


def test_uninstall_hook_leaves_foreign_hook_alone(tmp_path):
    _make_repo(tmp_path)
    hooks = hooks_dir(tmp_path)
    hooks.mkdir(parents=True, exist_ok=True)
    foreign = hooks / "pre-commit"
    foreign.write_text("#!/bin/sh\necho 'my own hook'\n", encoding="utf-8")

    assert uninstall_hook(tmp_path) is False
    assert foreign.is_file()


def test_uninstall_hook_no_op_when_missing(tmp_path):
    _make_repo(tmp_path)
    assert uninstall_hook(tmp_path) is False


def test_uninstall_hook_no_op_when_not_a_git_repo(tmp_path):
    """Must not raise just because the folder isn't (or is no longer) a git
    repo -- there's simply nothing Spiced-installed to remove."""
    assert uninstall_hook(tmp_path) is False


def test_is_git_repo_true_for_worktree(tmp_path):
    """A git worktree's ``.git`` is a *file* (``gitdir: ...``), not a
    directory -- is_git_repo must still recognize it by asking git itself
    rather than checking ``.is_dir()``."""
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _git("init", "-q", cwd=main_repo)
    _git("config", "user.email", "test@example.com", cwd=main_repo)
    _git("config", "user.name", "Test", cwd=main_repo)
    (main_repo / "a.txt").write_text("hi", encoding="utf-8")
    _git("add", "a.txt", cwd=main_repo)
    _git("commit", "-q", "-m", "init", cwd=main_repo)

    worktree = tmp_path / "worktree"
    _git("worktree", "add", "-q", str(worktree), "-b", "wt-branch", cwd=main_repo)

    assert (worktree / ".git").is_file()  # sanity check: it's a file, not a dir
    assert is_git_repo(worktree) is True
    assert hooks_dir(worktree) == (main_repo / ".git" / "hooks").resolve()


def test_install_hook_works_inside_a_worktree(tmp_path):
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    _git("init", "-q", cwd=main_repo)
    _git("config", "user.email", "test@example.com", cwd=main_repo)
    _git("config", "user.name", "Test", cwd=main_repo)
    (main_repo / "a.txt").write_text("hi", encoding="utf-8")
    _git("add", "a.txt", cwd=main_repo)
    _git("commit", "-q", "-m", "init", cwd=main_repo)

    worktree = tmp_path / "worktree"
    _git("worktree", "add", "-q", str(worktree), "-b", "wt-branch", cwd=main_repo)

    result = install_hook(worktree, python_executable="python")
    hook_path = (main_repo / ".git" / "hooks" / "pre-commit").resolve()
    assert result.hook_path == str(hook_path)
    assert hook_path.is_file()


def test_hooks_dir_uses_mocked_git_output_for_dot_git_as_file(tmp_path, monkeypatch):
    """Lighter-weight companion to the real-worktree tests above: simulate
    git's own resolution of a relocated/worktree-style ``.git`` without
    spinning up a real worktree, to pin down exactly how the two rev-parse
    outputs get combined."""
    import spiced.core.precommit_hook as precommit_hook

    other_repo_hooks = tmp_path / "elsewhere" / ".git" / "worktrees" / "wt" / "hooks"

    def fake_run(args, cwd, capture_output, text, timeout):
        assert args[0] == "git"
        if args[1:] == ["rev-parse", "--is-inside-work-tree"]:
            return subprocess.CompletedProcess(args, 0, stdout="true\n", stderr="")
        if args[1:] == ["rev-parse", "--git-path", "hooks"]:
            # git prints an absolute path here for worktrees/relocated .git dirs.
            return subprocess.CompletedProcess(args, 0, stdout=f"{other_repo_hooks}\n", stderr="")
        raise AssertionError(f"unexpected git invocation: {args}")

    monkeypatch.setattr(precommit_hook.subprocess, "run", fake_run)

    assert is_git_repo(tmp_path) is True
    assert hooks_dir(tmp_path) == other_repo_hooks.resolve()
