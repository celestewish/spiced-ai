"""Tests for automation.mix_technical_qa (Implementation Bible, Feature 5).
Synthetic WAV data generated in-memory via the stdlib `wave` module, same
convention as tests/test_mix_level_qa.py -- no real audio fixtures needed."""

from __future__ import annotations

import array
import math
import wave

import pytest

from spiced.automation import mix_technical_qa as mtq
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS
from spiced.core.mix_level_qa import UnsupportedWavError
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

SAMPLE_RATE = 8000


def _write_wav(path, samples: list[int], *, rate: int = SAMPLE_RATE):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        arr = array.array("h", samples)
        wf.writeframes(arr.tobytes())


def _sine(duration_seconds: float, amplitude: int, rate: int = SAMPLE_RATE) -> list[int]:
    n = int(duration_seconds * rate)
    return [int(amplitude * math.sin(2 * math.pi * 220 * i / rate)) for i in range(n)]


# --- find_clipping_regions -------------------------------------------------


def test_find_clipping_regions_detects_a_run():
    samples = [0] * 100 + [32767] * 10 + [0] * 100
    regions = mtq.find_clipping_regions(samples, SAMPLE_RATE, 32767)
    assert len(regions) == 1
    assert regions[0].start_ms == pytest.approx(100 / SAMPLE_RATE * 1000, abs=0.1)
    assert regions[0].end_ms == pytest.approx(110 / SAMPLE_RATE * 1000, abs=0.1)


def test_find_clipping_regions_ignores_short_runs():
    samples = [0] * 100 + [32767] * 2 + [0] * 100  # shorter than min_run_samples default (3)
    assert mtq.find_clipping_regions(samples, SAMPLE_RATE, 32767) == []


def test_find_clipping_regions_trailing_run_included():
    samples = [0] * 50 + [32767] * 10
    regions = mtq.find_clipping_regions(samples, SAMPLE_RATE, 32767)
    assert len(regions) == 1


def test_find_clipping_regions_empty_samples():
    assert mtq.find_clipping_regions([], SAMPLE_RATE, 32767) == []


def test_find_clipping_regions_normal_audio_no_flags():
    samples = _sine(1.0, amplitude=10000)
    assert mtq.find_clipping_regions(samples, SAMPLE_RATE, 32767) == []


# --- find_silence_regions ---------------------------------------------------


def test_find_silence_regions_detects_mid_file_gap():
    tone = _sine(0.5, amplitude=15000)
    silence = [0] * int(0.5 * SAMPLE_RATE)  # 500ms, > default 300ms threshold
    samples = tone + silence + tone

    regions = mtq.find_silence_regions(samples, SAMPLE_RATE, 32767)

    assert len(regions) == 1
    assert regions[0].start_ms == pytest.approx(500, abs=5)


def test_find_silence_regions_excludes_leading_silence():
    silence = [0] * int(0.5 * SAMPLE_RATE)
    tone = _sine(0.5, amplitude=15000)
    samples = silence + tone  # silence at the very start

    assert mtq.find_silence_regions(samples, SAMPLE_RATE, 32767) == []


def test_find_silence_regions_excludes_trailing_silence():
    tone = _sine(0.5, amplitude=15000)
    silence = [0] * int(0.5 * SAMPLE_RATE)
    samples = tone + silence  # silence extending to the very end

    assert mtq.find_silence_regions(samples, SAMPLE_RATE, 32767) == []


def test_find_silence_regions_below_threshold_not_flagged():
    tone = _sine(0.5, amplitude=15000)
    short_silence = [0] * int(0.05 * SAMPLE_RATE)  # 50ms, below default 300ms
    samples = tone + short_silence + tone

    assert mtq.find_silence_regions(samples, SAMPLE_RATE, 32767) == []


def test_find_silence_regions_configurable_threshold():
    tone = _sine(0.5, amplitude=15000)
    short_silence = [0] * int(0.05 * SAMPLE_RATE)  # 50ms
    samples = tone + short_silence + tone

    regions = mtq.find_silence_regions(samples, SAMPLE_RATE, 32767, min_silence_ms=20.0)

    assert len(regions) == 1


# --- check_mix_technical_qa (Bible acceptance criteria) ---------------------


def test_check_mix_technical_qa_clean_file_is_info(tmp_path):
    p = tmp_path / "clean.wav"
    _write_wav(p, _sine(1.0, amplitude=10000))

    item = mtq.check_mix_technical_qa(p)

    assert item.severity == "info"


