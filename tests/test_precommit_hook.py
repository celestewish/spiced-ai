"""Tests for core.precommit_hook: install/uninstall + the "don't clobber a
foreign hook" rule."""

from __future__ import annotations

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


def _make_repo(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_is_git_repo_false_without_dot_git(tmp_path):
    assert is_git_repo(tmp_path) is False


def test_is_git_repo_true_with_dot_git(tmp_path):
    _make_repo(tmp_path)
    assert is_git_repo(tmp_path) is True


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


def test_install_hook_is_idempotent(tmp_path):
    _make_repo(tmp_path)
    install_hook(tmp_path, python_executable="python")
    # Installing again over its own previous hook must not raise.
    result = install_hook(tmp_path, python_executable="python")
    assert result.installed is True


def test_install_hook_refuses_to_overwrite_foreign_hook(tmp_path):
    _make_repo(tmp_path)
    hooks = hooks_dir(tmp_path)
    hooks.mkdir(parents=True)
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
    hooks.mkdir(parents=True)
    foreign = hooks / "pre-commit"
    foreign.write_text("#!/bin/sh\necho 'my own hook'\n", encoding="utf-8")

    assert uninstall_hook(tmp_path) is False
    assert foreign.is_file()


def test_uninstall_hook_no_op_when_missing(tmp_path):
    _make_repo(tmp_path)
    assert uninstall_hook(tmp_path) is False
