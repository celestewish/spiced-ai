"""Test-runner dispatch (Godot/Unreal UI follow-up).

Unlike ``core.build_pipeline`` (already a real ``Services.run_build`` choke
point), the UI historically called ``connectors.unity_test_runner.run_tests``
directly from its worker thread, bypassing ``Services`` entirely -- there was
no shared entry point to extend for Godot/Unreal. ``run_test_pipeline`` below
is that entry point now: one function all three engines' test runs go
through, returning a single ``RawTestRun`` shape the UI hands to
``TestingService.analyze`` without needing to know which engine produced it.

Godot and Unreal's raw output (JUnit XML / Automation JSON respectively) is
normalized via ``core.test_result_adapters`` into the generic JSON
``test_result_parser`` already understands -- see that module for why.
"""

from __future__ import annotations

from dataclasses import dataclass

from spiced.connectors import godot_test_runner, unreal_test_runner
from spiced.connectors.unreal import find_uproject_file
from spiced.core.engine_dispatch import ENGINE_GODOT, ENGINE_UNREAL
from spiced.core.test_result_adapters import (
    godot_junit_to_generic_json,
    unreal_report_to_generic_json,
)
from spiced.core.testing import SOURCE_GODOT_RUN, SOURCE_UNITY_RUN, SOURCE_UNREAL_RUN
from spiced.core.unity_test_runner import run_tests as run_unity_tests
from spiced.storage.projects import Project

__all__ = ["RawTestRun", "TestRunnerNotAvailableError", "run_test_pipeline"]


class TestRunnerNotAvailableError(RuntimeError):
    """Raised when a project's engine has no runnable test framework
    configured (e.g. Godot without the GUT addon installed)."""


@dataclass(frozen=True)
class RawTestRun:
    succeeded: bool
    raw_text: str | None
    source_type: str
    source_filename: str
    error: str | None
    log_tail: str | None


def run_test_pipeline(project: Project, editor_path: str, platform: str) -> RawTestRun:
    """Run one test pass for ``project`` and return its raw, engine-tagged
    result. ``platform`` is Unity's EditMode/PlayMode selection; Godot
    ignores it (GUT has no platform concept), Unreal treats it as an
    optional test filter (empty runs everything registered)."""
    if project.engine == ENGINE_GODOT:
        return _run_godot(project, editor_path)
    if project.engine == ENGINE_UNREAL:
        return _run_unreal(project, editor_path, platform)
    return _run_unity(project, editor_path, platform)


def _run_unity(project: Project, editor_path: str, platform: str) -> RawTestRun:
    result = run_unity_tests(editor_path, project.path, platform)
    return RawTestRun(
        succeeded=result.succeeded,
        raw_text=result.results_xml,
        source_type=SOURCE_UNITY_RUN,
        source_filename=f"unity-{platform.lower()}-run.xml",
        error=result.error,
        log_tail=result.log_tail,
    )


def _run_godot(project: Project, editor_path: str) -> RawTestRun:
    if not godot_test_runner.is_gut_installed(project.path):
        raise TestRunnerNotAvailableError(
            "GUT (Godot Unit Test) isn't installed in this project — Spiced only knows how to "
            "drive GUT's headless CLI. Install the GUT addon first, or run tests from the Godot "
            "Editor directly."
        )
    result = godot_test_runner.run_gut_tests(editor_path, project.path)
    raw_text = godot_junit_to_generic_json(result.results_xml) if result.results_xml else None
    return RawTestRun(
        succeeded=result.succeeded,
        raw_text=raw_text,
        source_type=SOURCE_GODOT_RUN,
        source_filename="godot-gut-run.json",
        error=result.error,
        log_tail=result.log_tail,
    )


def _run_unreal(project: Project, editor_path: str, platform: str) -> RawTestRun:
    uproject_path = find_uproject_file(project.path)
    if uproject_path is None:
        raise TestRunnerNotAvailableError("No .uproject file found in this project's folder.")
    result = unreal_test_runner.run_automation_tests(
        editor_path, str(uproject_path), platform or ""
    )
    raw_text = unreal_report_to_generic_json(result.report_json) if result.report_json else None
    return RawTestRun(
        succeeded=result.succeeded,
        raw_text=raw_text,
        source_type=SOURCE_UNREAL_RUN,
        source_filename="unreal-automation-run.json",
        error=result.error,
        log_tail=result.log_tail,
    )
