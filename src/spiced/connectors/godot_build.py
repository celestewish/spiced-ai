"""Godot headless export (Market-Viability Roadmap, Phase 2) -- the Godot
counterpart to ``connectors.unity_build``.

Architectural difference from Unity, worth being upfront about: Unity's
build connector *writes* a build script into the project (``Assets/Editor/
SpicedBuildScript.cs``) because Unity has no notion of a build target that
exists independent of running the Editor's build API. Godot is the
opposite -- a project's export targets (platform, output filter, codesign
settings, ...) are already fully described in ``export_presets.cfg``,
written by the Godot editor itself the first time a developer sets up
Export in the Editor UI. Spiced has no reason to (and should not) generate
or modify that file -- it can only be produced correctly by the Editor,
since it references platform export-template UUIDs Spiced has no way to
know. This module only *reads* the preset names already there and drives
the export via Godot's own documented headless CLI.

**Verification status, stated plainly.** ``export_presets.cfg``'s format
(``[preset.N]`` sections with a ``name=`` field, ConfigFile-style) is Godot's
own long-stable, publicly documented convention, but -- unlike every other
format this Phase verified against a real fetched sample -- no real
``export_presets.cfg`` was available to verify directly: it's a per-machine,
locally-generated file (references local export-template paths) that every
public demo-project repo checked, including ``godotengine/godot-demo-
projects`` itself, deliberately excludes via ``.gitignore``. The preset-name
reader below is written defensively (skips anything it can't parse rather
than raising) for exactly this reason. Likewise, ``godot --headless
--export-release <preset> <output>``'s exit-code reliability is documented
by Godot as a real non-zero-on-failure signal, but that has not been
empirically re-verified against a running Godot binary in this environment
the way Unity's *unreliable* exit code was independently confirmed via
Unity's own docs. ``run_export`` therefore trusts the exit code as its
primary success signal but always captures the full stdout/stderr tail
too, so a failure is diagnosable either way -- confirm this assumption
against a real Godot install before removing that log-tail fallback.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 1800
LOG_TAIL_CHARS = 4000

_PRESET_SECTION_RE = re.compile(r"^\[preset\.(\d+)\]\s*$")
_NAME_RE = re.compile(r'^name="((?:[^"\\]|\\.)*)"')
_PLATFORM_RE = re.compile(r'^platform="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class ExportPreset:
    index: int
    name: str
    platform: str | None


def export_presets_path(project_path: str | Path) -> Path:
    return Path(project_path) / "export_presets.cfg"


def list_export_presets(project_path: str | Path) -> list[ExportPreset]:
    """Read the export preset names already configured in the Godot editor.

    ``[]`` (never raises) if ``export_presets.cfg`` doesn't exist yet -- the
    developer hasn't set up Export in the Editor for this project, which
    Spiced can't do on their behalf (see module docstring).
    """
    path = export_presets_path(project_path)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    presets: list[ExportPreset] = []
    current_index: int | None = None
    current_name: str | None = None
    current_platform: str | None = None

    def _flush() -> None:
        if current_index is not None and current_name is not None:
            presets.append(
                ExportPreset(index=current_index, name=current_name, platform=current_platform)
            )

    for line in text.splitlines():
        section_match = _PRESET_SECTION_RE.match(line)
        if section_match:
            _flush()
            current_index = int(section_match.group(1))
            current_name = None
            current_platform = None
            continue
        if current_index is None:
            continue
        if (m := _NAME_RE.match(line)) is not None:
            current_name = m.group(1)
        elif (m := _PLATFORM_RE.match(line)) is not None:
            current_platform = m.group(1)
    _flush()
    return presets


@dataclass(frozen=True)
class GodotExportResult:
    succeeded: bool
    output_path: str | None
    log_tail: str | None
    exit_code: int | None
    timed_out: bool
    error: str | None = None


def run_export(
    godot_path: str,
    project_path: str,
    preset_name: str,
    output_path: str,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> GodotExportResult:
    """Launch one headless Godot export and return its result.

    Unlike ``unity_build.run_build``, there is no generated result-file
    handshake here (see module docstring on why) -- ``succeeded`` is based
    on the process exit code plus confirming ``output_path`` actually
    exists afterward, which is a stronger signal than the exit code alone.
    """
    command = [
        godot_path,
        "--headless",
        "--path",
        str(project_path),
        "--export-release",
        preset_name,
        str(output_path),
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
        return GodotExportResult(
            succeeded=False,
            output_path=None,
            log_tail=None,
            exit_code=None,
            timed_out=False,
            error=f"Could not launch Godot: {exc}",
        )

    log_tail = _combine(stdout_tail, stderr_tail)
    if timed_out:
        duration = f"{timeout_s // 60} minutes" if timeout_s >= 60 else f"{timeout_s} seconds"
        return GodotExportResult(
            succeeded=False,
            output_path=None,
            log_tail=log_tail,
            exit_code=None,
            timed_out=True,
            error=(
                f"Godot did not finish the export within {duration} and was stopped. This can "
                "happen on a large project's first export-template download or asset import."
            ),
        )

    output_exists = Path(output_path).exists()
    succeeded = exit_code == 0 and output_exists
    error = None
    if not succeeded:
        if exit_code != 0:
            error = f"Godot exited with code {exit_code} — see the log excerpt below."
        else:
            error = (
                "Godot exited successfully but the expected output file wasn't found — see the "
                "log excerpt below."
            )
    return GodotExportResult(
        succeeded=succeeded,
        output_path=output_path if succeeded else None,
        log_tail=log_tail,
        exit_code=exit_code,
        timed_out=False,
        error=error,
    )


def _tail(text: str | None, limit: int = LOG_TAIL_CHARS) -> str | None:
    if not text:
        return None
    return text[-limit:] if len(text) > limit else text


def _combine(stdout_tail: str | None, stderr_tail: str | None) -> str | None:
    parts = [p for p in (stdout_tail, stderr_tail) if p]
    return "\n".join(parts) if parts else None
