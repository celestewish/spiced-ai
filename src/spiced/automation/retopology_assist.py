"""Retopology Assist (Implementation Bible, Feature 10).

Auto-retopologizes a mesh (quad-based remesh) as an artist's starting
point, since true adaptive quad retopology matching ZBrush's ZRemesher has
no strong free equivalent -- Blender's QuadriFlow remesher is the closest
free option, per the Bible's own scope decision.

**Mesh I/O**: reuses ``automation.uv_lod_generation.load_mesh`` (Feature
8) to validate/normalize the input format -- same ``.obj``/``.gltf``/
``.glb``-only limitation as that feature, for the same reason (no
reliable pure-Python ``.fbx`` loader) -- rather than re-deriving mesh
loading here.

**Remeshing**: QuadriFlow, invoked headlessly through Blender's Python API
(``bpy.ops.object.quadriflow_remesh``), run in a subprocess exactly like
Feature 8's xatlas unwrap step (``_uv_lod_worker.py``) -- a native remesh
crash must not take down the whole desktop app. Unlike Feature 8's
worker, which runs under Spiced's *own* Python interpreter
(``python -m spiced.automation._uv_lod_worker``), this one has to run
under Blender's *embedded* interpreter instead (``bpy`` isn't
pip-installable) -- the isolation Feature 8 had to build deliberately is
inherent here, since Blender is always a separate OS process.

**Blender is a system dependency**, the same category as ffmpeg for
Feature 1 -- see ``docs/blender_retopology_assist.md`` (documented in the
same place as ``docs/loudness_normalize_ffmpeg.md``). If Blender isn't
installed/discoverable on the host, this fails with a clear, actionable
``BlenderNotAvailableError`` rather than crashing or hanging.

**UNVERIFIED** -- like ``connectors.renderdoc_analysis`` (Feature 9), the
actual Blender-side script
(``automation._blender_quadriflow_worker.WORKER_SCRIPT_SOURCE``) has not
been run against a real Blender install in this environment (none is
available here). See that module's docstring for exactly what was and
wasn't verified. Every test in this codebase mocks the ``blender``
subprocess call itself, matching how Feature 9 mocks the RenderDoc worker.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from spiced.automation._blender_quadriflow_worker import WORKER_SCRIPT_SOURCE
from spiced.automation.finding import Finding, FindingItem
from spiced.automation.uv_lod_generation import (
    SUPPORTED_EXTENSIONS,
    UnreadableMeshError,
    UnsupportedMeshFormatError,
    load_mesh,
)
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository
from spiced.storage.projects import Project

FEATURE_ID = "art.retopology_assist"

DEFAULT_TARGET_FACE_COUNT = 5000
DEFAULT_WORKER_TIMEOUT_S = 300
# Bible acceptance criteria: output triangle/quad count should land within
# this fraction of the configured target.
TARGET_FACE_COUNT_TOLERANCE = 0.25
# A remesh with at least this fraction of its polygons as quads counts as
# "majority-quad" for the acceptance criteria.
MAJORITY_QUAD_FRACTION = 0.5


class BlenderNotAvailableError(RuntimeError):
    """Raised when a `blender` executable can't be found on the host."""


class RetopologyWorkerError(RuntimeError):
    """Raised when the Blender subprocess fails or crashes."""


def find_blender_executable(blender_path: str | None = None) -> str:
    """Resolves a usable Blender executable path, or raises
    ``BlenderNotAvailableError`` with a clear, actionable message. Checked
    once up front, matching ``loudness_normalize.check_ffmpeg_available``'s
    "fail clearly before any file is touched" approach."""
    if blender_path:
        if shutil.which(blender_path) or Path(blender_path).is_file():
            return blender_path
        raise BlenderNotAvailableError(
            f'"{blender_path}" was not found or is not executable.'
        )
    found = shutil.which("blender")
    if found:
        return found
    raise BlenderNotAvailableError(
        "Blender isn't installed or isn't on PATH. Retopology Assist needs Blender's QuadriFlow "
        "remesher -- install Blender (https://www.blender.org/download/) and either add it to "
        "PATH or pass its executable path explicitly. See docs/blender_retopology_assist.md."
    )


@dataclass(frozen=True)
class RetopologyStats:
    before_face_count: int
    after_face_count: int
    quad_count: int
    triangle_count: int
    other_polygon_count: int
    non_manifold_edge_count: int
    output_path: str

    @property
    def quad_ratio(self) -> float:
        return self.quad_count / self.after_face_count if self.after_face_count else 0.0


