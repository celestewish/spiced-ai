"""Save/Load Integrity Testing use-case (Phase E, section 6, Core tier).

Convention-based, per the plan's confirmed approach: Spiced launches the
project's own *built game executable* (not the Unity Editor — a separate,
already-built ``.exe`` the developer points at, configured per project) once
per save file in a folder the developer supplies, passing two environment
variables:

    SPICED_LOAD_TEST_SAVE_PATH    -- absolute path to the save file to load
    SPICED_LOAD_TEST_RESULT_PATH  -- absolute path to write a small JSON result to

The developer's own game is responsible for noticing these env vars at
startup, attempting to load that save, writing
``{"success": bool, "error": str|null}`` to the result path, and exiting.
Like ``unity_test_runner``/``unity_build``, the process's exit code is never
trusted as the sole success signal — only the result file is read, since a
game can exit 0 after a silent load failure just as easily as it can crash
after a genuine success. See ``docs/save_load_integrity_hook.md`` for the
exact, concrete contract shipped to developers.

This only works for games that implement that hook. It cannot inspect an
unmodified black-box executable — that limitation is surfaced in the report
and the in-app copy, not hidden.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from spiced.storage.projects import Project
from spiced.storage.save_integrity_reports import (
    SaveIntegrityReport,
    SaveIntegrityReportRepository,
)

DEFAULT_TIMEOUT_S = 60

SAVE_PATH_ENV_VAR = "SPICED_LOAD_TEST_SAVE_PATH"
RESULT_PATH_ENV_VAR = "SPICED_LOAD_TEST_RESULT_PATH"

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed_out"
# Launch failure, or the game exited without writing a (valid) result file —
# usually means the hook isn't implemented yet, not necessarily a real bug.
STATUS_ERROR = "error"


class NoExecutableError(RuntimeError):
    """Raised when no valid built-game executable path was given."""


class NoSavesFolderError(RuntimeError):
    """Raised when the saves folder has no files to test."""


@dataclass(frozen=True)
class SaveTestResult:
    save_file: str
    status: str  # one of STATUS_*
    error: str | None = None

    def as_dict(self) -> dict:
        return {"save_file": self.save_file, "status": self.status, "error": self.error}


def run_one_save(
    executable_path: str, save_path: str | Path, timeout_s: int = DEFAULT_TIMEOUT_S
) -> SaveTestResult:
    """Launch the built game once against one save file and read its result."""
    save_path = Path(save_path)
    with tempfile.TemporaryDirectory(prefix="spiced-save-test-") as tmp:
        result_path = Path(tmp) / "result.json"
        env = {
            **os.environ,
            SAVE_PATH_ENV_VAR: str(save_path),
            RESULT_PATH_ENV_VAR: str(result_path),
        }
        try:
            subprocess.run([executable_path], env=env, timeout=timeout_s, capture_output=True)
        except subprocess.TimeoutExpired:
            return SaveTestResult(
                save_file=save_path.name,
                status=STATUS_TIMED_OUT,
                error=(
                    f"Didn't exit within {timeout_s}s — the game may be stuck (a dialog, an "
                    "infinite load) rather than crashed."
                ),
            )
        except OSError as exc:
            return SaveTestResult(
                save_file=save_path.name,
                status=STATUS_ERROR,
                error=f"Could not launch the game: {exc}",
            )

        data = _read_json(result_path)
        if data is None:
            return SaveTestResult(
                save_file=save_path.name,
                status=STATUS_ERROR,
                error=(
                    "The game exited without writing a valid result file. Either it doesn't "
                    "implement the Save/Load Integrity hook yet (see "
                    "docs/save_load_integrity_hook.md), or it crashed before writing one."
                ),
            )
        if data.get("success") is True:
            return SaveTestResult(save_file=save_path.name, status=STATUS_PASSED, error=None)
        error_text = data.get("error")
        return SaveTestResult(
            save_file=save_path.name,
            status=STATUS_FAILED,
            error=str(error_text) if error_text else 'The game reported "success": false.',
        )


def _read_json(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def list_save_files(saves_folder: str | Path) -> list[Path]:
    """All files directly under ``saves_folder`` (non-recursive), sorted by name."""
    folder = Path(saves_folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file())


@dataclass(frozen=True)
class SaveIntegrityRun:
    results: list[SaveTestResult]
    report: SaveIntegrityReport | None

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_PASSED)

    @property
    def failed_count(self) -> int:
        return len(self.results) - self.passed_count


class SaveLoadTesterService:
    def __init__(self, reports: SaveIntegrityReportRepository) -> None:
        self._reports = reports

    def run(
        self,
        project: Project,
        executable_path: str,
        saves_folder: str,
        timeout_s: int = DEFAULT_TIMEOUT_S,
    ) -> SaveIntegrityRun:
        """Run every save file in ``saves_folder`` through the built executable
        and save a rollup report. Purely local/deterministic — no AI call."""
        if not executable_path or not Path(executable_path).is_file():
            raise NoExecutableError(
                "Point Spiced at your project's built game executable first."
            )
        saves = list_save_files(saves_folder)
        if not saves:
            raise NoSavesFolderError(
                "No files found in that folder — pick a folder containing old save files."
            )
        results = [run_one_save(executable_path, save, timeout_s=timeout_s) for save in saves]
        passed = sum(1 for r in results if r.status == STATUS_PASSED)
        failed = len(results) - passed
        report = self._reports.create(
            project_id=project.id,
            executable_path=executable_path,
            saves_folder=saves_folder,
            results=[r.as_dict() for r in results],
            passed_count=passed,
            failed_count=failed,
        )
        return SaveIntegrityRun(results=results, report=report)

    def history(self, project_id: int, limit: int = 20) -> list[SaveIntegrityReport]:
        return self._reports.list_for_project(project_id, limit=limit)
