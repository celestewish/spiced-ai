"""Manual GUT (Godot Unit Test) execution (Market-Viability Roadmap, Phase 2)
-- the Godot counterpart to ``core.unity_test_runner``.

Godot has no single built-in test runner the way Unity's Test Framework
package is a first-party, always-the-same-answer dependency -- per the
roadmap's own note, this module must detect which framework (if any) a
project actually uses rather than assume one. GUT
(https://github.com/bitwes/Gut) is by a wide margin the Godot community's
de facto standard addon for this, so it's the one framework this module
knows how to drive; a project using something else (or nothing) is reported
as such rather than silently treated as a GUT project.

**Verification status.** GUT's addon-folder layout (``addons/gut/
plugin.cfg`` as the marker every Godot addon has, ``addons/gut/
gut_cmdln.gd`` as its documented headless command-line entry point) and its
``-gdir=res://<path> -gexit`` CLI convention are GUT's own long-stable,
publicly documented interface, unchanged across GUT's 4.x releases. No real
GUT installation was available to run in this environment, so (matching
``connectors.godot_build``'s same honest caveat) this has not been
empirically re-verified end-to-end here -- only checked against GUT's
published documentation and README.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 1800
LOG_TAIL_CHARS = 4000

_GUT_ADDON_DIR = Path("addons") / "gut"
_GUT_CMDLN_SCRIPT = "gut_cmdln.gd"


def is_gut_installed(project_path: str | Path) -> bool:
    """True iff the project has GUT's addon installed -- the marker every
    Godot addon carries (``plugin.cfg``) plus GUT's specific headless entry
    point script, so an unrelated addon named "gut" for some other reason
    isn't mistaken for it."""
    addon_dir = Path(project_path) / _GUT_ADDON_DIR
    return (addon_dir / "plugin.cfg").is_file() and (addon_dir / _GUT_CMDLN_SCRIPT).is_file()


@dataclass(frozen=True)
class GodotTestRunResult:
    results_xml: str | None
    log_tail: str | None
    timed_out: bool
    exit_code: int | None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.results_xml is not None


def run_gut_tests(
    godot_path: str,
    project_path: str,
    test_dir: str = "res://test",
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> GodotTestRunResult:
    """Run GUT's suite headlessly under ``test_dir`` and return its JUnit XML
    results.

    Caller must have already confirmed ``is_gut_installed(project_path)`` --
    this function is pure mechanism with no gate of its own, matching every
    other connector's convention. Deliberately omits any Unity-style
    result-file handshake: GUT's own ``-gjunit_xml_file`` flag writes exactly
    the results file this needs, so no generated intermediary script is
    required the way Unity's build/test connectors needed one.
    """
    with tempfile.TemporaryDirectory(prefix="spiced-gut-tests-") as tmp:
        results_path = Path(tmp) / "results.xml"
        command = [
            godot_path,
            "--headless",
            "--path",
            str(project_path),
            "-s",
            str(_GUT_ADDON_DIR / _GUT_CMDLN_SCRIPT),
            f"-gdir={test_dir}",
            f"-gjunit_xml_file={results_path}",
            "-gexit",
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
            return GodotTestRunResult(
                results_xml=None,
                log_tail=None,
                timed_out=False,
                exit_code=None,
                error=f"Could not launch Godot: {exc}",
            )

        log_tail = _combine(stdout_tail, stderr_tail)
        if timed_out:
            duration = f"{timeout_s // 60} minutes" if timeout_s >= 60 else f"{timeout_s} seconds"
            return GodotTestRunResult(
                results_xml=None,
                log_tail=log_tail,
                timed_out=True,
                exit_code=None,
                error=f"GUT did not finish within {duration} and was stopped.",
            )

        xml_text = _read_text(results_path)
        if xml_text is None:
            return GodotTestRunResult(
                results_xml=None,
                log_tail=log_tail,
                timed_out=False,
                exit_code=exit_code,
                error=(
                    "Godot exited without writing a GUT results file. This usually means it hit "
                    "an error before the tests could run — see the log excerpt below."
                ),
            )
        return GodotTestRunResult(
            results_xml=xml_text, log_tail=log_tail, timed_out=False, exit_code=exit_code
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
