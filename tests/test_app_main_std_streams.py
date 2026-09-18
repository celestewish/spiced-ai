"""spiced.app.main._ensure_std_streams(): the fix for a real, previously
unexplained bug -- a windowed (console=False) PyInstaller build's
sys.stdout/sys.stderr are None, so anything touching them (this module's
own print() on the --smoke-test success path included) raised an uncaught
AttributeError that killed the process before anything could be reported.
Root-caused via a diagnostic console-subsystem CI build of the exact same
code, which ran clean -- see packaging/README.md's former "Known issue"
section and .github/workflows/release.yml's history.

The "streams are actually None" cases run in a real subprocess rather than
monkeypatching sys.stdout/sys.stderr on the live pytest process: pytest's
own output capture and fault-handling machinery depends on those being
real, valid objects, and a previous version of this file that set them to
None in-process reproducibly crashed the *entire test session* (a native
fault, not a normal test failure) once combined with other test modules in
the same run -- exactly the kind of cross-test corruption this module's own
subject matter warns about. A subprocess's sys.stdout/stderr belong to that
process alone.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

from spiced.app import main as main_module

_REPO_SRC = Path(__file__).resolve().parents[1] / "src"


def test_leaves_real_streams_untouched(monkeypatch):
    # Real (if throwaway) stream objects, not None and not a bare object()
    # -- safe to touch even if something incidental writes to them during
    # the monkeypatch window, unlike this test's own subject matter.
    fake_out, fake_err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_out)
    monkeypatch.setattr(sys, "stderr", fake_err)

    main_module._ensure_std_streams()

    assert sys.stdout is fake_out
    assert sys.stderr is fake_err


def _run_in_subprocess(tmp_path: Path, body: str) -> Path:
    """Runs ``body`` in a fresh Python process with sys.stdout/sys.stderr
    set to None *before* spiced.app.main is even imported, and HOME/
    USERPROFILE redirected to tmp_path so Path.home() lands there. Returns
    the log file _ensure_std_streams should have created."""
    script = (
        "import sys\n"
        f"sys.path.insert(0, {str(_REPO_SRC)!r})\n"
        "sys.stdout = None\n"
        "sys.stderr = None\n"
        "from spiced.app.main import _ensure_std_streams\n"
        f"{body}\n"
    )
    # Inherit the real environment (PATH, SYSTEMROOT, etc. -- Python and
    # Windows both need more than just HOME to start cleanly) and only
    # override where Path.home() should resolve to.
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stdout}\n{result.stderr}"
    return tmp_path / ".spiced" / "spiced_stdio.log"


def test_redirects_both_streams_to_a_log_file_when_both_are_none(tmp_path):
    log_path = _run_in_subprocess(
        tmp_path,
        "_ensure_std_streams()\n"
        "assert sys.stdout is not None\n"
        "assert sys.stdout is sys.stderr\n"  # same shared log stream
        "print('hello from a windowed build', file=sys.stdout)\n"
        "sys.stdout.flush()\n",
    )

    assert log_path.is_file()
    assert "hello from a windowed build" in log_path.read_text(encoding="utf-8")


def test_redirects_only_stdout_when_only_stdout_is_none(tmp_path):
    _run_in_subprocess(
        tmp_path,
        "import io\n"
        "sys.stderr = io.StringIO()\n"  # a real, writable stream -- not None
        "real_err = sys.stderr\n"
        "_ensure_std_streams()\n"
        "assert sys.stdout is not None\n"
        "assert sys.stderr is real_err\n",  # untouched -- it wasn't the broken one
    )


def test_creates_the_spiced_home_folder_if_missing(tmp_path):
    fresh_home = tmp_path / "not-yet-created"
    log_path = fresh_home / ".spiced" / "spiced_stdio.log"
    _run_in_subprocess(fresh_home, "_ensure_std_streams()\n")  # must not raise

    assert log_path.parent.is_dir()
