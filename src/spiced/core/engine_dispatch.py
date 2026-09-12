"""Shared engine-name constants (Market-Viability Roadmap, Godot/Unreal UI
follow-up).

``Project.engine`` is a free-form string set from the Projects screen's
combo box (``"Unity"|"Godot"|"Unreal"|"Other"``, see ``ui.screens.projects``).
Every feature that branches on it -- ``core.dev_docs.DevDocsService.scan``
was first, followed by ``core.asset_scan``/``core.build_pipeline``/the test
runner dispatch -- used to spell the same three string literals out by hand.
These constants exist purely to stop that duplication drifting into a typo
("godot" vs "Godot") across call sites; they carry no behavior of their own.

``"Other"`` and any unrecognized value fall back to the Unity-shaped default
everywhere in this codebase (matching ``DevDocsService.scan``'s existing
``else`` branch), so there is no ``ENGINE_OTHER`` constant -- callers should
treat anything that isn't ``ENGINE_GODOT``/``ENGINE_UNREAL`` as the default
case rather than enumerating it.
"""

from __future__ import annotations

from pathlib import Path

from spiced.connectors.godot import GodotDetectionResult, detect_godot_project
from spiced.connectors.unity import UnityDetectionResult, detect_unity_project
from spiced.connectors.unreal import UnrealDetectionResult, detect_unreal_project

ENGINE_UNITY = "Unity"
ENGINE_GODOT = "Godot"
ENGINE_UNREAL = "Unreal"


def detect_engine(
    folder: str | Path,
) -> tuple[str, UnityDetectionResult | GodotDetectionResult | UnrealDetectionResult]:
    """Run all three folder detectors against ``folder`` and return the
    engine whose marker file matched, plus its detection result.

    Godot (``project.godot``) and Unreal (``*.uproject``) each have one
    unambiguous marker file, so at most one should ever match; Unity is
    checked last since its ``Assets/``/``ProjectSettings/`` pair is also
    the fallback shape used when nothing matches (matching
    ``ProjectsService.attach_engine_folder``'s existing "Other" -> Unity-
    shaped behavior), so an unrecognized folder still gets a consistent,
    actionable warning instead of three different ones.
    """
    godot_result = detect_godot_project(folder)
    if godot_result.is_valid:
        return ENGINE_GODOT, godot_result

    unreal_result = detect_unreal_project(folder)
    if unreal_result.is_valid:
        return ENGINE_UNREAL, unreal_result

    return ENGINE_UNITY, detect_unity_project(folder)
