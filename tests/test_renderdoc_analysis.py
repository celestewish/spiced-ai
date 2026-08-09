"""Tests for connectors.renderdoc_analysis (Implementation Bible, Feature 9).
Mocks subprocess.run, the same convention as the Unity connector tests --
no real RenderDoc install is required (see that module's docstring for why
one couldn't be verified against in this environment either way)."""

from __future__ import annotations

import json
import subprocess

from spiced.connectors import renderdoc_analysis as rda


def test_analyze_capture_parses_result(monkeypatch):
    def fake_run(command, timeout, capture_output):
        stdout = json.dumps(
            {
                "shaders": [
                    {
                        "shader_name": "Toon/Outline",
                        "gpu_time_ms": 1.23,
                        "texture_bandwidth_bytes": 4096,
                        "draw_call_count": 3,
                    }
                ]
            }
        ).encode("utf-8")
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(rda.subprocess, "run", fake_run)

    result = rda.analyze_capture("capture.rdc", "C:\\RenderDoc\\pymodules")

    assert result.error is None
    assert len(result.stats) == 1
    assert result.stats[0].shader_name == "Toon/Outline"
    assert result.stats[0].gpu_time_ms == 1.23


def test_analyze_capture_renderdoc_not_available(monkeypatch):
    def fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(
            command, 1, stdout=b"RENDERDOC_NOT_AVAILABLE\n", stderr=b""
        )

    monkeypatch.setattr(rda.subprocess, "run", fake_run)

    result = rda.analyze_capture("capture.rdc", "C:\\bad\\path")

    assert result.renderdoc_unavailable is True
    assert result.error is not None
    assert "RenderDoc" in result.error


def test_analyze_capture_generic_failure(monkeypatch):
    def fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(
            command, 1, stdout=b"", stderr=b"could not open capture file"
        )

    monkeypatch.setattr(rda.subprocess, "run", fake_run)

    result = rda.analyze_capture("capture.rdc", "C:\\RenderDoc\\pymodules")

    assert result.error is not None
    assert "could not open capture file" in result.error
    assert result.renderdoc_unavailable is False


def test_analyze_capture_timeout(monkeypatch):
    def fake_run(command, timeout, capture_output):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(rda.subprocess, "run", fake_run)

    result = rda.analyze_capture("capture.rdc", "C:\\RenderDoc\\pymodules", timeout_s=5)

    assert result.error is not None
    assert "timed out" in result.error


def test_analyze_capture_unlaunchable(monkeypatch):
    def fake_run(command, timeout, capture_output):
        raise OSError("not found")

    monkeypatch.setattr(rda.subprocess, "run", fake_run)

    result = rda.analyze_capture("capture.rdc", "C:\\RenderDoc\\pymodules")

    assert "Could not launch" in result.error


def test_analyze_capture_unreadable_output(monkeypatch):
    def fake_run(command, timeout, capture_output):
        return subprocess.CompletedProcess(command, 0, stdout=b"not json", stderr=b"")

    monkeypatch.setattr(rda.subprocess, "run", fake_run)

    result = rda.analyze_capture("capture.rdc", "C:\\RenderDoc\\pymodules")

    assert result.error is not None
