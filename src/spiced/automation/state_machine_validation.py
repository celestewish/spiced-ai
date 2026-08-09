"""State Machine & Retarget Validation (Implementation Bible, Feature 7).

Two checks, either runnable alone:

1. **State machine validation** -- unreachable states and missing
   transition targets reuse ``core.animation_state_machine_check`` /
   ``connectors.unity_controller_scan`` directly (already built, and
   verified against a real Unity-generated ``.controller`` file -- see
   that connector's docstring). "Dead-end" states (zero outgoing
   transitions) is the one check added here, using the same parsed
   ``.controller`` data.
2. **Retarget validation** -- needs live engine data (a rigged model's bone
   hierarchy isn't reliably readable from a raw ``.fbx``), so it goes
   through ``connectors.unity_skeleton_export``, matching the "documented
   API over guessed file format" approach Features 2/3/6 already
   established. A source bone is "unmapped" if no target bone matches it
   either exactly or after stripping a known naming-convention prefix
   (default: ``mixamorig:``, Mixamo's real, well-known rig-naming
   convention) -- configurable per project.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from spiced.automation.finding import Finding, FindingItem
from spiced.connectors.unity_controller_scan import ParsedController, scan_controllers
from spiced.connectors.unity_skeleton_export import SkeletonExportRunResult, run_export
from spiced.core.animation_state_machine_check import scan_state_machines
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "animation.state_machine_retarget_validation"

DEFAULT_ALIAS_PREFIXES: tuple[str, ...] = ("mixamorig:",)

CAVEAT = (
    "State machine checks are static structural analysis of saved .controller files -- "
    "'unreachable'/'dead end' don't account for a script calling Animator.Play()/CrossFade() by "
    "name directly, which isn't visible from the file alone. Retarget checks compare bone *names* "
    "only, via Unity's live Transform hierarchy -- they don't verify bone rotation/scale "
    "compatibility between skeletons."
)


@dataclass(frozen=True)
class DeadEndStateFinding:
    controller_file: str
    state_name: str | None
    state_file_id: str


def find_dead_end_states(controllers: list[ParsedController]) -> list[DeadEndStateFinding]:
    """States with zero outgoing transitions -- the animator can never
    leave them via the state machine's own graph."""
    dead_ends = []
    for controller in controllers:
        for state in controller.states.values():
            if not state.transition_ids:
                dead_ends.append(
                    DeadEndStateFinding(controller.path, state.name, state.file_id)
                )
    return dead_ends


def check_state_machines(project_path: str | Path) -> list[FindingItem]:
    """Unreachable states, missing transition targets (reused from
    ``core.animation_state_machine_check``), and dead-end states."""
    scan_result = scan_state_machines(project_path)
    controllers = scan_controllers(project_path)
    dead_ends = find_dead_end_states(controllers)

    items: list[FindingItem] = []
    for f in scan_result.unreachable_states:
        state_label = f.state_name or f.state_file_id
        items.append(
            FindingItem(
                asset_path=f.controller_file,
                severity="warning",
                message=f'{f.controller_file}: state "{state_label}" is unreachable.',
                detail={"issue_type": "unreachable_state", "state_name": f.state_name},
            )
        )
    for f in scan_result.missing_targets:
        items.append(
            FindingItem(
                asset_path=f.controller_file,
                severity="warning",
                message=(
                    f"{f.controller_file}: transition references a missing {f.missing_kind} "
                    f"(fileID {f.missing_file_id})."
                ),
                detail={"issue_type": "missing_transition_target", "missing_kind": f.missing_kind},
            )
        )
    for d in dead_ends:
        items.append(
            FindingItem(
                asset_path=d.controller_file,
                severity="warning",
                message=(
                    f"{d.controller_file}: state \"{d.state_name or d.state_file_id}\" has no "
                    "outgoing transitions (dead end)."
                ),
                detail={"issue_type": "dead_end_state", "state_name": d.state_name},
            )
        )
    return items


def normalize_bone_name(name: str, alias_prefixes: tuple[str, ...] = DEFAULT_ALIAS_PREFIXES) -> str:
    lowered = name.strip().lower()
    for prefix in alias_prefixes:
        if lowered.startswith(prefix.lower()):
            lowered = lowered[len(prefix) :]
            break
    return lowered


def diff_skeletons(
    source_bones: list[str],
    target_bones: list[str],
    *,
    alias_prefixes: tuple[str, ...] = DEFAULT_ALIAS_PREFIXES,
) -> list[str]:
    """Bones present in ``source_bones`` with no exact-or-normalized match
    in ``target_bones``."""
    target_normalized = {normalize_bone_name(b, alias_prefixes) for b in target_bones}
    return [
        b for b in source_bones if normalize_bone_name(b, alias_prefixes) not in target_normalized
    ]


