"""Unreal headless build via the Unreal Automation Tool (UAT)
(Market-Viability Roadmap, Phase 3) -- the Unreal counterpart to
``connectors.unity_build``/``connectors.godot_build``.

No generated build script is written into the project (unlike Unity's
connector) -- ``RunUAT``'s ``BuildCookRun`` command is a complete,
self-contained build/cook/package pipeline driven entirely by command-line
arguments against the existing ``.uproject``, the same shape as Godot's
export connector needing no generated script either.

**Verification status.** ``RunUAT.(bat|sh) BuildCookRun -project=<.uproject>
-platform=<Platform> -clientconfig=<Config> -build -cook -stage -pak
-archive -archivedirectory=<dir>`` is Epic's own long-documented, stable CI
convention -- UAT is specifically built and marketed for automated build
farms, and (unlike Unity's own explicit documentation that batch-mode exit
codes are *not* reliable) Epic's own docs and UAT's design intent treat its
exit code as a first-class, reliable success/failure signal; this is a
stronger, better-attested claim than the equivalent one made for Godot's
export CLI in ``connectors.godot_build``. That said, no real Unreal Engine
installation was available to run ``RunUAT`` in this environment, so this
has not been empirically re-verified end-to-end here either -- only checked
against Epic's published documentation. ``run_build`` therefore still
confirms the archive output actually exists in addition to trusting the
exit code, the same double-check ``godot_build.run_export`` uses, rather
than trusting the exit code alone.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_TIMEOUT_S = 3600  # Cook+package runs routinely take longer than a Unity/Godot build.
LOG_TAIL_CHARS = 4000

DEFAULT_CLIENT_CONFIG = "Development"


@dataclass(frozen=True)
class UnrealBuildResult:
    succeeded: bool
    output_path: str | None
    log_tail: str | None
    exit_code: int | None
    timed_out: bool
    error: str | None = None


def run_build(
    uat_path: str,
    uproject_path: str,
    platform: str,
    archive_directory: str,
    client_config: str = DEFAULT_CLIENT_CONFIG,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> UnrealBuildResult:
    """Launch one headless ``BuildCookRun`` and return its result.

    ``uat_path`` is the path to ``RunUAT.bat``/``RunUAT.sh`` inside an
    Unreal Engine install (``Engine/Build/BatchFiles/``) -- resolving that
    path is the caller's responsibility, same division of concerns as
    ``unity_build.run_build`` taking an already-resolved editor path.
    """
    command = [
        uat_path,
        "BuildCookRun",
        f"-project={uproject_path}",
        "-noP4",
        f"-platform={platform}",
        f"-clientconfig={client_config}",
        "-build",
        "-cook",
        "-stage",
        "-pak",
        "-archive",
        f"-archivedirectory={archive_directory}",
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
        return UnrealBuildResult(
            succeeded=False,
            output_path=None,
            log_tail=None,
            exit_code=None,
            timed_out=False,
            error=f"Could not launch RunUAT: {exc}",
        )

    log_tail = _combine(stdout_tail, stderr_tail)
    if timed_out:
        duration = f"{timeout_s // 60} minutes" if timeout_s >= 60 else f"{timeout_s} seconds"
        return UnrealBuildResult(
            succeeded=False,
            output_path=None,
            log_tail=log_tail,
            exit_code=None,
            timed_out=True,
            error=(
                f"The build did not finish within {duration} and was stopped. Cook+package "
                "runs can legitimately take a long time, especially the first one for a "
                "project — consider a longer timeout before assuming this is a hang."
            ),
        )

    output_exists = Path(archive_directory).is_dir() and any(Path(archive_directory).iterdir())
    succeeded = exit_code == 0 and output_exists
    error = None
    if not succeeded:
        if exit_code != 0:
            error = f"RunUAT exited with code {exit_code} — see the log excerpt below."
        else:
            error = (
                "RunUAT exited successfully but the archive directory is empty — see the log "
                "excerpt below."
            )
    return UnrealBuildResult(
        succeeded=succeeded,
        output_path=archive_directory if succeeded else None,
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
