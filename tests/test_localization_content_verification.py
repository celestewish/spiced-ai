"""Tests for automation.localization_content_verification (Implementation
Bible, Feature 13).

Unit tests mock ``run_stt_transcription`` at the subprocess boundary, the
same convention Feature 9 uses for its RenderDoc worker. One additional
test (``test_real_pipeline_...``) exercises the REAL pipeline end to end
-- real Windows SAPI text-to-speech generating a real WAV fixture, then a
real ``faster-whisper`` subprocess transcribing it -- matching this
codebase's stated preference (Feature 1/8) for running real pipelines over
mocks wherever practical. It's skipped automatically wherever that isn't
possible (non-Windows, no `faster-whisper` install, or no cached/
downloadable model), so the rest of the suite never depends on it."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from spiced.automation import localization_content_verification as lcv
from spiced.automation.finding import STATUS_ERROR, STATUS_FLAGGED, STATUS_PASS
from spiced.core.localization_audio_sync import ScriptLine, VoiceLineFile
from spiced.storage.automation_findings import AutomationFindingRepository
from spiced.storage.database import Database
from spiced.storage.projects import ProjectRepository

# --- normalize_text / text_similarity ----------------------------------


def test_normalize_text_lowercases_and_strips_punctuation():
    assert lcv.normalize_text("Hello, World!!") == "hello world"


def test_normalize_text_collapses_whitespace():
    assert lcv.normalize_text("  Watch   out\nfor traps.  ") == "watch out for traps"


def test_text_similarity_identical_is_one():
    assert lcv.text_similarity("Watch out for traps.", "watch out for traps") == pytest.approx(1.0)


def test_text_similarity_unrelated_is_low():
    score = lcv.text_similarity(
        "Watch out for traps in the dungeon.", "The weather forecast calls for rain tomorrow."
    )
    assert score < 0.5


# --- match_voice_to_script (reuses core.localization_audio_sync matching) --


def test_match_voice_to_script_pairs_by_inferred_line_id():
    script = [ScriptLine("line001", "Welcome, traveler.", 100.0)]
    voice = [VoiceLineFile("VO_Line001_v2.wav", 200.0)]

    matched, missing = lcv.match_voice_to_script(script, voice)

    assert len(matched) == 1
    assert matched[0].script_line.line_id == "line001"
    assert matched[0].voice_file.path == "VO_Line001_v2.wav"
    assert missing == []


def test_match_voice_to_script_reports_missing_audio():
    script = [ScriptLine("line001", "Welcome.", 100.0)]
    matched, missing = lcv.match_voice_to_script(script, [])
    assert matched == []
    assert missing == [script[0]]


def test_match_voice_to_script_picks_newest_when_duplicates():
    script = [ScriptLine("line001", "Welcome.", 100.0)]
    old = VoiceLineFile("line001_old.wav", 50.0, line_id="line001")
    new = VoiceLineFile("line001_new.wav", 500.0, line_id="line001")
    matched, _missing = lcv.match_voice_to_script(script, [old, new])
    assert matched[0].voice_file.path == "line001_new.wav"


# --- build_finding -------------------------------------------------------


def _matched(line_id="line001", script_text="Welcome, traveler."):
    return lcv.MatchedVoiceLine(
        script_line=ScriptLine(line_id, script_text, 100.0),
        voice_file=VoiceLineFile(f"{line_id}.wav", 200.0),
    )


def test_build_finding_flags_below_threshold_as_content_mismatch():
    m = _matched()
    results = [(m, lcv.STTResult(text="something completely unrelated"), 0.1)]
    finding = lcv.build_finding(results, "1", threshold=0.6)
    assert finding.status == STATUS_FLAGGED
    assert finding.items[0].detail["issue_type"] == "content_mismatch"
    assert finding.items[0].severity == "warning"


def test_build_finding_passes_at_or_above_threshold():
    m = _matched()
    results = [(m, lcv.STTResult(text="Welcome, traveler."), 0.95)]
    finding = lcv.build_finding(results, "1", threshold=0.6)
    assert finding.status == STATUS_PASS
    assert finding.items[0].detail["issue_type"] == "content_match"
    assert finding.items[0].severity == "info"


def test_build_finding_transcription_error_is_error_severity():
    m = _matched()
    results = [(m, lcv.STTResult(error="boom"), 0.0)]
    finding = lcv.build_finding(results, "1", threshold=0.6)
    assert finding.status == STATUS_ERROR
    assert finding.items[0].detail["issue_type"] == "transcription_error"


def test_build_finding_no_matches_summary():
    finding = lcv.build_finding([], "1", threshold=0.6)
    assert finding.status == STATUS_PASS
    assert "No matched" in finding.summary


# --- run_stt_transcription (subprocess boundary) --------------------------


def test_run_stt_transcription_reads_worker_stdout(monkeypatch):
    def fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps({"text": "hello there"}).encode(), stderr=b""
        )

    monkeypatch.setattr(lcv.subprocess, "run", fake_run)
    result = lcv.run_stt_transcription("line001.wav")
    assert result.succeeded
    assert result.text == "hello there"


def test_run_stt_transcription_not_available_sentinel(monkeypatch):
    def fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(command, 1, stdout=b"STT_NOT_AVAILABLE", stderr=b"")

    monkeypatch.setattr(lcv.subprocess, "run", fake_run)
    result = lcv.run_stt_transcription("line001.wav")
    assert result.succeeded is False
    assert result.stt_unavailable is True


def test_run_stt_transcription_timeout_becomes_error(monkeypatch):
    def fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(lcv.subprocess, "run", fake_run)
    result = lcv.run_stt_transcription("line001.wav", timeout_s=5)
    assert result.succeeded is False
    assert "5s" in result.error


# --- verify_localization_audio_content / run_localization_content_check ---


def test_verify_localization_audio_content_end_to_end(monkeypatch, tmp_path):
    def fake_transcribe(audio_path, *, model_size=lcv.DEFAULT_MODEL_SIZE, device="cpu",
                         python_executable=None, timeout_s=300):
        return lcv.STTResult(text="Welcome, traveler.")

    monkeypatch.setattr(lcv, "run_stt_transcription", fake_transcribe)

    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "VO_Line001.wav").write_bytes(b"fake wav data")

    script_lines = [ScriptLine("line001", "Welcome, traveler.", 0.0)]
    from spiced.core.localization_audio_sync import scan_voice_folder

    voice_files = scan_voice_folder(voice_dir)

    finding = lcv.verify_localization_audio_content(script_lines, voice_files, "1")
    assert finding.status == STATUS_PASS


def test_run_localization_content_check_uses_paste_format(monkeypatch, tmp_path):
    def fake_transcribe(audio_path, *, model_size=lcv.DEFAULT_MODEL_SIZE, device="cpu",
                         python_executable=None, timeout_s=300):
        return lcv.STTResult(text="something else entirely")

    monkeypatch.setattr(lcv, "run_stt_transcription", fake_transcribe)

    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    (voice_dir / "line001.wav").write_bytes(b"fake wav data")

    finding = lcv.run_localization_content_check(
        "line001,Welcome, traveler.", voice_dir, "1", threshold=0.6
    )
    assert finding.status == STATUS_FLAGGED
    assert finding.items[0].detail["issue_type"] == "content_mismatch"


# --- LocalizationContentVerificationService --------------------------------


def test_service_check_persists_finding(monkeypatch, tmp_path):
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = lcv.LocalizationContentVerificationService(findings)

    def fake_run(script_text, voice_folder, project_id, **kwargs):
        return lcv.Finding(
            feature_id=lcv.FEATURE_ID, project_id=project_id, status=STATUS_PASS, summary="ok"
        )

    monkeypatch.setattr(lcv, "run_localization_content_check", fake_run)

    finding, record = service.check(project, "line001,Hi", tmp_path)
    assert record.feature_id == lcv.FEATURE_ID
    assert findings.list_for_project(project.id) == [record]


def test_service_history_filters_by_feature_id():
    db = Database(":memory:")
    projects = ProjectRepository(db)
    findings = AutomationFindingRepository(db)
    project = projects.create("Moonlit Depths")
    service = lcv.LocalizationContentVerificationService(findings)
    findings.create(
        project.id,
        lcv.Finding(feature_id=lcv.FEATURE_ID, project_id=str(project.id), status=STATUS_PASS,
                    summary="a"),
    )
    findings.create(
        project.id,
        lcv.Finding(feature_id="audio.other", project_id=str(project.id), status=STATUS_PASS,
                    summary="b"),
    )
    history = service.history(project.id)
    assert len(history) == 1
    assert history[0].feature_id == lcv.FEATURE_ID


# --- CLI --------------------------------------------------------------------


def test_cli_prints_summary_and_returns_zero_on_pass(monkeypatch, tmp_path, capsys):
    def fake_run(script_text, voice_folder, project_id, **kwargs):
        return lcv.Finding(
            feature_id=lcv.FEATURE_ID, project_id=project_id, status=STATUS_PASS,
            summary="Checked 1 line(s); all match the script text.",
        )

    monkeypatch.setattr(lcv, "run_localization_content_check", fake_run)

    script_file = tmp_path / "script.txt"
    script_file.write_text("line001,Hi", encoding="utf-8")
    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()

    exit_code = lcv._cli([str(script_file), str(voice_dir)])
    out = capsys.readouterr().out
    assert exit_code == 0
    assert "all match" in out


# --- Real pipeline (Windows SAPI TTS -> real faster-whisper) --------------


def _generate_sapi_wav(text: str, output_path) -> bool:
    """Generates a real WAV file via Windows' built-in System.Speech TTS.
    Returns False (never raises) if this isn't possible in the current
    environment, so the calling test can skip cleanly."""
    if sys.platform != "win32" or shutil.which("powershell") is None:
        return False
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.SetOutputToWaveFile('{output_path}'); "
        f"$s.Speak('{text}'); $s.Dispose();"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0


def test_real_pipeline_sapi_tts_and_real_faster_whisper(tmp_path):
    pytest.importorskip("faster_whisper")

    voice_dir = tmp_path / "voice"
    voice_dir.mkdir()
    audio_path = voice_dir / "VO_Line001.wav"
    if not _generate_sapi_wav("The quick brown fox jumps over the lazy dog", audio_path):
        pytest.skip("Windows SAPI text-to-speech isn't available in this environment.")

    script_lines = [
        ScriptLine("line001", "The quick brown fox jumps over the lazy dog", 0.0),
        ScriptLine("line002", "Attack the castle gates at dawn tomorrow", 0.0),
    ]
    # Same real audio matched to both a correct and an incorrect script
    # line -- line002 has no audio of its own, so it's a "missing audio"
    # case, not a content check; instead, directly score the one real
    # transcription against both texts to exercise both outcomes for real.
    result = lcv.run_stt_transcription(str(audio_path), timeout_s=120)
    assert result.succeeded, result.error

    match_score = lcv.text_similarity(result.text, script_lines[0].text)
    mismatch_score = lcv.text_similarity(result.text, script_lines[1].text)

    assert match_score >= lcv.DEFAULT_SIMILARITY_THRESHOLD
    assert mismatch_score < lcv.DEFAULT_SIMILARITY_THRESHOLD
    assert match_score > mismatch_score
