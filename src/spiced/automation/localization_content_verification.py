"""Localization Audio Sync Checker, Content Verification (Implementation
Bible, Feature 13).

Verifies a voice recording's actual **spoken content** matches the current
script line -- the exact gap ``core.localization_audio_sync`` documents as
out of scope for itself (a staleness/coverage heuristic only, "Spiced
cannot listen to or transcribe these recordings"). This module is that
real content-verification path, kept side by side with that existing
module rather than replacing it: it reuses that module's
``infer_line_id_from_filename``/``scan_voice_folder`` matching logic
directly instead of re-implementing it, and adds a new, distinct
``content_mismatch`` category on top of its existing
``stale_recordings``/``missing_audio`` categories.

**Speech-to-text**: self-hosted ``faster-whisper``, fully local -- no
audio ever leaves the machine (see
``docs/faster_whisper_model_caching.md`` for the model download/caching
behavior). Runs in a subprocess (``automation._stt_worker``), the same
isolation pattern Feature 8 uses for its xatlas unwrap step -- a heavier
native/ML dependency shouldn't be able to crash the host process either.

**Similarity scoring**: deliberately simple -- normalize case/punctuation,
then ``difflib.SequenceMatcher.ratio()`` (a standard-library edit-distance-
style ratio in [0, 1]). Per the Bible's own instruction not to
over-engineer this into an NLP project, there's no tokenization/stemming/
embedding model here, just a straightforward string-similarity measure.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from spiced.automation.finding import Finding, FindingItem
from spiced.core.localization_audio_sync import (
    ScriptLine,
    VoiceLineFile,
    _normalize_line_id,
    infer_line_id_from_filename,
    scan_voice_folder,
)
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "audio.localization_content_verification"

DEFAULT_SIMILARITY_THRESHOLD = 0.6
DEFAULT_MODEL_SIZE = "tiny.en"
DEFAULT_DEVICE = "cpu"
DEFAULT_COMPUTE_TYPE = "int8"
DEFAULT_TIMEOUT_S = 300

_PUNCTUATION_RE = re.compile(r"[^\w\s]")

CAVEAT = (
    "Content verification via local speech-to-text -- distinct from the file-timestamp "
    "staleness/coverage check (Localization Audio Sync). Transcription accuracy depends on the "
    "model size and audio quality; a low similarity score is worth a listen, not an automatic "
    "confirmation of a mismatch, especially for short lines or heavy accents/background noise."
)


def normalize_text(text: str) -> str:
    lowered = text.lower()
    stripped = _PUNCTUATION_RE.sub("", lowered)
    return " ".join(stripped.split())


def text_similarity(a: str, b: str) -> float:
    """A straightforward string-similarity ratio in [0, 1] -- 1.0 means
    the normalized texts are identical, 0.0 means nothing in common.
    Deliberately not an NLP model; see module docstring."""
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


@dataclass(frozen=True)
class STTResult:
    text: str | None = None
    error: str | None = None
    stt_unavailable: bool = False

    @property
    def succeeded(self) -> bool:
        return self.text is not None


def run_stt_transcription(
    audio_path: str | Path,
    *,
    model_size: str = DEFAULT_MODEL_SIZE,
    device: str = DEFAULT_DEVICE,
    compute_type: str = DEFAULT_COMPUTE_TYPE,
    python_executable: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> STTResult:
    """Transcribes one audio file in a subprocess (see module docstring
    for why) and returns the result -- never raises for a worker
    failure/crash."""
    python_exe = python_executable or sys.executable
    command = [
        python_exe, "-m", "spiced.automation._stt_worker", str(audio_path), model_size, device,
        compute_type,
    ]

    try:
        completed = subprocess.run(command, timeout=timeout_s, capture_output=True)
    except subprocess.TimeoutExpired:
        return STTResult(error=f"Transcription timed out after {timeout_s}s.")
    except OSError as exc:
        return STTResult(error=f"Could not launch the transcription worker: {exc}")

    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr_tail = completed.stderr.decode("utf-8", errors="replace")[-2000:]

    if completed.returncode != 0:
        if "STT_NOT_AVAILABLE" in stdout:
            return STTResult(
                error=(
                    "faster-whisper couldn't be imported. Check that it's installed (see "
                    f"docs/faster_whisper_model_caching.md). {stderr_tail}".strip()
                ),
                stt_unavailable=True,
            )
        return STTResult(
            error=f"Transcription failed (exit code {completed.returncode}). {stderr_tail}".strip()
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return STTResult(error=f"Transcription produced unreadable output. {stderr_tail}".strip())

    return STTResult(text=data.get("text", ""))


@dataclass(frozen=True)
class MatchedVoiceLine:
    script_line: ScriptLine
    voice_file: VoiceLineFile


def match_voice_to_script(
    script_lines: list[ScriptLine], voice_files: list[VoiceLineFile]
) -> tuple[list[MatchedVoiceLine], list[ScriptLine]]:
    """Same line-ID matching as ``core.localization_audio_sync.
    scan_localization_audio_sync`` (newest audio file per line ID wins),
    reused rather than re-implemented. Returns matched pairs and the
    script lines with no matching audio at all."""
    by_line_id: dict[str, list[VoiceLineFile]] = {}
    for vf in voice_files:
        line_id = vf.line_id or infer_line_id_from_filename(Path(vf.path).name)
        if line_id is None:
            continue
        by_line_id.setdefault(_normalize_line_id(line_id), []).append(vf)

    matched: list[MatchedVoiceLine] = []
    missing: list[ScriptLine] = []
    for line in script_lines:
        candidates = by_line_id.get(_normalize_line_id(line.line_id))
        if not candidates:
            missing.append(line)
            continue
        newest = max(candidates, key=lambda v: v.last_modified)
        matched.append(MatchedVoiceLine(script_line=line, voice_file=newest))
    return matched, missing


def build_finding(
    results: list[tuple[MatchedVoiceLine, STTResult, float]],
    project_id: str,
    *,
    threshold: float,
) -> Finding:
    items: list[FindingItem] = []
    for matched, stt, score in results:
        line = matched.script_line
        if not stt.succeeded:
            items.append(
                FindingItem(
                    asset_path=matched.voice_file.path,
                    severity="error",
                    message=f"{line.line_id}: transcription failed -- {stt.error}",
                    detail={"issue_type": "transcription_error", "line_id": line.line_id},
                )
            )
            continue
        mismatch = score < threshold
        items.append(
            FindingItem(
                asset_path=matched.voice_file.path,
                severity="warning" if mismatch else "info",
                message=(
                    f'{line.line_id}: similarity {score:.2f} '
                    f'({"below" if mismatch else "at/above"} threshold {threshold:.2f}).'
                ),
                detail={
                    "issue_type": "content_mismatch" if mismatch else "content_match",
                    "line_id": line.line_id,
                    "transcribed_text": stt.text,
                    "script_text": line.text,
                    "similarity_score": round(score, 4),
                    "threshold": threshold,
                },
            )
        )

    status = Finding.status_for(items)
    summary = _summarize(items)
    return Finding(
        feature_id=FEATURE_ID, project_id=str(project_id), status=status, summary=summary,
        items=items,
    )


def _summarize(items: list[FindingItem]) -> str:
    if not items:
        return "No matched script/audio pairs to check."
    mismatches = sum(1 for i in items if i.detail.get("issue_type") == "content_mismatch")
    errors = sum(1 for i in items if i.detail.get("issue_type") == "transcription_error")
    if errors:
        return (
            f"Checked {len(items)} line(s); {errors} transcription error(s), "
            f"{mismatches} mismatch(es)."
        )
    if mismatches:
        return f"Checked {len(items)} line(s); {mismatches} content mismatch(es) found."
    return f"Checked {len(items)} line(s); all match the script text."


def verify_localization_audio_content(
    script_lines: list[ScriptLine],
    voice_files: list[VoiceLineFile],
    project_id: str,
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    model_size: str = DEFAULT_MODEL_SIZE,
) -> Finding:
    matched, _missing = match_voice_to_script(script_lines, voice_files)
    results = []
    for m in matched:
        stt = run_stt_transcription(m.voice_file.path, model_size=model_size)
        score = text_similarity(stt.text, m.script_line.text) if stt.succeeded else 0.0
        results.append((m, stt, score))
    return build_finding(results, project_id, threshold=threshold)


def run_localization_content_check(
    script_text: str,
    voice_folder: str | Path,
    project_id: str,
    *,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    model_size: str = DEFAULT_MODEL_SIZE,
) -> Finding:
    """Convenience entry point matching the paste-format
    ``core.localization_audio_sync.parse_script_lines`` UI convention."""
    from spiced.core.localization_audio_sync import parse_script_lines

    script_lines = parse_script_lines(script_text, last_modified=0.0)
    voice_files = scan_voice_folder(voice_folder)
    return verify_localization_audio_content(
        script_lines, voice_files, project_id, threshold=threshold, model_size=model_size
    )


class LocalizationContentVerificationService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def check(
        self,
        project: Project,
        script_text: str,
        voice_folder: str | Path,
        *,
        threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> tuple[Finding, AutomationFindingRecord]:
        finding = run_localization_content_check(
            script_text, voice_folder, str(project.id), threshold=threshold
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-localization-audio-content-check",
        description=(
            "Verify voice-line recordings' actual spoken content matches the current script "
            "text, via local speech-to-text (faster-whisper)."
        ),
    )
    parser.add_argument(
        "script_file", help="Path to a text file of script lines, one per row as: line_id,text"
    )
    parser.add_argument("voice_folder", help="Folder of voice-line audio files.")
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_SIMILARITY_THRESHOLD,
        help=(
            "Similarity threshold below which a line is flagged "
            f"(default: {DEFAULT_SIMILARITY_THRESHOLD})."
        ),
    )
    parser.add_argument(
        "--model-size", default=DEFAULT_MODEL_SIZE,
        help=f"faster-whisper model size (default: {DEFAULT_MODEL_SIZE}).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    script_text = Path(args.script_file).read_text(encoding="utf-8", errors="replace")
    finding = run_localization_content_check(
        script_text, args.voice_folder, args.project_id, threshold=args.threshold,
        model_size=args.model_size,
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
