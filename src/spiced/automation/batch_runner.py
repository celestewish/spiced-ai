"""Shared BatchRunner (Implementation Bible, Feature 0).

Every automation feature operates on a directory or asset list, not a
single file at a time. This is the one shared "walk a directory, filter by
extension, run a per-file callback, collect results, produce a Finding"
utility every feature module (audio normalization, visual regression,
asset QA, ...) reuses, instead of rewriting file-walking and result-
aggregation logic once per feature. See the Bible's section 0, "Batch job
pattern".
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from spiced.automation.finding import SEVERITY_ERROR, SEVERITY_INFO, Finding, FindingItem

PerFileCallback = Callable[[Path], "FindingItem | Iterable[FindingItem] | None"]
SummaryFn = Callable[[list[FindingItem], int], str]


def _default_summary(items: list[FindingItem], file_count: int) -> str:
    if file_count == 0:
        return "No matching files found."
    flagged = sum(1 for i in items if i.severity != SEVERITY_INFO)
    if flagged == 0:
        return f"Scanned {file_count} file(s); no issues found."
    return f"Scanned {file_count} file(s); {flagged} issue(s) flagged."


class BatchRunner:
    """Walks a directory, runs ``callback`` per matching file, and collects
    the results into one ``Finding``. A callback that raises is not fatal to
    the batch -- it's caught and turned into an 'error'-severity FindingItem
    for that one file, so one bad asset never aborts the whole run."""

    def __init__(
        self,
        feature_id: str,
        *,
        extensions: Iterable[str] | None = None,
        recursive: bool = True,
        summary_fn: SummaryFn | None = None,
    ) -> None:
        self.feature_id = feature_id
        self.extensions = (
            {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}
            if extensions is not None
            else None
        )
        self.recursive = recursive
        self.summary_fn = summary_fn or _default_summary

    def iter_files(self, root_dir: str | Path) -> list[Path]:
        root = Path(root_dir)
        if not root.is_dir():
            return []
        walker = root.rglob("*") if self.recursive else root.glob("*")
        files = [p for p in walker if p.is_file()]
        if self.extensions is not None:
            files = [p for p in files if p.suffix.lower() in self.extensions]
        return sorted(files)

    def run(self, root_dir: str | Path, project_id: str, callback: PerFileCallback) -> Finding:
        files = self.iter_files(root_dir)
        items: list[FindingItem] = []
        for path in files:
            try:
                result = callback(path)
            except Exception as exc:
                items.append(
                    FindingItem(
                        asset_path=str(path),
                        severity=SEVERITY_ERROR,
                        message=f"{path.name}: {exc}",
                        detail={"exception_type": type(exc).__name__},
                    )
                )
                continue
            if result is None:
                continue
            if isinstance(result, FindingItem):
                items.append(result)
            else:
                items.extend(result)

        status = Finding.status_for(items)
        summary = self.summary_fn(items, len(files))
        return Finding(
            feature_id=self.feature_id,
            project_id=str(project_id),
            status=status,
            summary=summary,
            items=items,
        )
