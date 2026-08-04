"""Pre-Commit Review use-case (Phase E, section 6, Core tier).

Local, deterministic checks over staged files — fast enough to run inside a
git ``pre-commit`` hook with no AI or network dependency: obvious TODOs,
stray ``Debug.Log``/``print`` statements, unresolved merge-conflict markers,
and extremely large staged files. This is a heads-up only, never a gate —
every caller (the installed hook, this module's own CLI entry point, and the
in-app "run now" action) always reports findings without ever failing a
commit because of them.

Invocation: the installed hook (``core.precommit_hook``) shells out to
``python -m spiced.core.precommit_check <project_path>`` directly rather than
a packaged console-script entry point. That was the simpler of the two
options the plan offered: it works immediately against an editable/dev
install with no ``pip install`` step needed after code changes, and the hook
script only needs to know a Python interpreter and this module's dotted
path — no dependency on Spiced's console scripts being on PATH inside
whatever shell git uses to run hooks.

Scope note on the "optional AI pass": the installed git hook itself only
ever runs the local checks below — no AI call, no database — so every commit
stays fast and works even before any provider is configured. A separate,
explicit "Get AI take" action (Projects/Testing screen, same threaded-worker
pattern as every other AI feature in the app) is where the optional AI
commentary actually happens; ``run_ai_pass`` below is what that action calls.
This keeps the hook itself trivial and dependency-free while still
delivering the optional AI pass as a real, available feature.
"""

from __future__ import annotations

import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

MAX_STAGED_FILE_BYTES = 5 * 1024 * 1024  # 5 MB — a heads-up threshold, not a hard limit.
DEFAULT_AI_TIMEOUT_S = 8.0

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK)\b")
_DEBUG_LOG_RE = re.compile(r"\bDebug\.Log(Warning|Error)?\s*\(")
_PRINT_RE = re.compile(r"(?<!\w)print\s*\(")
_MERGE_MARKER_RE = re.compile(r"^(<{7}|={7}|>{7})")

# Extensions worth scanning line-by-line — a project's actual source files,
# not every staged file type (binary assets, images, etc. are skipped).
_SCANNABLE_EXTS = {".cs", ".py", ".js", ".ts", ".shader", ".cginc"}

KIND_TODO = "todo"
KIND_DEBUG_STATEMENT = "debug_statement"
KIND_MERGE_CONFLICT = "merge_conflict"
KIND_LARGE_FILE = "large_file"


@dataclass(frozen=True)
class PrecommitFinding:
    file: str
    line: int | None
    kind: str
    message: str


def check_file(path: Path, *, max_bytes: int = MAX_STAGED_FILE_BYTES) -> list[PrecommitFinding]:
    """Run every local deterministic check on one staged file.

    Never raises — an unreadable file (binary, permission issue, already
    deleted between staging and the hook running) is silently skipped rather
    than blocking the whole hook.
    """
    findings: list[PrecommitFinding] = []
    try:
        size = path.stat().st_size
    except OSError:
        return findings

    if size > max_bytes:
        mb = size / (1024 * 1024)
        findings.append(
            PrecommitFinding(
                file=str(path),
                line=None,
                kind=KIND_LARGE_FILE,
                message=(
                    f"{mb:.1f} MB staged — worth double-checking this should be committed "
                    "(build output, a binary asset, or a large save/log file?)."
                ),
            )
        )

    if path.suffix.lower() not in _SCANNABLE_EXTS:
        return findings
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings

    for line_no, line in enumerate(text.splitlines(), start=1):
        if _MERGE_MARKER_RE.match(line):
            findings.append(
                PrecommitFinding(
                    file=str(path),
                    line=line_no,
                    kind=KIND_MERGE_CONFLICT,
                    message="Looks like an unresolved merge-conflict marker.",
                )
            )
        elif _TODO_RE.search(line):
            findings.append(
                PrecommitFinding(
                    file=str(path),
                    line=line_no,
                    kind=KIND_TODO,
                    message=f"TODO/FIXME/HACK left in: {line.strip()[:120]}",
                )
            )
        elif _DEBUG_LOG_RE.search(line) or _PRINT_RE.search(line):
            findings.append(
                PrecommitFinding(
                    file=str(path),
                    line=line_no,
                    kind=KIND_DEBUG_STATEMENT,
                    message=f"Possible stray debug output: {line.strip()[:120]}",
                )
            )
    return findings


def check_files(paths: list[Path]) -> list[PrecommitFinding]:
    findings: list[PrecommitFinding] = []
    for path in paths:
        findings.extend(check_file(path))
    return findings


def get_staged_files(project_path: str | Path) -> list[Path]:
    """Run ``git diff --cached --name-only`` and resolve results under the project.

    Returns ``[]`` (never raises) if git isn't available, the folder isn't a
    repo, or the command otherwise fails — callers treat that the same as
    "nothing staged" rather than a hard error.
    """
    import subprocess

    root = Path(project_path)
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [root / line.strip() for line in result.stdout.splitlines() if line.strip()]


def format_findings(findings: list[PrecommitFinding]) -> str:
    """Plain-text report git will show during ``git commit``."""
    if not findings:
        return "Spiced pre-commit review: no obvious issues found. (Heads-up only, not a gate.)"
    lines = [f"Spiced pre-commit review: {len(findings)} thing(s) worth a look "
              "(heads-up only — this never blocks the commit):"]
    for f in findings:
        where = f"{f.file}:{f.line}" if f.line is not None else f.file
        lines.append(f"  [{f.kind}] {where} — {f.message}")
    return "\n".join(lines)


def run_ai_pass(
    provider,
    findings: list[PrecommitFinding],
    file_count: int,
    timeout_s: float = DEFAULT_AI_TIMEOUT_S,
) -> str | None:
    """Best-effort, time-boxed AI commentary layered on the local findings.

    Returns None on any failure, timeout, or when the provider isn't
    available. Runs the provider call on a background thread and only waits
    up to ``timeout_s`` — genuinely optional per spec ("a heads-up, never a
    blocking gate"), so a slow or broken provider must never stall the
    caller (a git hook, or the in-app "Get AI take" action).
    """
    if provider is None or not provider.is_available():
        return None

    from spiced.ai.prompt_templates import build_precommit_review_prompt

    box: dict[str, str | None] = {"text": None}

    def _run() -> None:
        try:
            prompt = build_precommit_review_prompt(findings, file_count=file_count)
            box["text"] = provider.generate(prompt).text
        except Exception:
            box["text"] = None

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout_s)
    if thread.is_alive():
        return None
    return box["text"]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point the installed git hook calls.

    Always returns 0 (and the ``except`` below guarantees it even on an
    unexpected internal error) — a pre-commit review is a heads-up, never a
    gate, per spec. Invoked as ``python -m spiced.core.precommit_check
    <project_path>``.
    """
    args = argv if argv is not None else sys.argv[1:]
    try:
        if not args:
            print("Spiced pre-commit review: no project path given, skipping.")
            return 0
        project_path = args[0]
        staged = get_staged_files(project_path)
        if not staged:
            print("Spiced pre-commit review: nothing staged to check.")
            return 0
        findings = check_files(staged)
        print(format_findings(findings))
    except Exception as exc:  # never let an internal error block a commit
        print(f"Spiced pre-commit review: skipped due to an internal error ({exc}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