@dataclass(frozen=True)
class RetopologyWorkerResult:
    stats: RetopologyStats | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.stats is not None


def run_retopology_worker(
    blender_path: str,
    input_mesh_path: str | Path,
    output_mesh_path: str | Path,
    target_face_count: int,
    timeout_s: int = DEFAULT_WORKER_TIMEOUT_S,
) -> RetopologyWorkerResult:
    """Runs the QuadriFlow remesh for one mesh in a Blender subprocess (see
    module docstring for why) and returns the result, or a
    ``RetopologyWorkerResult`` with ``error`` set -- never raises for a
    subprocess failure/crash, matching Feature 8's
    ``generate_uv_lod_chain``/``_run_lod_worker`` "one bad item doesn't
    kill the whole run" contract."""
    with tempfile.TemporaryDirectory(prefix="spiced-retopology-") as tmp:
        script_path = Path(tmp) / "spiced_quadriflow_worker.py"
        result_path = Path(tmp) / "retopology_result.json"
        script_path.write_text(WORKER_SCRIPT_SOURCE, encoding="utf-8")

        command = [
            blender_path,
            "--background",
            "--python",
            str(script_path),
            "--",
            str(input_mesh_path),
            str(output_mesh_path),
            str(target_face_count),
            str(result_path),
        ]
        try:
            completed = subprocess.run(command, timeout=timeout_s, capture_output=True)
        except subprocess.TimeoutExpired:
            return RetopologyWorkerResult(
                error=f"Blender did not finish the remesh within {timeout_s}s and was stopped."
            )
        except OSError as exc:
            return RetopologyWorkerResult(error=f"Could not launch Blender: {exc}")

        if completed.returncode != 0 or not result_path.is_file():
            stderr_tail = completed.stderr.decode("utf-8", errors="replace")[-2000:]
            return RetopologyWorkerResult(
                error=(
                    f"Blender's remesh failed (exit code {completed.returncode}). This can "
                    f"happen on certain mesh topologies that trip a crash in QuadriFlow. "
                    f"{stderr_tail}".strip()
                )
            )

        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return RetopologyWorkerResult(
                error=f"Blender exited cleanly but wrote no readable result: {exc}"
            )

        return RetopologyWorkerResult(
            stats=RetopologyStats(
                before_face_count=int(data["before_face_count"]),
                after_face_count=int(data["after_face_count"]),
                quad_count=int(data["quad_count"]),
                triangle_count=int(data["triangle_count"]),
                other_polygon_count=int(data["other_polygon_count"]),
                non_manifold_edge_count=int(data["non_manifold_edge_count"]),
                output_path=data.get("output_path", str(output_mesh_path)),
            )
        )


def build_finding(
    result: RetopologyWorkerResult, project_id: str, mesh_path: str, *,
    target_face_count: int,
) -> Finding:
    if not result.succeeded:
        message = result.error or "Retopology failed for an unknown reason."
        return Finding(
            feature_id=FEATURE_ID, project_id=str(project_id), status="error", summary=message,
            items=[FindingItem(asset_path=mesh_path, severity="error", message=message)],
        )

    stats = result.stats
    items: list[FindingItem] = []

    within_tolerance = (
        abs(stats.after_face_count - target_face_count)
        <= target_face_count * TARGET_FACE_COUNT_TOLERANCE
    )
    items.append(
        FindingItem(
            asset_path=mesh_path,
            severity="info" if within_tolerance else "warning",
            message=(
                f"{stats.before_face_count} -> {stats.after_face_count} face(s) "
                f"(target {target_face_count})."
            ),
            detail={
                "issue_type": "face_count",
                "before_face_count": stats.before_face_count,
                "after_face_count": stats.after_face_count,
                "target_face_count": target_face_count,
                "within_tolerance": within_tolerance,
            },
        )
    )

    majority_quad = stats.quad_ratio >= MAJORITY_QUAD_FRACTION
    items.append(
        FindingItem(
            asset_path=mesh_path,
            severity="info" if majority_quad else "warning",
            message=(
                f"{stats.quad_count} quad(s) / {stats.triangle_count} triangle(s) / "
                f"{stats.other_polygon_count} other -- {stats.quad_ratio * 100:.1f}% quad."
            ),
            detail={
                "issue_type": "quad_ratio",
                "quad_count": stats.quad_count,
                "triangle_count": stats.triangle_count,
                "other_polygon_count": stats.other_polygon_count,
                "quad_ratio": round(stats.quad_ratio, 4),
            },
        )
    )

    if stats.non_manifold_edge_count:
        items.append(
            FindingItem(
                asset_path=mesh_path,
                severity="warning",
                message=f"{stats.non_manifold_edge_count} non-manifold edge(s) in the remesh.",
                detail={
                    "issue_type": "non_manifold_edges",
                    "non_manifold_edge_count": stats.non_manifold_edge_count,
                },
            )
        )
    else:
        items.append(
            FindingItem(
                asset_path=mesh_path,
                severity="info",
                message="No non-manifold edges in the remesh.",
                detail={"issue_type": "non_manifold_edges", "non_manifold_edge_count": 0},
            )
        )

    status = Finding.status_for(items)
    summary = (
        f"Remeshed to {stats.after_face_count} face(s), {stats.quad_ratio * 100:.1f}% quad, "
        f"{stats.non_manifold_edge_count} non-manifold edge(s)."
    )
    return Finding(
        feature_id=FEATURE_ID, project_id=str(project_id), status=status, summary=summary,
        items=items,
    )


