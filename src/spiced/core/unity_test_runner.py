"""Manual Unity Test Runner execution.

Opt-in, per project, and off by default: this is the one place Spiced
launches an external engine process rather than only parsing text a
developer pastes or imports. Everything downstream stays exactly the same —
Unity writes its results as standard NUnit3 XML, which the existing
deterministic test-result parser already reads, so a real run feeds the same
parsing -> regression-matching -> AI-review pipeline as a pasted result.

Unity's own documentation states there is no reliable, version-stable exit
code for test pass/fail, so the results XML is always read regardless of the
process's exit code — the exit code is only used to explain a run that never
produced results at all (a crash, bad arguments, license/activation failure).

Windows-first, matching the rest of the app; Unity Hub discovery below only
looks in Windows install locations.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

EDIT_MODE = "EditMode"
PLAY_MODE = "PlayMode"
TEST_PLATFORMS = (EDIT_MODE, PLAY_MODE)

# Generous default: a project's first headless run can trigger a full asset
# reimport, which can take a long time and is easily mistaken for a hang.
DEFAULT_TIMEOUT_S = 1800

LOG_TAIL_CHARS = 4000

_HUB_CANDIDATE_PATHS = (
    r"C:\Program Files\Unity Hub\Unity Hub.exe",
    r"C:\Program Files (x86)\Unity Hub\Unity Hub.exe",
)

_EDITOR_LINE_RE = re.compile(r"^(?P<version>\S+)\s*,\s*installed at\s+(?P<path>.+)$")


@dataclass(frozen=True)
class UnityEditorInfo:
    version: str
    path: str


@dataclass(frozen=True)
class UnityTestRunResult:
    results_xml: str | None
    log_tail: str | None
    timed_out: bool
    exit_code: int | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.results_xml is not None


def find_unity_hub_executable() -> str | None:
    """Locate Unity Hub, or None if it isn't installed in a known location."""
    for candidate in _HUB_CANDIDATE_PATHS:
        if Path(candidate).is_file():
            return candidate
    local_appdata_hub = (
        Path.home() / "AppData" / "Local" / "Programs" / "Unity Hub" / "Unity Hub.exe"
    )
    if local_appdata_hub.is_file():
        return str(local_appdata_hub)
    return None


def list_installed_editors(hub_path: str, timeout_s: int = 30) -> list[UnityEditorInfo]:
    """Ask Unity Hub for its installed editors via its documented headless CLI.

    Uses ``Unity Hub.exe -- --headless editors -i`` rather than reading Hub's
    internal state files directly, since that file format isn't a stable,
    documented interface across Hub versions.
    """
    try:
        result = subprocess.run(
            [hub_path, "--", "--headless", "editors", "-i"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    editors: list[UnityEditorInfo] = []
    for line in result.stdout.splitlines():
        match = _EDITOR_LINE_RE.match(line.strip())
        if match:
            editors.append(
                UnityEditorInfo(version=match.group("version"), path=match.group("path").strip())
            )
    return editors


def resolve_unity_editor(
    required_version: str | None,
    override_path: str | None = None,
    hub_path: str | None = None,
) -> UnityEditorInfo | None:
    """Find the Unity Editor executable to run.

    An explicit ``override_path`` always wins. Otherwise, the project's exact
    required version (from ``ProjectSettings/ProjectVersion.txt``, already
    read during Unity-folder detection) must match an installed editor —
    Spiced does not fall back to a "close enough" version, since opening a
    project with the wrong Editor can trigger an unwanted upgrade/reimport.
    Returns None if nothing matches.
    """
    if override_path:
        if not Path(override_path).is_file():
            return None
        return UnityEditorInfo(version=required_version or "unknown", path=override_path)
    if not required_version:
        return None
    hub = hub_path or find_unity_hub_executable()
    if not hub:
        return None
    for editor in list_installed_editors(hub):
        if editor.version == required_version:
            return editor
    return None


def run_tests(
    unity_path: str,
    project_path: str,
    test_platform: str,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> UnityTestRunResult:
    """Run one Unity Test Runner platform headlessly and return its results.

    Deliberately omits ``-quit``: Unity's own ``-runTests`` already exits once
    the run finishes, and the docs flag known issues combining the two flags.
    """
    if test_platform not in TEST_PLATFORMS:
        raise ValueError(f"Unknown test platform: {test_platform!r}")

    with tempfile.TemporaryDirectory(prefix="spiced-unity-tests-") as tmp:
        results_path = Path(tmp) / "results.xml"
        log_path = Path(tmp) / "editor.log"
        command = [
            unity_path,
            "-batchmode",
            "-projectPath",
            str(project_path),
            "-runTests",
            "-testPlatform",
            test_platform,
            "-testResults",
            str(results_path),
            "-logFile",
            str(log_path),
            "-nographics",
        ]

        exit_code: int | None = None
        timed_out = False
        try:
            completed = subprocess.run(command, timeout=timeout_s, capture_output=True)
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
        except OSError as exc:
            return UnityTestRunResult(
                results_xml=None,
                log_tail=None,
                timed_out=False,
                exit_code=None,
                error=f"Could not launch Unity: {exc}",
            )

        log_tail = _read_tail(log_path)
        if timed_out:
            duration = f"{timeout_s // 60} minutes" if timeout_s >= 60 else f"{timeout_s} seconds"
            return UnityTestRunResult(
                results_xml=None,
                log_tail=log_tail,
                timed_out=True,
                exit_code=None,
                error=(
                    f"Unity did not finish within {duration} and was stopped. This can "
                    "happen on a slow first-time asset import, or if Unity is stuck on a dialog "
                    "(e.g. license activation) that batch mode can't dismiss."
                ),
            )

        xml_text = _read_text(results_path)
        if xml_text is None:
            return UnityTestRunResult(
                results_xml=None,
                log_tail=log_tail,
                timed_out=False,
                exit_code=exit_code,
                error=(
                    "Unity exited without writing a results file. This usually means it hit an "
                    "error before the tests could run — see the log excerpt below."
                ),
            )
        return UnityTestRunResult(
            results_xml=xml_text, log_tail=log_tail, timed_out=False, exit_code=exit_code
        )


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_tail(path: Path, limit: int = LOG_TAIL_CHARS) -> str | None:
    text = _read_text(path)
    if text is None:
        return None
    return text[-limit:] if len(text) > limit else text
