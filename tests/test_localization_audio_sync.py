"""Tests for core.localization_audio_sync: the staleness/coverage heuristic."""

from __future__ import annotations

import os
import time

from spiced.core.localization_audio_sync import (
    ScriptLine,
    VoiceLineFile,
    infer_line_id_from_filename,
    parse_script_lines,
    scan_localization_audio_sync,
    scan_voice_folder,
)


def test_infers_line_id_from_common_filename_convention():
    assert infer_line_id_from_filename("VO_Line042_v2.wav") == "line042"
    assert infer_line_id_from_filename("Line_7.mp3") == "line7"


def test_infer_line_id_returns_none_for_non_matching_filename():
    assert infer_line_id_from_filename("footstep_grass_01.wav") is None


def test_flags_stale_recording_when_audio_older_than_script_edit():
    now = time.time()
    script = [ScriptLine(line_id="line001", text="Updated line text", last_modified=now)]
    voice = [VoiceLineFile(path="VO_Line001.wav", last_modified=now - 3600, line_id=None)]

    result = scan_localization_audio_sync(script, voice)
    assert len(result.stale_recordings) == 1
    assert result.stale_recordings[0].line_id == "line001"
    assert result.missing_audio == []


def test_does_not_flag_recording_newer_than_script_edit():
    now = time.time()
    script = [ScriptLine(line_id="line001", text="Original text", last_modified=now - 3600)]
    voice = [VoiceLineFile(path="VO_Line001.wav", last_modified=now, line_id=None)]

    result = scan_localization_audio_sync(script, voice)
    assert result.stale_recordings == []


def test_flags_missing_audio_for_script_line_with_no_match():
    now = time.time()
    script = [ScriptLine(line_id="line002", text="No recording exists yet", last_modified=now)]
    result = scan_localization_audio_sync(script, [])
    assert len(result.missing_audio) == 1
    assert result.missing_audio[0].line_id == "line002"


def test_unmatched_audio_file_reported_separately():
    now = time.time()
    voice = [VoiceLineFile(path="random_grunt.wav", last_modified=now, line_id=None)]
    result = scan_localization_audio_sync([], voice)
    assert "random_grunt.wav" in result.unmatched_audio_files
    assert result.stale_recordings == []
    assert result.missing_audio == []


def test_dev_supplied_line_id_overrides_filename_inference():
    now = time.time()
    script = [ScriptLine(line_id="custom42", text="Text", last_modified=now)]
    voice = [VoiceLineFile(path="weird_filename.wav", last_modified=now - 10, line_id="custom42")]
    result = scan_localization_audio_sync(script, voice)
    assert len(result.stale_recordings) == 1


def test_parse_script_lines_basic_format():
    text = "line001,Hello there\nline002,Watch out!\nnot a valid line\n"
    lines = parse_script_lines(text, last_modified=123.0)
    assert len(lines) == 2
    assert lines[0].line_id == "line001"
    assert lines[0].text == "Hello there"
    assert lines[0].last_modified == 123.0


def test_scan_voice_folder_finds_audio_files(tmp_path):
    (tmp_path / "VO_Line001.wav").write_bytes(b"\0")
    (tmp_path / "notes.txt").write_text("not audio")
    files = scan_voice_folder(tmp_path)
    assert len(files) == 1
    assert files[0].path.endswith("VO_Line001.wav")


def test_scan_voice_folder_missing_folder_returns_empty():
    assert scan_voice_folder(os.path.join("does", "not", "exist")) == []


def test_caveat_states_content_cannot_be_verified():
    now = time.time()
    result = scan_localization_audio_sync(
        [ScriptLine("line001", "text", now)],
        [VoiceLineFile("VO_Line001.wav", now, None)],
    )
    assert "cannot" in result.caveat.lower()