def check_retarget(
    unity_path: str,
    project_path: str | Path,
    source_model_path: str,
    target_model_path: str,
    *,
    alias_prefixes: tuple[str, ...] = DEFAULT_ALIAS_PREFIXES,
    timeout_s: int = 600,
) -> list[FindingItem]:
    result: SkeletonExportRunResult = run_export(
        unity_path, str(project_path), [source_model_path, target_model_path], timeout_s=timeout_s
    )
    if result.error is not None:
        return [
            FindingItem(
                asset_path=source_model_path,
                severity="error",
                message=f"Retarget check failed: {result.error}",
            )
        ]

    by_path = {o.model_path: o for o in result.outcomes}
    source = by_path.get(source_model_path)
    target = by_path.get(target_model_path)
    items: list[FindingItem] = []
    for label, outcome, path in (
        ("source", source, source_model_path),
        ("target", target, target_model_path),
    ):
        if outcome is None or not outcome.succeeded:
            error = outcome.error if outcome is not None else "no result returned for this model"
            items.append(
                FindingItem(
                    asset_path=path,
                    severity="error",
                    message=f"Couldn't read the {label} skeleton ({path}): {error}",
                )
            )
    if items:
        return items

    unmapped = diff_skeletons(
        source.bone_names or [], target.bone_names or [], alias_prefixes=alias_prefixes
    )
    if not unmapped:
        return [
            FindingItem(
                asset_path=source_model_path,
                severity="info",
                message=f"Every bone in {Path(source_model_path).name} has a match in "
                f"{Path(target_model_path).name}.",
            )
        ]
    for bone in unmapped:
        items.append(
            FindingItem(
                asset_path=source_model_path,
                severity="warning",
                message=f'"{bone}" has no mapped equivalent in {Path(target_model_path).name}.',
                detail={
                    "issue_type": "unmapped_bone",
                    "bone_name": bone,
                    "target": target_model_path,
                },
            )
        )
    return items


def _summarize(items: list[FindingItem]) -> str:
    if not items:
        return "No state machines or skeletons checked."
    errors = sum(1 for i in items if i.severity == "error")
    flagged = sum(1 for i in items if i.severity == "warning")
    if errors:
        return f"{errors} check(s) failed, {flagged} issue(s) flagged."
    if flagged:
        return f"{flagged} issue(s) flagged."
    return "No unreachable states, dead ends, or unmapped bones found."


def run_state_machine_retarget_validation(
    project_path: str | Path,
    project_id: str,
    *,
    check_states: bool = True,
    unity_path: str | None = None,
    source_model_path: str | None = None,
    target_model_path: str | None = None,
    alias_prefixes: tuple[str, ...] = DEFAULT_ALIAS_PREFIXES,
    timeout_s: int = 600,
) -> Finding:
    items: list[FindingItem] = []
    if check_states:
        items.extend(check_state_machines(project_path))
    if unity_path and source_model_path and target_model_path:
        items.extend(
            check_retarget(
                unity_path,
                project_path,
                source_model_path,
                target_model_path,
                alias_prefixes=alias_prefixes,
                timeout_s=timeout_s,
            )
        )

    status = Finding.status_for(items)
    return Finding(
        feature_id=FEATURE_ID,
        project_id=str(project_id),
        status=status,
        summary=_summarize(items),
        items=items,
    )


class StateMachineValidationService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def check_states(self, project: Project) -> tuple[Finding, AutomationFindingRecord]:
        finding = run_state_machine_retarget_validation(project.path, str(project.id))
        record = self._findings.create(project.id, finding)
        return finding, record

    def check_retarget(
        self,
        project: Project,
        unity_path: str,
        source_model_path: str,
        target_model_path: str,
    ) -> tuple[Finding, AutomationFindingRecord]:
        alias_prefixes = DEFAULT_ALIAS_PREFIXES
        if project.retarget_alias_prefixes:
            alias_prefixes = tuple(
                p.strip() for p in project.retarget_alias_prefixes.split(",") if p.strip()
            )
        finding = run_state_machine_retarget_validation(
            project.path,
            str(project.id),
            check_states=False,
            unity_path=unity_path,
            source_model_path=source_model_path,
            target_model_path=target_model_path,
            alias_prefixes=alias_prefixes,
        )
        record = self._findings.create(project.id, finding)
        return finding, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-state-machine-retarget-validation",
        description=(
            "Check an animation state machine for unreachable/dead-end states, and/or validate a "
            "retarget mapping between two skeletons' bone names."
        ),
    )
    parser.add_argument("project_path", help="Path to the Unity project folder.")
    parser.add_argument(
        "--skip-states",
        action="store_true",
        help="Skip the state-machine unreachable/dead-end check.",
    )
    parser.add_argument(
        "--unity-path", default=None, help="Unity Editor executable (for retarget check)."
    )
    parser.add_argument(
        "--source-model", default=None, help="Source model asset path (retarget check)."
    )
    parser.add_argument(
        "--target-model", default=None, help="Target model asset path (retarget check)."
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    finding = run_state_machine_retarget_validation(
        args.project_path,
        args.project_id,
        check_states=not args.skip_states,
        unity_path=args.unity_path,
        source_model_path=args.source_model,
        target_model_path=args.target_model,
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
