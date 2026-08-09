"""Mix Technical QA (Implementation Bible, Feature 5).

Detects clipping and silence gaps across an audio library, reporting actual
timestamped regions (not just a pass/fail flag). Reuses
``core.mix_level_qa._read_pcm_channel0`` for the proven WAV/PCM decoding
step (stdlib ``wave``/``array`` only, no ``audioop`` -- see that module's
docstring for why) rather than re-deriving 8-bit/16-bit/byte-order handling;
this module's own job is the two things that decoding step doesn't already
do: reporting clipping as timestamped *regions* (the legacy module only
exposes a boolean "clipping risk"), and a configurable silence-duration
threshold (the legacy module hardcodes 2 seconds; the Bible wants a
project-configurable default of 300ms).

WAV only, same documented reason as ``core.mix_level_qa``: decoding
``.mp3``/``.ogg`` needs a new third-party dependency this module doesn't add.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from spiced.automation.batch_runner import BatchRunner
from spiced.automation.finding import Finding, FindingItem
from spiced.core.mix_level_qa import _read_pcm_channel0
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "audio.mix_technical_qa"

# "at/near max amplitude (+/-0.1% of full scale)" per the Bible -- distinct
# from core.mix_level_qa.CLIPPING_RATIO_THRESHOLD (0.98), which is a looser
# "clipping risk" heuristic for a different feature.
CLIPPING_NEAR_MAX_RATIO = 0.999
# "longer than a few samples" -- a small, documented number of samples.
DEFAULT_MIN_CLIP_RUN_SAMPLES = 3

SILENCE_THRESHOLD_RATIO = 0.02
DEFAULT_SILENCE_MS = 300.0

AUDIO_EXTENSIONS = (".wav",)


@dataclass(frozen=True)
class Region:
    start_ms: float
    end_ms: float

    def as_dict(self) -> dict:
        return {"start_ms": round(self.start_ms, 1), "end_ms": round(self.end_ms, 1)}


def find_clipping_regions(
    samples: list[int],
    rate: int,
    max_val: int,
    *,
    ratio_threshold: float = CLIPPING_NEAR_MAX_RATIO,
    min_run_samples: int = DEFAULT_MIN_CLIP_RUN_SAMPLES,
) -> list[Region]:
    if not samples or rate <= 0:
        return []
    threshold = max_val * ratio_threshold
    regions: list[Region] = []
    run_start: int | None = None
    for i, s in enumerate(samples):
        if abs(s) >= threshold:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and i - run_start >= min_run_samples:
                regions.append(Region(run_start / rate * 1000, i / rate * 1000))
            run_start = None
    if run_start is not None and len(samples) - run_start >= min_run_samples:
        regions.append(Region(run_start / rate * 1000, len(samples) / rate * 1000))
    return regions


def find_silence_regions(
    samples: list[int],
    rate: int,
    max_val: int,
    *,
    threshold_ratio: float = SILENCE_THRESHOLD_RATIO,
    min_silence_ms: float = DEFAULT_SILENCE_MS,
) -> list[Region]:
    """Silence regions strictly *inside* the file -- a run touching the very
    start or extending to the very end is excluded, since that's usually
    intentional lead-in/lead-out silence, not a mixing mistake."""
    if not samples or rate <= 0:
        return []
    threshold = max_val * threshold_ratio
    min_run = int(min_silence_ms / 1000 * rate)
    regions: list[Region] = []
    run_start: int | None = None
    for i, s in enumerate(samples):
        if abs(s) <= threshold:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and run_start > 0 and i - run_start >= min_run:
                regions.append(Region(run_start / rate * 1000, i / rate * 1000))
            run_start = None
    # A trailing run always extends to the file's end, so it's never added --
    # matches the "not at the start/end of the file" rule above.
    return regions


def check_mix_technical_qa(
    path: str | Path,
    *,
    clipping_ratio_threshold: float = CLIPPING_NEAR_MAX_RATIO,
    min_clip_run_samples: int = DEFAULT_MIN_CLIP_RUN_SAMPLES,
    silence_threshold_ratio: float = SILENCE_THRESHOLD_RATIO,
    min_silence_ms: float = DEFAULT_SILENCE_MS,
) -> FindingItem:
    samples, rate, _channels, _sample_width, max_val = _read_pcm_channel0(path)
    clipping = find_clipping_regions(
        samples,
        rate,
        max_val,
        ratio_threshold=clipping_ratio_threshold,
        min_run_samples=min_clip_run_samples,
    )
    silence = find_silence_regions(
        samples,
        rate,
        max_val,
        threshold_ratio=silence_threshold_ratio,
        min_silence_ms=min_silence_ms,
    )

    name = Path(path).name
    if not clipping and not silence:
        return FindingItem(
            asset_path=str(path),
            severity="info",
            message=f"{name}: no clipping or silence issues found.",
        )

    parts = []
    if clipping:
        parts.append(f"{len(clipping)} clipping region(s)")
    if silence:
        parts.append(f"{len(silence)} silence gap(s)")
    return FindingItem(
        asset_path=str(path),
        severity="warning",
        message=f"{name}: " + ", ".join(parts) + ".",
        detail={
            "clipping_regions": [r.as_dict() for r in clipping],
            "silence_regions": [r.as_dict() for r in silence],
        },
    )


def _summarize(items: list[FindingItem], file_count: int) -> str:
    if file_count == 0:
        return "No WAV files found to check."
    errors = sum(1 for i in items if i.severity == "error")
    flagged = sum(1 for i in items if i.severity == "warning")
    if errors:
        return f"Checked {file_count} file(s); {errors} unreadable, {flagged} flagged."
    if flagged:
        return f"Checked {file_count} file(s); {flagged} flagged for clipping or silence gaps."
    return f"Checked {file_count} file(s); no clipping or silence issues found."


def scan_folder_for_mix_qa(
    folder_path: str | Path,
    project_id: str,
    *,
    min_silence_ms: float = DEFAULT_SILENCE_MS,
) -> Finding:
    runner = BatchRunner(FEATURE_ID, extensions=AUDIO_EXTENSIONS, summary_fn=_summarize)

    def callback(path: Path) -> FindingItem:
        return check_mix_technical_qa(path, min_silence_ms=min_silence_ms)

    return runner.run(folder_path, project_id, callback)


class MixTechnicalQaService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def scan(
        self, project: Project, folder_path: str | Path
    ) -> tuple[Finding, AutomationFindingRecord]:
        min_silence_ms = (
            project.mix_qa_silence_ms
            if project.mix_qa_silence_ms is not None
            else DEFAULT_SILENCE_MS
        )
        finding = scan_folder_for_mix_qa(
            folder_path, str(project.id), min_silence_ms=min_silence_ms
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-mix-technical-qa",
        description="Scan a folder of .wav files for clipping and silence gaps, with timestamps.",
    )
    parser.add_argument("folder", help="Folder of WAV files to check (scanned recursively).")
    parser.add_argument(
        "--min-silence-ms",
        type=float,
        default=DEFAULT_SILENCE_MS,
        help=f"Minimum silent-region duration to flag, in ms (default: {DEFAULT_SILENCE_MS}).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    finding = scan_folder_for_mix_qa(
        args.folder, args.project_id, min_silence_ms=args.min_silence_ms
    )

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
