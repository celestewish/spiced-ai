"""Out-of-process worker: RenderDoc capture analysis (Implementation Bible,
Feature 9). UNVERIFIED -- see connectors.renderdoc_analysis's module
docstring for what this is and isn't confirmed against.

Invoked as ``python -m spiced.connectors._renderdoc_worker <rdc_path>
<renderdoc_pymodules_path>``. Prints a JSON result to stdout on success.
On failure to even import ``renderdoc``, prints the literal string
``RENDERDOC_NOT_AVAILABLE`` to stdout and exits 1, which the parent
(``renderdoc_analysis.analyze_capture``) checks for specifically so it can
give a clear "RenderDoc isn't installed/reachable" message rather than a
generic failure. Not a public API -- only ``renderdoc_analysis`` calls this.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict


def main() -> None:
    rdc_path, pymodules_path = sys.argv[1:3]
    sys.path.insert(0, pymodules_path)

    try:
        import renderdoc as rd
    except ImportError:
        print("RENDERDOC_NOT_AVAILABLE")
        sys.exit(1)

    rd.InitialiseReplay(rd.GlobalEnvironment(), [])
    try:
        cap = rd.OpenCaptureFile()
        try:
            status = cap.OpenFile(rdc_path, "", None)
            if status != rd.ReplayStatus.Succeeded:
                raise RuntimeError(f"Could not open capture file: {status}")

            status, controller = cap.OpenCapture(rd.ReplayOptions(), None)
            if status != rd.ReplayStatus.Succeeded:
                raise RuntimeError(f"Could not open replay controller: {status}")

            try:
                shader_stats = _collect_shader_stats(rd, controller)
            finally:
                controller.Shutdown()
        finally:
            cap.Shutdown()
    finally:
        rd.ShutdownReplay()

    print(
        json.dumps(
            {
                "shaders": [
                    {
                        "shader_name": name,
                        "gpu_time_ms": stats["gpu_time_ms"],
                        "texture_bandwidth_bytes": stats["texture_bandwidth_bytes"],
                        "draw_call_count": stats["draw_call_count"],
                    }
                    for name, stats in shader_stats.items()
                ]
            }
        )
    )


def _collect_shader_stats(rd, controller) -> dict:
    """Aggregate GPU time / draw-call count / texture bandwidth per pixel
    shader across every draw ("action") in the capture."""
    actions = controller.GetRootActions()
    counter_results = controller.FetchCounters([rd.GPUCounter.EventGPUDuration])
    duration_by_event = {r.eventId: r for r in counter_results}

    per_shader: dict = defaultdict(
        lambda: {"gpu_time_ms": 0.0, "texture_bandwidth_bytes": 0, "draw_call_count": 0}
    )

    def visit(action) -> None:
        if action.flags & rd.ActionFlags.Drawcall:
            controller.SetFrameEvent(action.eventId, True)
            pipe = controller.GetPipelineState()
            shader_id = pipe.GetShader(rd.ShaderStage.Pixel)
            reflection = pipe.GetShaderReflection(rd.ShaderStage.Pixel)
            name = (
                reflection.resourceId.name
                if reflection is not None and hasattr(reflection, "resourceId")
                else str(shader_id)
            )

            result = duration_by_event.get(action.eventId)
            gpu_ms = 0.0
            if result is not None and result.value.d is not None:
                gpu_ms = float(result.value.d) * 1000.0  # seconds -> ms

            bandwidth = 0
            for ro in pipe.GetReadOnlyResources(rd.ShaderStage.Pixel):
                res = controller.GetResource(ro.resources[0].resourceId)
                if res is not None:
                    bandwidth += int(getattr(res, "byteSize", 0))

            per_shader[name]["gpu_time_ms"] += gpu_ms
            per_shader[name]["texture_bandwidth_bytes"] += bandwidth
            per_shader[name]["draw_call_count"] += 1

        for child in action.children:
            visit(child)

    for action in actions:
        visit(action)

    return per_shader


if __name__ == "__main__":
    main()
