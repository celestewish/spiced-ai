"""Batch Processing & Loudness Normalization (Implementation Bible, Feature 1).

Batch-normalizes a folder of SFX/voice/music files to a consistent EBU R128
integrated-loudness target via ``ffmpeg-normalize`` (a two-pass wrapper
around ffmpeg's ``loudnorm`` filter). Requires the real ``ffmpeg`` binary on
the host -- a system dependency, not something pip installs; see
``docs/loudness_normalize_ffmpeg.md``. ``check_ffmpeg_available`` is called
once up front so a missing install fails clearly before any file is touched,
rather than as a repeated per-file error.

Normalized output always goes to a ``<folder>_normalized`` directory
*alongside* (a sibling of, not nested inside) the source folder -- both so a
re-run never re-normalizes its own previous output, and so source files are
never overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ffmpeg_normalize import FFmpegNormalize, FFmpegNormalizeError

from spiced.automation.batch_runner import BatchRunner
from spiced.automation.finding import Finding, FindingItem
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "audio.loudness_normalize"
DEFAULT_TARGET_LUFS = -23.0
AUDIO_EXTENSIONS = (".wav", ".mp3", ".ogg")
# Bible acceptance criteria: outputs should land within +/-0.5 LUFS of target.
LUFS_TOLERANCE = 0.5


class FfmpegNotAvailableError(RuntimeError):
    """Raised when the `ffmpeg` binary (or a loudnorm-capable build of it) can't be found."""


def check_ffmpeg_available() -> None:
    """Raise ``FfmpegNotAvailableError`` if ``ffmpeg-normalize`` can't find a
    usable ``ffmpeg``. Call once before a batch, not per file."""
    try:
        FFmpegNormalize(normalization_type="ebu")
    except FFmpegNormalizeError as exc:
        raise FfmpegNotAvailableError(str(exc)) from exc


def output_dir_for(root_dir: str | Path) -> Path:
    root = Path(root_dir)
    return root.parent / f"{root.name}_normalized"


@dataclass(frozen=True)
class LoudnessResult:
    input_path: str
    output_path: str
    before_lufs: float | None
    after_lufs: float | None
    target_lufs: float
    status: str  # "normalized" | "error"
    error: str | None = None


def normalize_file(
    input_path: str | Path,
    output_dir: str | Path,
    target_lufs: float = DEFAULT_TARGET_LUFS,
) -> LoudnessResult:
    """Normalize one file, writing the result into ``output_dir`` under the
    same filename. Never modifies ``input_path``."""
    input_path = Path(input_path)
    output_path = Path(output_dir) / input_path.name

    # print_stats is left at its default (False): that flag only controls
    # whether ffmpeg-normalize itself dumps raw JSON to stdout, which would
    # collide with this module's own CLI output. Per-stream loudness stats
    # are read below via media_file.get_stats() regardless of this flag.
    normalizer = FFmpegNormalize(normalization_type="ebu", target_level=target_lufs)
    normalizer.add_media_file(str(input_path), str(output_path))
    normalizer.run_normalization()

    media_file = normalizer.media_files[0]
    if media_file.status == "error":
        return LoudnessResult(
            input_path=str(input_path),
            output_path=str(output_path),
            before_lufs=None,
            after_lufs=None,
            target_lufs=target_lufs,
            status="error",
            error=media_file.error or "ffmpeg-normalize failed for this file.",
        )

    before_lufs: float | None = None
    after_lufs: float | None = None
    for stream_stats in media_file.get_stats():
        pass1 = stream_stats.get("ebu_pass1") or {}
        pass2 = stream_stats.get("ebu_pass2") or {}
        if "input_i" in pass1:
            before_lufs = float(pass1["input_i"])
        if "output_i" in pass2:
            after_lufs = float(pass2["output_i"])
        break  # first audio stream is what "the file's loudness" means here

    return LoudnessResult(
        input_path=str(input_path),
        output_path=str(output_path),
        before_lufs=before_lufs,
        after_lufs=after_lufs,
        target_lufs=target_lufs,
        status="normalized",
    )


