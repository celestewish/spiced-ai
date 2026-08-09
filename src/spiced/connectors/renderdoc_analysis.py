"""Shader Performance Profiling mechanism: RenderDoc capture analysis
(Implementation Bible, Feature 9).

**Not verified against a real RenderDoc install.** Every other engine
connector this project built (Unity's ``-executeMethod`` scripts,
``ShaderUtil.GetVariantCount``) was checked against either a real sample
file or a real, working install. No RenderDoc install was available in this
environment (and GPU frame capture likely wouldn't function in this kind of
sandboxed environment even with one installed -- it needs a real GPU
context). The Python API calls below (``renderdoc.OpenCaptureFile`` /
``ReplayController.GetDrawcalls`` / ``FetchCounters`` with
``GPUCounter.EventGPUDuration``) match RenderDoc's own published API
reference (https://renderdoc.org/docs/python_api/index.html, which the
Bible itself cites) as closely as this project could determine without a
capture to test against -- treat this as a documented best effort, not a
confirmed-working integration. Verify it against a real ``.rdc`` file
before relying on it.

**Scope decision**: analyzes an EXISTING ``.rdc`` capture file rather than
automating the capture step. The Bible's step 1 ("automate a RenderDoc
capture... reusing the camera-move hook from Feature 2") would need a
*runtime* script baked into the game's own built player -- RenderDoc
captures a running standalone process, not the Unity Editor, so
``unity_visual_capture``'s Editor-batchmode ``-executeMethod`` approach
doesn't carry over. That's a substantially larger, separate mechanism
(build a player with a capture-trigger hook linked against RenderDoc's
in-application API, launch it under ``renderdoccmd capture``, trigger at
the right frame) that this project could not build *and verify* here
either. Point this at a capture you already made -- RenderDoc's own UI, or
your own launch-and-capture wrapper -- instead.

Runs in a subprocess, like ``uv_lod_generation``'s xatlas worker: RenderDoc's
native ``renderdoc`` module is exactly the kind of binding that can crash
outside Python's control, and it needs its own matching-ABI Python
interpreter with RenderDoc's ``pymodules`` directory on ``sys.path`` --
almost certainly not the same interpreter running Spiced itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TIMEOUT_S = 300


class RenderDocNotAvailableError(RuntimeError):
    """Raised when the `renderdoc` module can't be imported (not installed,
    wrong pymodules path, or a Python ABI mismatch)."""


class CaptureAnalysisError(RuntimeError):
    """Raised when the capture file itself can't be opened/analyzed."""


@dataclass(frozen=True)
class ShaderGpuStats:
    shader_name: str
    gpu_time_ms: float
    texture_bandwidth_bytes: int
    draw_call_count: int


@dataclass(frozen=True)
class CaptureAnalysisResult:
    stats: list[ShaderGpuStats] = field(default_factory=list)
    error: str | None = None
    renderdoc_unavailable: bool = False


def analyze_capture(
    rdc_path: str | Path,
    renderdoc_pymodules_path: str | Path,
    *,
    python_executable: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> CaptureAnalysisResult:
    """Analyze one ``.rdc`` capture file in a subprocess, aggregating GPU
    time/bandwidth/draw-call-count per shader."""
    python_exe = python_executable or sys.executable
    command = [
        python_exe,
        "-m",
        "spiced.connectors._renderdoc_worker",
        str(rdc_path),
        str(renderdoc_pymodules_path),
    ]

    try:
        completed = subprocess.run(command, timeout=timeout_s, capture_output=True)
    except subprocess.TimeoutExpired:
        return CaptureAnalysisResult(
            error=f"RenderDoc capture analysis timed out after {timeout_s}s."
        )
    except OSError as exc:
        return CaptureAnalysisResult(error=f"Could not launch the analysis worker: {exc}")

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr_tail = completed.stderr.decode("utf-8", errors="replace")[-2000:]

    if completed.returncode != 0:
        if "RENDERDOC_NOT_AVAILABLE" in stdout:
            return CaptureAnalysisResult(
                error=(
                    "RenderDoc's Python module couldn't be imported. Check that RenderDoc is "
                    "installed and that the pymodules path points at its `pymodules` directory "
                    f"with a matching Python version. {stderr_tail}".strip()
                ),
                renderdoc_unavailable=True,
            )
        return CaptureAnalysisResult(
            error=(
                f"Capture analysis failed (exit code {completed.returncode}). {stderr_tail}"
            ).strip()
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return CaptureAnalysisResult(
            error=f"Capture analysis produced unreadable output. {stderr_tail}".strip()
        )

    stats = [
        ShaderGpuStats(
            shader_name=s["shader_name"],
            gpu_time_ms=s["gpu_time_ms"],
            texture_bandwidth_bytes=s["texture_bandwidth_bytes"],
            draw_call_count=s["draw_call_count"],
        )
        for s in data.get("shaders", [])
    ]
    return CaptureAnalysisResult(stats=stats)
