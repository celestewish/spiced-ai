"""Tests for core.precommit_check: local deterministic checks + the CLI entry.

The hook's core promise is "always exits 0" — several tests here exist
specifically to pin that down, including when things go wrong internally.
"""

from __future__ import annotations

import subprocess

from spiced.core.precommit_check import (
    KIND_DEBUG_STATEMENT,
    KIND_LARGE_FILE,
    KIND_MERGE_CONFLICT,
    KIND_TODO,
    check_file,
    check_files,
    format_findings,
    get_staged_files,
    main,
    run_ai_pass,
)


def test_check_file_flags_todo(tmp_path):
    f = tmp_path / "Player.cs"
    f.write_text("void Foo() {\n    // TODO: fix this later\n}\n", encoding="utf-8")
    findings = check_file(f)
    assert any(x.kind == KIND_TODO for x in findings)


def test_check_file_flags_debug_log(tmp_path):
    f = tmp_path / "Player.cs"
    f.write_text('void Foo() {\n    Debug.Log("here");\n}\n', encoding="utf-8")
    findings = check_file(f)
    assert any(x.kind == KIND_DEBUG_STATEMENT for x in findings)


def test_check_file_flags_stray_print(tmp_path):
    f = tmp_path / "script.py"
    f.write_text("def foo():\n    print('debugging')\n", encoding="utf-8")
    findings = check_file(f)
    assert any(x.kind == KIND_DEBUG_STATEMENT for x in findings)


def test_check_file_flags_merge_conflict_markers(tmp_path):
    f = tmp_path / "Player.cs"
    f.write_text("<<<<<<< HEAD\nfoo\n=======\nbar\n>>>>>>> branch\n", encoding="utf-8")
    findings = check_file(f)
    kinds = [x.kind for x in findings]
    assert kinds.count(KIND_MERGE_CONFLICT) == 3


def test_check_file_flags_large_file(tmp_path):
    f = tmp_path / "big.cs"
    f.write_bytes(b"\0" * (6 * 1024 * 1024))
    findings = check_file(f, max_bytes=5 * 1024 * 1024)
    assert any(x.kind == KIND_LARGE_FILE for x in findings)


def test_check_file_ignores_non_scannable_extensions(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("TODO: not a real code file", encoding="utf-8")
    assert check_file(f) == []


def test_check_file_skips_unreadable_file_without_raising(tmp_path):
    missing = tmp_path / "does_not_exist.cs"
    assert check_file(missing) == []


def test_check_file_clean_file_has_no_findings(tmp_path):
    f = tmp_path / "Clean.cs"
    f.write_text("public class Clean {\n    public void Foo() {}\n}\n", encoding="utf-8")
    assert check_file(f) == []


def test_check_files_aggregates_across_files(tmp_path):
    a = tmp_path / "A.cs"
    a.write_text("// TODO: a\n", encoding="utf-8")
    b = tmp_path / "B.cs"
    b.write_text("// TODO: b\n", encoding="utf-8")
    findings = check_files([a, b])
    assert len(findings) == 2


def test_format_findings_empty_says_no_issues():
    text = format_findings([])
    assert "no obvious issues" in text.lower()
    assert "heads-up" in text.lower()


def test_format_findings_lists_each_finding(tmp_path):
    f = tmp_path / "A.cs"
    f.write_text("// TODO: a\n", encoding="utf-8")
    findings = check_file(f)
    text = format_findings(findings)
    assert "TODO" in text
    assert str(f) in text


# --- get_staged_files ----------------------------------------------------------


def test_get_staged_files_returns_empty_when_git_missing(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert get_staged_files(tmp_path) == []


def test_get_staged_files_parses_output(monkeypatch, tmp_path):
    class _Result:
        returncode = 0
        stdout = "Assets/Scripts/Player.cs\nAssets/Scripts/Enemy.cs\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())
    files = get_staged_files(tmp_path)
    assert files == [tmp_path / "Assets/Scripts/Player.cs", tmp_path / "Assets/Scripts/Enemy.cs"]


def test_get_staged_files_returns_empty_on_nonzero_exit(monkeypatch, tmp_path):
    class _Result:
        returncode = 128
        stdout = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: _Result())
    assert get_staged_files(tmp_path) == []


# --- run_ai_pass: time-boxed, never blocks ------------------------------------


class _UnavailableProvider:
    def is_available(self):
        return False


class _SlowProvider:
    def is_available(self):
        return True

    def generate(self, prompt):
        import time

        time.sleep(5)
        raise AssertionError("should not be reached before timeout")


class _FailingProvider:
    def is_available(self):
        return True

    def generate(self, prompt):
        raise RuntimeError("boom")


def test_run_ai_pass_returns_none_when_provider_unavailable():
    assert run_ai_pass(_UnavailableProvider(), [], 0) is None


def test_run_ai_pass_returns_none_on_provider_exception():
    assert run_ai_pass(_FailingProvider(), [], 0) is None


def test_run_ai_pass_times_out_without_blocking():
    result = run_ai_pass(_SlowProvider(), [], 0, timeout_s=0.05)
    assert result is None


# --- main(): always exits 0 -----------------------------------------------------


def test_main_returns_0_with_no_args():
    assert main([]) == 0


def test_main_returns_0_when_nothing_staged(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "spiced.core.precommit_check.get_staged_files", lambda project_path: []
    )
    assert main([str(tmp_path)]) == 0


def test_main_returns_0_even_on_internal_error(monkeypatch, tmp_path):
    def boom(project_path):
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr("spiced.core.precommit_check.get_staged_files", boom)
    assert main([str(tmp_path)]) == 0


def test_main_prints_findings_for_staged_files(monkeypatch, tmp_path, capsys):
    staged = tmp_path / "Player.cs"
    staged.write_text("// TODO: finish\n", encoding="utf-8")
    monkeypatch.setattr(
        "spiced.core.precommit_check.get_staged_files", lambda project_path: [staged]
    )
    assert main([str(tmp_path)]) == 0
    captured = capsys.readouterr()
    assert "TODO" in captured.out
