"""Tests for automation.batch_runner.BatchRunner: the shared "walk a
directory, filter by extension, run a per-file callback, collect results"
utility (SPICED_IMPLEMENTATION_BIBLE.md, section 0)."""

from __future__ import annotations

from spiced.automation.batch_runner import BatchRunner
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS, FindingItem


def _make_files(tmp_path, names):
    for name in names:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")


def test_iter_files_filters_by_extension(tmp_path):
    _make_files(tmp_path, ["a.wav", "b.mp3", "c.txt"])
    runner = BatchRunner("audio.test", extensions=[".wav", ".mp3"])
    files = runner.iter_files(tmp_path)
    assert {f.name for f in files} == {"a.wav", "b.mp3"}


def test_iter_files_recursive_by_default(tmp_path):
    _make_files(tmp_path, ["top.wav", "nested/deep.wav"])
    runner = BatchRunner("audio.test", extensions=[".wav"])
    files = runner.iter_files(tmp_path)
    assert {f.name for f in files} == {"top.wav", "deep.wav"}


def test_iter_files_non_recursive(tmp_path):
    _make_files(tmp_path, ["top.wav", "nested/deep.wav"])
    runner = BatchRunner("audio.test", extensions=[".wav"], recursive=False)
    files = runner.iter_files(tmp_path)
    assert {f.name for f in files} == {"top.wav"}


def test_iter_files_missing_dir_returns_empty(tmp_path):
    runner = BatchRunner("audio.test")
    assert runner.iter_files(tmp_path / "does_not_exist") == []


def test_run_collects_items_and_rolls_up_status(tmp_path):
    _make_files(tmp_path, ["ok.wav", "loud.wav"])
    runner = BatchRunner("audio.test", extensions=[".wav"])

    def callback(path):
        if path.name == "loud.wav":
            return FindingItem(asset_path=str(path), severity="warning", message="too loud")
        return None

    finding = runner.run(tmp_path, project_id="7", callback=callback)
    assert finding.status == STATUS_FLAGGED
    assert finding.feature_id == "audio.test"
    assert finding.project_id == "7"
    assert len(finding.items) == 1
    assert finding.items[0].asset_path == str(tmp_path / "loud.wav")


def test_run_callback_exception_becomes_error_item_not_a_crash(tmp_path):
    _make_files(tmp_path, ["good.wav", "corrupt.wav"])
    runner = BatchRunner("audio.test", extensions=[".wav"])

    def callback(path):
        if path.name == "corrupt.wav":
            raise ValueError("bad header")
        return None

    finding = runner.run(tmp_path, project_id="1", callback=callback)
    assert finding.status == STATUS_ERROR
    assert len(finding.items) == 1
    assert "bad header" in finding.items[0].message


def test_run_callback_can_return_multiple_items(tmp_path):
    _make_files(tmp_path, ["a.wav"])
    runner = BatchRunner("audio.test", extensions=[".wav"])

    def callback(path):
        return [
            FindingItem(asset_path=str(path), severity="info", message="one"),
            FindingItem(asset_path=str(path), severity="info", message="two"),
        ]

    finding = runner.run(tmp_path, project_id="1", callback=callback)
    assert len(finding.items) == 2
    assert finding.status == STATUS_PASS


def test_run_no_matching_files_passes_with_default_summary(tmp_path):
    runner = BatchRunner("audio.test", extensions=[".wav"])
    finding = runner.run(tmp_path, project_id="1", callback=lambda p: None)
    assert finding.status == STATUS_PASS
    assert finding.summary == "No matching files found."


def test_run_custom_summary_fn(tmp_path):
    _make_files(tmp_path, ["a.wav"])
    runner = BatchRunner(
        "audio.test",
        extensions=[".wav"],
        summary_fn=lambda items, count: f"custom:{count}",
    )
    finding = runner.run(tmp_path, project_id="1", callback=lambda p: None)
    assert finding.summary == "custom:1"