def _to_finding_item(result: LoudnessResult) -> FindingItem:
    if result.status == "error":
        return FindingItem(
            asset_path=result.input_path,
            severity="error",
            message=f"{Path(result.input_path).name}: {result.error}",
            detail={"target_lufs": result.target_lufs},
        )

    off_target = (
        result.after_lufs is not None
        and abs(result.after_lufs - result.target_lufs) > LUFS_TOLERANCE
    )
    name = Path(result.input_path).name
    if result.before_lufs is not None and result.after_lufs is not None:
        message = f"{name}: {result.before_lufs:.1f} -> {result.after_lufs:.1f} LUFS"
    else:
        message = f"{name}: normalized (loudness stats unavailable)"

    return FindingItem(
        asset_path=result.input_path,
        severity="warning" if off_target else "info",
        message=message,
        detail={
            "before_lufs": result.before_lufs,
            "after_lufs": result.after_lufs,
            "target_lufs": result.target_lufs,
            "output_path": result.output_path,
        },
    )


def _summarize(items: list[FindingItem], file_count: int) -> str:
    if file_count == 0:
        return "No audio files found to normalize."
    errors = sum(1 for i in items if i.severity == "error")
    off_target = sum(1 for i in items if i.severity == "warning")
    if errors:
        return (
            f"Normalized {file_count} file(s); {errors} failed, "
            f"{off_target} landed outside tolerance."
        )
    if off_target:
        return (
            f"Normalized {file_count} file(s); {off_target} landed outside the "
            f"+/-{LUFS_TOLERANCE} LUFS tolerance."
        )
    return f"Normalized {file_count} file(s) to target."


def normalize_folder(
    root_dir: str | Path,
    project_id: str,
    target_lufs: float = DEFAULT_TARGET_LUFS,
) -> Finding:
    """Batch-normalize every .wav/.mp3/.ogg file under ``root_dir`` to
    ``target_lufs``. Output goes to a sibling ``<root_dir>_normalized``
    folder; nothing under ``root_dir`` is ever written to.

    Raises ``FfmpegNotAvailableError`` up front if ffmpeg isn't usable --
    no files are touched in that case.
    """
    check_ffmpeg_available()
    output_dir = output_dir_for(root_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    runner = BatchRunner(FEATURE_ID, extensions=AUDIO_EXTENSIONS, summary_fn=_summarize)

    def callback(path: Path) -> FindingItem:
        result = normalize_file(path, output_dir, target_lufs=target_lufs)
        return _to_finding_item(result)

    return runner.run(root_dir, project_id, callback)


class LoudnessNormalizeService:
    """Wires ``normalize_folder`` to a real project (target LUFS setting,
    persisted Finding) for GUI/chatbox callers."""

    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def normalize(
        self,
        project: Project,
        folder_path: str | Path,
        *,
        target_lufs: float | None = None,
    ) -> tuple[Finding, AutomationFindingRecord]:
        """Normalize ``folder_path`` for ``project``.

        ``target_lufs`` lets a caller (e.g. a UI field) override the
        project's saved target for just this run without persisting it.
        Falls back to the project's saved setting, then
        ``DEFAULT_TARGET_LUFS``, when not given.
        """
        if target_lufs is None:
            target_lufs = project.loudness_normalize_target_lufs
        if target_lufs is None:
            target_lufs = DEFAULT_TARGET_LUFS
        finding = normalize_folder(folder_path, str(project.id), target_lufs=target_lufs)
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(
        self, project_id: int, limit: int = 20
    ) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-normalize-loudness",
        description=(
            "Batch-normalize a folder of .wav/.mp3/.ogg files to an EBU R128 loudness "
            "target. Output is written to a sibling '<folder>_normalized' directory; "
            "source files are never modified."
        ),
    )
    parser.add_argument("folder", help="Folder of audio files to normalize (scanned recursively).")
    parser.add_argument(
        "--target",
        type=float,
        default=DEFAULT_TARGET_LUFS,
        help=f"Target integrated loudness in LUFS (default: {DEFAULT_TARGET_LUFS}).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    try:
        finding = normalize_folder(args.folder, args.project_id, target_lufs=args.target)
    except FfmpegNotAvailableError as exc:
        print(f"ffmpeg is not available: {exc}", file=sys.stderr)
        print("See docs/loudness_normalize_ffmpeg.md for install instructions.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(finding.as_dict(), indent=2))
    else:
        print(finding.summary)
        for item in finding.items:
            print(f"  [{item.severity}] {item.message}")

    return 1 if finding.status == "error" else 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