def test_check_mix_technical_qa_clipped_file_is_flagged(tmp_path):
    samples = [32767] * (SAMPLE_RATE // 2) + [-32768] * (SAMPLE_RATE // 2)
    p = tmp_path / "clipped.wav"
    _write_wav(p, samples)

    item = mtq.check_mix_technical_qa(p)

    assert item.severity == "warning"
    assert len(item.detail["clipping_regions"]) >= 1


def test_check_mix_technical_qa_silence_gap_file_is_flagged(tmp_path):
    tone = _sine(1.0, amplitude=15000)
    silence = [0] * int(1.0 * SAMPLE_RATE)
    samples = tone + silence + tone
    p = tmp_path / "gappy.wav"
    _write_wav(p, samples)

    item = mtq.check_mix_technical_qa(p)

    assert item.severity == "warning"
    assert len(item.detail["silence_regions"]) == 1


def test_check_mix_technical_qa_unsupported_file_raises(tmp_path):
    p = tmp_path / "not_a_wav.wav"
    p.write_text("not audio", encoding="utf-8")
    with pytest.raises(UnsupportedWavError):  # propagated for BatchRunner to catch
        mtq.check_mix_technical_qa(p)


# --- scan_folder_for_mix_qa (BatchRunner wiring) ----------------------------


def test_scan_folder_for_mix_qa(tmp_path):
    _write_wav(tmp_path / "clean.wav", _sine(1.0, amplitude=10000))
    samples = [32767] * (SAMPLE_RATE // 2) + [-32768] * (SAMPLE_RATE // 2)
    _write_wav(tmp_path / "clipped.wav", samples)
    (tmp_path / "notes.txt").write_text("not audio", encoding="utf-8")

    finding = mtq.scan_folder_for_mix_qa(tmp_path, project_id="1")

    assert finding.status == STATUS_FLAGGED
    by_name = {i.asset_path.split("\\")[-1].split("/")[-1]: i for i in finding.items}
    assert by_name["clean.wav"].severity == "info"
    assert by_name["clipped.wav"].severity == "warning"
    assert "notes.txt" not in by_name


def test_scan_folder_for_mix_qa_all_clean_passes(tmp_path):
    _write_wav(tmp_path / "a.wav", _sine(1.0, amplitude=10000))
    finding = mtq.scan_folder_for_mix_qa(tmp_path, project_id="1")
    assert finding.status == STATUS_PASS


def test_scan_folder_for_mix_qa_unreadable_file_is_error(tmp_path):
    p = tmp_path / "bad.wav"
    p.write_text("not audio", encoding="utf-8")

    finding = mtq.scan_folder_for_mix_qa(tmp_path, project_id="1")

    assert finding.status == STATUS_ERROR


def test_scan_folder_for_mix_qa_no_files():
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        finding = mtq.scan_folder_for_mix_qa(d, project_id="1")
    assert finding.status == STATUS_PASS
    assert finding.summary == "No WAV files found to check."


# --- MixTechnicalQaService --------------------------------------------------


def _setup_service():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    service = mtq.MixTechnicalQaService(findings)
    project = projects.create("Moonlit Depths")
    return service, projects, project


def test_service_uses_default_silence_threshold(tmp_path):
    service, _projects, project = _setup_service()
    _write_wav(tmp_path / "a.wav", _sine(1.0, amplitude=10000))

    finding, record = service.scan(project, tmp_path)

    assert record.feature_id == mtq.FEATURE_ID


def test_service_uses_project_silence_threshold(tmp_path):
    service, projects, project = _setup_service()
    project = projects.set_mix_qa_silence_ms(project.id, 20.0)
    tone = _sine(0.5, amplitude=15000)
    short_silence = [0] * int(0.05 * SAMPLE_RATE)  # 50ms -- above the 20ms project setting
    _write_wav(tmp_path / "a.wav", tone + short_silence + tone)

    finding, _record = service.scan(project, tmp_path)

    assert finding.status == STATUS_FLAGGED


def test_service_history(tmp_path):
    service, _projects, project = _setup_service()
    _write_wav(tmp_path / "a.wav", _sine(1.0, amplitude=10000))
    finding, record = service.scan(project, tmp_path)
    assert service.history(project.id) == [record]


# --- CLI ---------------------------------------------------------------


def test_cli_prints_summary(tmp_path, capsys):
    _write_wav(tmp_path / "a.wav", _sine(1.0, amplitude=10000))

    exit_code = mtq._cli([str(tmp_path)])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "no clipping or silence issues found" in out


def test_cli_json_flag(tmp_path, capsys):
    import json

    _write_wav(tmp_path / "a.wav", _sine(1.0, amplitude=10000))

    exit_code = mtq._cli([str(tmp_path), "--json"])

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert exit_code == 0
    assert parsed["feature_id"] == mtq.FEATURE_ID
