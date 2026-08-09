"""Tests for connectors.unity_visual_capture: the headless Unity capture
mechanism (Implementation Bible, Feature 2). Mocks subprocess.run, the same
convention tests/test_build_pipeline.py and unity_build use for other
engine-automation mechanisms -- no real Unity install is required or
assumed."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from spiced.connectors import unity_visual_capture as uvc


def test_ensure_capture_script_writes_file(tmp_path):
    path = uvc.ensure_capture_script(tmp_path)
    assert Path(path).is_file()
    assert Path(path) == tmp_path / "Assets" / "Editor" / "SpicedVisualCaptureScript.cs"
    content = Path(path).read_text(encoding="utf-8")
    assert "SpicedVisualCaptureScript" in content
    assert "PerformCapture" in content


def test_ensure_capture_script_overwrites_existing(tmp_path):
    editor_dir = tmp_path / "Assets" / "Editor"
    editor_dir.mkdir(parents=True)
    script_path = editor_dir / "SpicedVisualCaptureScript.cs"
    script_path.write_text("// stale hand-edit", encoding="utf-8")

    uvc.ensure_capture_script(tmp_path)

    assert "PerformCapture" in script_path.read_text(encoding="utf-8")


def _fake_run_writing_result(result_data: dict, log_text: str = "log line\n"):
    def _fake_run(command, timeout, capture_output):
        # The result/log file paths are positional args after -spicedResultFile / -logFile.
        result_path = Path(command[command.index("-spicedResultFile") + 1])
        log_path = Path(command[command.index("-logFile") + 1])
        result_path.write_text(json.dumps(result_data), encoding="utf-8")
        log_path.write_text(log_text, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    return _fake_run


def test_run_capture_parses_result_file(tmp_path, monkeypatch):
    monkeypatch.setattr(
        uvc.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "captures": [
                    {
                        "scene_path": "Assets/Scenes/Main.unity",
                        "success": True,
                        "error": None,
                        "output_path": str(tmp_path / "main.png"),
                    }
                ],
            }
        ),
    )
    requests = [
        uvc.SceneCaptureRequest(
            scene_path="Assets/Scenes/Main.unity",
            marker_name="SpicedCapture_MainHall",
            output_path=str(tmp_path / "main.png"),
        )
    ]

    result = uvc.run_capture("C:\\Unity\\Unity.exe", str(tmp_path), requests)

    assert result.error is None
    assert result.timed_out is False
    assert len(result.outcomes) == 1
    assert result.outcomes[0].succeeded is True
    assert result.outcomes[0].scene_path == "Assets/Scenes/Main.unity"


def test_run_capture_reports_per_scene_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        uvc.subprocess,
        "run",
        _fake_run_writing_result(
            {
                "run_error": None,
                "captures": [
                    {
                        "scene_path": "Assets/Scenes/Broken.unity",
                        "success": False,
                        "error": "No GameObject named 'Missing' found",
                        "output_path": str(tmp_path / "broken.png"),
                    }
                ],
            }
        ),
    )
    requests = [
        uvc.SceneCaptureRequest(
            scene_path="Assets/Scenes/Broken.unity",
            marker_name="Missing",
            output_path=str(tmp_path / "broken.png"),
        )
    ]

    result = uvc.run_capture("C:\\Unity\\Unity.exe", str(tmp_path), requests)

    assert result.error is None  # whole run didn't fail
    assert result.outcomes[0].succeeded is False
    assert "Missing" in result.outcomes[0].error


def test_run_capture_no_result_file_is_a_run_error(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(command, 1)  # never wrote a result file

    monkeypatch.setattr(uvc.subprocess, "run", _fake_run)
    requests = [
        uvc.SceneCaptureRequest(
            scene_path="Assets/Scenes/Main.unity",
            marker_name="Marker",
            output_path=str(tmp_path / "main.png"),
        )
    ]

    result = uvc.run_capture("C:\\Unity\\Unity.exe", str(tmp_path), requests)

    assert result.error is not None
    assert "exited without writing" in result.error
    assert result.outcomes == []


def test_run_capture_timeout(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(uvc.subprocess, "run", _fake_run)
    requests = [
        uvc.SceneCaptureRequest(
            scene_path="Assets/Scenes/Main.unity",
            marker_name="Marker",
            output_path=str(tmp_path / "main.png"),
        )
    ]

    result = uvc.run_capture(
        "C:\\Unity\\Unity.exe", str(tmp_path), requests, timeout_s=5
    )

    assert result.timed_out is True
    assert result.error is not None


def test_run_capture_unity_not_launchable(tmp_path, monkeypatch):
    def _fake_run(command, timeout, capture_output):
        raise OSError("not found")

    monkeypatch.setattr(uvc.subprocess, "run", _fake_run)
    requests = [
        uvc.SceneCaptureRequest(
            scene_path="Assets/Scenes/Main.unity",
            marker_name="Marker",
            output_path=str(tmp_path / "main.png"),
        )
    ]

    result = uvc.run_capture("C:\\nonexistent\\Unity.exe", str(tmp_path), requests)

    assert "Could not launch Unity" in result.error


def test_run_capture_ensures_script_before_running(tmp_path, monkeypatch):
    calls = []

    def _fake_run(command, timeout, capture_output):
        calls.append(command)
        result_path = Path(command[command.index("-spicedResultFile") + 1])
        result_path.write_text(json.dumps({"run_error": None, "captures": []}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(uvc.subprocess, "run", _fake_run)
    uvc.run_capture("C:\\Unity\\Unity.exe", str(tmp_path), [])

    script_path = tmp_path / "Assets" / "Editor" / "SpicedVisualCaptureScript.cs"
    assert script_path.is_file()
    assert len(calls) == 1
    assert "-nographics" not in calls[0]  # rendering needs a graphics device