@dataclass(frozen=True)
class RetopologyRunResult:
    finding: Finding
    output_path: str | None = None


def run_retopology_assist(
    mesh_path: str | Path,
    project_id: str,
    *,
    output_path: str | Path | None = None,
    blender_path: str | None = None,
    target_face_count: int = DEFAULT_TARGET_FACE_COUNT,
    timeout_s: int = DEFAULT_WORKER_TIMEOUT_S,
) -> RetopologyRunResult:
    mesh_path = Path(mesh_path)
    try:
        load_mesh(mesh_path)  # validates/normalizes format; reused from Feature 8
    except (UnsupportedMeshFormatError, UnreadableMeshError) as exc:
        finding = Finding(
            feature_id=FEATURE_ID, project_id=str(project_id), status="error", summary=str(exc),
            items=[FindingItem(asset_path=str(mesh_path), severity="error", message=str(exc))],
        )
        return RetopologyRunResult(finding=finding)

    try:
        resolved_blender = find_blender_executable(blender_path)
    except BlenderNotAvailableError as exc:
        finding = Finding(
            feature_id=FEATURE_ID, project_id=str(project_id), status="error", summary=str(exc),
            items=[FindingItem(asset_path=str(mesh_path), severity="error", message=str(exc))],
        )
        return RetopologyRunResult(finding=finding)

    if output_path is None:
        output_path = mesh_path.with_name(f"{mesh_path.stem}_retopo{mesh_path.suffix}")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    result = run_retopology_worker(
        resolved_blender, mesh_path, output_path, target_face_count, timeout_s=timeout_s
    )
    finding = build_finding(
        result, project_id, str(mesh_path), target_face_count=target_face_count
    )
    return RetopologyRunResult(
        finding=finding, output_path=str(output_path) if result.succeeded else None
    )


class RetopologyAssistService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def retopologize(
        self,
        project: Project,
        mesh_path: str | Path,
        *,
        output_path: str | Path | None = None,
        blender_path: str | None = None,
        target_face_count: int = DEFAULT_TARGET_FACE_COUNT,
    ) -> tuple[RetopologyRunResult, AutomationFindingRecord]:
        result = run_retopology_assist(
            mesh_path, str(project.id), output_path=output_path, blender_path=blender_path,
            target_face_count=target_face_count,
        )
        record = self._findings.create(project.id, result.finding)
        return result, record

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-retopology-assist",
        description=(
            "Auto-retopologize a mesh (quad-based remesh via Blender's QuadriFlow) as an "
            "artist's starting point. Supported formats: "
            f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}."
        ),
    )
    parser.add_argument("mesh_path", help="Path to the source mesh file.")
    parser.add_argument("--output", default=None, help="Output mesh path (default: <name>_retopo).")
    parser.add_argument("--blender-path", default=None, help="Blender executable (default: PATH).")
    parser.add_argument(
        "--target-faces", type=int, default=DEFAULT_TARGET_FACE_COUNT,
        help=f"Target face count for the remesh (default: {DEFAULT_TARGET_FACE_COUNT}).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    result = run_retopology_assist(
        args.mesh_path, args.project_id, output_path=args.output, blender_path=args.blender_path,
        target_face_count=args.target_faces,
    )

    if args.json:
        print(json.dumps(result.finding.as_dict(), indent=2))
    else:
        print(result.finding.summary)
        for item in result.finding.items:
            print(f"  [{item.severity}] {item.message}")

    return 1 if result.finding.status == "error" else 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
