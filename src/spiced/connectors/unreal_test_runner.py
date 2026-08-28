"""Manual Unreal Automation test execution (Market-Viability Roadmap, Phase
3) -- the Unreal counterpart to ``core.unity_test_runner``/``connectors.
godot_test_runner``.

Unlike Godot (no single built-in test runner, hence detecting GUT), Unreal
does ship a built-in Automation/Gauntlet test framework as part of the
Engine itself -- no third-party addon detection is needed the way GUT
needed one. A project either has automation test code (functional test
classes, ``IMPLEMENT_SIMPLE_AUTOMATION_TEST``-declared unit tests) or it
doesn't; this module doesn't gate on project content the way GUT-detection
does, since the Editor executable it drives is a guaranteed part of any
Unreal install regardless of what a given project contains.

**Verification status.** ``UnrealEditor-Cmd.exe <uproject>
-ExecCmds="Automation RunTests <filter>;Quit" -unattended -nopause
-testexit="Automation Test Queue Empty" -ReportOutputPath=<dir>`` is
Epic's own documented headless automation-testing invocation, and the
Automation report is a JSON file (``index.json``) written to
``-ReportOutputPath``, not JUnit XML the way GUT's report is -- this
module intentionally returns that JSON text as-is (mirroring ``unity_test_
runner``/``godot_test_runner``'s "hand back the raw results, let the
caller parse" shape) rather than guessing at a schema Spiced hasn't
verified against a real run. No real Unreal Engine installation was
available to run this in this environment -- confirm the report's actual
JSON shape against a real run before writing a parser for it.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 1800
LOG_TAIL_CHARS = 4000

_REPORT_FILE_NAME = "index.json"


@dataclass(frozen=True)
class UnrealTestRunResult:
    report_json: str | None
    log_tail: str | None
    timed_out: bool
    exit_code: int | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.report_json is not None


def run_automation_tests(
    editor_cmd_path: str,
    uproject_path: str,
    test_filter: str = "",
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> UnrealTestRunResult:
    """Run the Automation test suite headlessly and return its raw JSON
    report text.

    ``editor_cmd_path`` is the path to ``UnrealEditor-Cmd.exe`` (Windows) or
    the equivalent per-platform binary inside an Unreal Engine install --
    resolving that path is the caller's responsibility, same division of
    concerns as ``unity_test_runner.run_tests`` taking an already-resolved
    editor path. ``test_filter`` narrows which automation tests run (e.g. a
    module or category name); empty runs everything registered.
    """
    with tempfile.TemporaryDirectory(prefix="spiced-unreal-tests-") as tmp:
        report_dir = Path(tmp) / "report"
        filter_expr = test_filter or "*"
        exec_cmds = f"Automation RunTests {filter_expr};Quit"
        command = [
            editor_cmd_path,
            uproject_path,
            f"-ExecCmds={exec_cmds}",
            "-unattended",
            "-nopause",
            "-nosplash",
            "-testexit=Automation Test Queue Empty",
            f"-ReportOutputPath={report_dir}",
        ]

        exit_code: int | None = None
        timed_out = False
        stdout_tail = stderr_tail = None
        try:
            completed = subprocess.run(
                command, timeout=timeout_s, capture_output=True, text=True, errors="replace"
            )
            exit_code = completed.returncode
            stdout_tail = _tail(completed.stdout)
            stderr_tail = _tail(completed.stderr)
        except subprocess.TimeoutExpired:
            timed_out = True
        except OSError as exc:
            return UnrealTestRunResult(
                report_json=None,
                log_tail=None,
                timed_out=False,
                exit_code=None,
                error=f"Could not launch UnrealEditor-Cmd: {exc}",
            )

        log_tail = _combine(stdout_tail, stderr_tail)
        if timed_out:
            duration = f"{timeout_s // 60} minutes" if timeout_s >= 60 else f"{timeout_s} seconds"
            return UnrealTestRunResult(
                report_json=None,
                log_tail=log_tail,
                timed_out=True,
                exit_code=None,
                error=f"Automation tests did not finish within {duration} and were stopped.",
            )

        report_text = _read_text(report_dir / _REPORT_FILE_NAME)
        if report_text is None:
            return UnrealTestRunResult(
                report_json=None,
                log_tail=log_tail,
                timed_out=False,
                exit_code=exit_code,
                error=(
                    "The Editor exited without writing an Automation report. This usually means "
                    "it hit an error before the tests could run — see the log excerpt below."
                ),
            )
        return UnrealTestRunResult(
            report_json=report_text, log_tail=log_tail, timed_out=False, exit_code=exit_code
        )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _tail(text: str | None, limit: int = LOG_TAIL_CHARS) -> str | None:
    if not text:
        return None
    return text[-limit:] if len(text) > limit else text


def _combine(stdout_tail: str | None, stderr_tail: str | None) -> str | None:
    parts = [p for p in (stdout_tail, stderr_tail) if p]
    return "\n".join(parts) if parts else None
