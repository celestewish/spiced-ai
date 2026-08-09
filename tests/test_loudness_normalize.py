"""Tests for automation.loudness_normalize (Implementation Bible, Feature 1).

No real `ffmpeg`/`ffmpeg-normalize` run is required or assumed to be
installed on the test machine -- everything that would call into
`FFmpegNormalize` is monkeypatched with a fake that returns controlled
results, matching this codebase's existing convention for mocking external
process mechanisms (see tests/test_build_pipeline.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from spiced.automation import loudness_normalize as ln
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS, FindingItem
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository


class _FakeMediaFile:
    def __init__(self, *, before_i=-30.0, after_i=-23.0, status="done", error=None):
        self.status = status
        self.error = error
        self._before_i = before_i
        self._after_i = after_i

    def get_stats(self):
        yield {
            "ebu_pass1": {"input_i": self._before_i},
            "ebu_pass2": {"output_i": self._after_i},
        }


class _FakeFFmpegNormalize:
    """Stand-in for ffmpeg_normalize.FFmpegNormalize. ``outcomes`` maps
    input-file basenames to the _FakeMediaFile to return for that file; a
    class not preconfigured with ``outcomes`` (i.e. the ffmpeg-availability
    check) just succeeds at construction."""

    outcomes: dict[str, _FakeMediaFile] = {}
    raise_on_init: Exception | None = None

    def __init__(self, normalization_type="ebu", target_level=-23.0, print_stats=False):
        if self.raise_on_init is not None:
            raise self.raise_on_init
        self.target_level = target_level
        self.media_files = []
        self._pending_input = None

    def add_media_file(self, input_file, output_file):
        name = os.path.basename(input_file)
        self.media_files.append(type(self).outcomes.get(name, _FakeMediaFile()))

    def run_normalization(self):
        pass


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeFFmpegNormalize.outcomes = {}
    _FakeFFmpegNormalize.raise_on_init = None
    yield
    _FakeFFmpegNormalize.outcomes = {}
    _FakeFFmpegNormalize.raise_on_init = None


def _make_files(tmp_path, names):
    for name in names:
        (tmp_path / name).write_text("x")


# --- check_ffmpeg_available ---------------------------------------------


def test_check_ffmpeg_available_raises_when_ffmpeg_missing(monkeypatch):
    _FakeFFmpegNormalize.raise_on_init = ln.FFmpegNormalizeError("ffmpeg not found")
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    with pytest.raises(ln.FfmpegNotAvailableError):
        ln.check_ffmpeg_available()


def test_check_ffmpeg_available_passes_when_ok(monkeypatch):
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    ln.check_ffmpeg_available()  # should not raise


# --- output_dir_for -------------------------------------------------------


def test_output_dir_for_is_a_sibling_not_nested(tmp_path):
    root = tmp_path / "sfx"
    root.mkdir()
    out = ln.output_dir_for(root)
    assert out == tmp_path / "sfx_normalized"
    assert out.parent == root.parent


# --- normalize_file ---------------------------------------------------


def test_normalize_file_extracts_before_after_lufs(tmp_path, monkeypatch):
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    _FakeFFmpegNormalize.outcomes = {"a.wav": _FakeMediaFile(before_i=-30.0, after_i=-23.0)}
    src = tmp_path / "a.wav"
    src.write_text("x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = ln.normalize_file(src, out_dir, target_lufs=-23.0)

    assert result.status == "normalized"
    assert result.before_lufs == -30.0
    assert result.after_lufs == -23.0
    assert result.output_path == str(out_dir / "a.wav")


def test_normalize_file_reports_error_status(tmp_path, monkeypatch):
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    _FakeFFmpegNormalize.outcomes = {
        "bad.wav": _FakeMediaFile(status="error", error="not a valid audio stream")
    }
    src = tmp_path / "bad.wav"
    src.write_text("x")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    result = ln.normalize_file(src, out_dir)

    assert result.status == "error"
    assert result.error == "not a valid audio stream"
    assert result.before_lufs is None


# --- _to_finding_item / _summarize (pure) ---------------------------------


def test_to_finding_item_flags_off_target_as_warning():
    result = ln.LoudnessResult(
        input_path="a.wav",
        output_path="out/a.wav",
        before_lufs=-30.0,
        after_lufs=-20.0,  # 3 LUFS off a -23 target -- outside tolerance
        target_lufs=-23.0,
        status="normalized",
    )
    item = ln._to_finding_item(result)
    assert item.severity == "warning"


def test_to_finding_item_within_tolerance_is_info():
    result = ln.LoudnessResult(
        input_path="a.wav",
        output_path="out/a.wav",
        before_lufs=-30.0,
        after_lufs=-23.2,
        target_lufs=-23.0,
        status="normalized",
    )
    item = ln._to_finding_item(result)
    assert item.severity == "info"


def test_to_finding_item_error_result_is_error_severity():
    result = ln.LoudnessResult(
        input_path="bad.wav",
        output_path="out/bad.wav",
        before_lufs=None,
        after_lufs=None,
        target_lufs=-23.0,
        status="error",
        error="boom",
    )
    item = ln._to_finding_item(result)
    assert item.severity == "error"
    assert "boom" in item.message


def test_summarize_no_files():
    assert ln._summarize([], 0) == "No audio files found to normalize."


def test_summarize_all_clean():
    items = [FindingItem(asset_path="a", severity="info", message="x")]
    assert "1 file(s)" in ln._summarize(items, 1)


# --- normalize_folder (BatchRunner wiring) --------------------------------


def test_normalize_folder_filters_extensions_and_writes_to_sibling_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    root = tmp_path / "sfx"
    root.mkdir()
    _make_files(root, ["a.wav", "b.mp3", "c.txt"])
    _FakeFFmpegNormalize.outcomes = {
        "a.wav": _FakeMediaFile(before_i=-30.0, after_i=-23.0),
        "b.mp3": _FakeMediaFile(before_i=-18.0, after_i=-23.0),
    }

    finding = ln.normalize_folder(root, project_id="7", target_lufs=-23.0)

    assert finding.status == STATUS_PASS
    assert {Path(i.asset_path).name for i in finding.items} == {"a.wav", "b.mp3"}
    assert (tmp_path / "sfx_normalized").is_dir()


def test_normalize_folder_raises_before_touching_files_when_ffmpeg_missing(tmp_path, monkeypatch):
    _FakeFFmpegNormalize.raise_on_init = ln.FFmpegNormalizeError("nope")
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    root = tmp_path / "sfx"
    root.mkdir()
    _make_files(root, ["a.wav"])

    with pytest.raises(ln.FfmpegNotAvailableError):
        ln.normalize_folder(root, project_id="1")

    assert not (tmp_path / "sfx_normalized").exists()


def test_normalize_folder_status_flagged_when_off_target(tmp_path, monkeypatch):
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    root = tmp_path / "sfx"
    root.mkdir()
    _make_files(root, ["loud.wav"])
    _FakeFFmpegNormalize.outcomes = {"loud.wav": _FakeMediaFile(before_i=-10.0, after_i=-15.0)}

    finding = ln.normalize_folder(root, project_id="1", target_lufs=-23.0)
    assert finding.status == STATUS_FLAGGED


def test_normalize_folder_status_error_when_a_file_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ln, "FFmpegNormalize", _FakeFFmpegNormalize)
    root = tmp_path / "sfx"
    root.mkdir()
    _make_files(root, ["bad.wav"])
    _FakeFFmpegNormalize.outcomes = {"bad.wav": _FakeMediaFile(status="error", error="broken")}

    finding = ln.normalize_folder(root, project_id="1")
    assert finding.status == STATUS_ERROR


# --- LoudnessNormalizeService ----------------------------------------------


def test_service_uses_default_target_when_project_has_none(tmp_path, monkeypatch):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = ln.LoudnessNormalizeService(findings)

    captured = {}

    def fake_normalize_folder(root_dir, project_id, target_lufs=ln.DEFAULT_TARGET_LUFS):
        captured["target_lufs"] = target_lufs
        return ln.Finding(
            feature_id=ln.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(ln, "normalize_folder", fake_normalize_folder)

    finding, record = service.normalize(project, tmp_path)

    assert captured["target_lufs"] == ln.DEFAULT_TARGET_LUFS
    assert record.feature_id == ln.FEATURE_ID
    assert findings.list_for_project(project.id) == [record]


def test_service_uses_project_specific_target(tmp_path, monkeypatch):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    project = projects.set_loudness_normalize_target(project.id, -16.0)
    service = ln.LoudnessNormalizeService(findings)

    captured = {}

    def fake_normalize_folder(root_dir, project_id, target_lufs=ln.DEFAULT_TARGET_LUFS):
        captured["target_lufs"] = target_lufs
        return ln.Finding(
            feature_id=ln.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(ln, "normalize_folder", fake_normalize_folder)
    service.normalize(project, tmp_path)

    assert captured["target_lufs"] == -16.0


def test_service_explicit_target_overrides_project_setting(tmp_path, monkeypatch):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    project = projects.set_loudness_normalize_target(project.id, -16.0)
    service = ln.LoudnessNormalizeService(findings)

    captured = {}

    def fake_normalize_folder(root_dir, project_id, target_lufs=ln.DEFAULT_TARGET_LUFS):
        captured["target_lufs"] = target_lufs
        return ln.Finding(
            feature_id=ln.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(ln, "normalize_folder", fake_normalize_folder)
    service.normalize(project, tmp_path, target_lufs=-20.0)

    assert captured["target_lufs"] == -20.0


def test_service_history_filters_by_feature_id(tmp_path, monkeypatch):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = ln.LoudnessNormalizeService(findings)
    findings.create(
        project.id,
        ln.Finding(
            feature_id=ln.FEATURE_ID,
            project_id=str(project.id),
            status=STATUS_PASS,
            summary="a",
        ),
    )
    findings.create(
        project.id,
        ln.Finding(
            feature_id="vfx.visual_regression",
            project_id=str(project.id),
            status=STATUS_PASS,
            summary="b",
        ),
    )

    history = service.history(project.id)

    assert len(history) == 1
    assert history[0].feature_id == ln.FEATURE_ID


# --- CLI ---------------------------------------------------------------


def test_cli_prints_summary_and_returns_zero_on_pass(tmp_path, monkeypatch, capsys):
    def fake_normalize_folder(root_dir, project_id, target_lufs=ln.DEFAULT_TARGET_LUFS):
        return ln.Finding(
            feature_id=ln.FEATURE_ID,
            project_id=project_id,
            status=STATUS_PASS,
            summary="Normalized 1 file(s) to target.",
        )

    monkeypatch.setattr(ln, "normalize_folder", fake_normalize_folder)
    exit_code = ln._cli([str(tmp_path)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "Normalized 1 file(s) to target." in out


def test_cli_json_flag_prints_finding_dict(tmp_path, monkeypatch, capsys):
    def fake_normalize_folder(root_dir, project_id, target_lufs=ln.DEFAULT_TARGET_LUFS):
        return ln.Finding(
            feature_id=ln.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(ln, "normalize_folder", fake_normalize_folder)
    exit_code = ln._cli([str(tmp_path), "--json"])
    out = capsys.readouterr().out
    assert exit_code == 0
    parsed = json.loads(out)
    assert parsed["feature_id"] == ln.FEATURE_ID


def test_cli_reports_ffmpeg_missing_cleanly(tmp_path, monkeypatch, capsys):
    def raise_missing(root_dir, project_id, target_lufs=ln.DEFAULT_TARGET_LUFS):
        raise ln.FfmpegNotAvailableError("no ffmpeg on PATH")

    monkeypatch.setattr(ln, "normalize_folder", raise_missing)
    exit_code = ln._cli([str(tmp_path)])
    err = capsys.readouterr().err
    assert exit_code == 1
    assert "no ffmpeg on PATH" in err
