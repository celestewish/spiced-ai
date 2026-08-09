"""UV Unwrapping + LOD Generation (Implementation Bible, Feature 8).

Auto-unwraps UVs and generates an LOD chain for a mesh, using the exact
libraries the Bible names -- verified against real generated meshes in this
environment (not merely assumed to work from documentation):

- **Mesh I/O**: ``trimesh``, for ``.obj``/``.gltf``/``.glb`` only. ``.fbx``
  is NOT supported -- trimesh has no built-in FBX loader, and there is no
  reliable pure-Python FBX reader without the proprietary Autodesk SDK or a
  fragile ``assimp`` binding. A project using ``.fbx`` source meshes needs
  to export an OBJ/glTF copy first; this is an honest scope limit, not an
  oversight (see ``SUPPORTED_EXTENSIONS``).
- **UV unwrapping**: ``xatlas.Atlas`` (``add_mesh`` / ``generate``) -- its
  real Python API is class-based with ``chart_count`` and
  ``get_utilization()`` properties, not the ``Create``/``AddMesh``/
  ``Generate`` free-function shape the Bible describes (that's the
  library's C++ API; the Python bindings wrap it differently). xatlas
  guarantees non-overlapping charts by construction, which this module
  relies on rather than re-verifying.
- **LOD simplification**: ``meshoptimizer.simplify``, with
  ``SIMPLIFY_LOCK_BORDER`` to weld/lock mesh borders during simplification
  (avoiding seams reopening at LOD transitions), matching the Bible's
  ``meshopt_SimplifyLockBorder`` call.

**Why the actual simplify+unwrap step runs in a subprocess**
(``_uv_lod_worker.py``): testing against real meshes in this environment
found a reproducible native access violation inside ``xatlas.Atlas.
generate()`` on certain mesh topologies (not predictable from triangle
count alone -- see that module's docstring for the specific repro). A
native crash kills the whole process and can't be caught with ``try``/
``except``; running it out-of-process turns a crash into an ordinary failed
subprocess call this module can catch and report as an error for that one
LOD level, instead of taking down all of Spiced.

Each LOD level is unwrapped independently (not just the highest-resolution
mesh) and exported as its own file -- Unity's ``LODGroup`` component
references separate mesh assets per level, not one multi-LOD file, so this
matches how the output actually gets used rather than inventing a
non-standard combined format.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import trimesh

from spiced.automation.finding import Finding, FindingItem
from spiced.storage.automation_findings import AutomationFindingRecord, AutomationFindingRepository

FEATURE_ID = "art.uv_unwrapping_lod_generation"

SUPPORTED_EXTENSIONS = {".obj", ".gltf", ".glb"}
# 100%, 50%, 25%, 10% triangle count, matching the Bible's stated default.
DEFAULT_LOD_RATIOS: tuple[float, ...] = (1.0, 0.5, 0.25, 0.1)
DEFAULT_TARGET_ERROR = 0.05
DEFAULT_WORKER_TIMEOUT_S = 300


class UnsupportedMeshFormatError(RuntimeError):
    """Raised for a mesh format this module can't load (see SUPPORTED_EXTENSIONS)."""


class UnreadableMeshError(RuntimeError):
    """Raised when the file can't be loaded as a mesh at all."""


@dataclass(frozen=True)
class MeshBuffers:
    vertices: np.ndarray  # (N, 3) float32
    faces: np.ndarray  # (M, 3) uint32


def load_mesh(path: str | Path) -> MeshBuffers:
    ext = Path(path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedMeshFormatError(
            f"{ext} is not supported -- only {', '.join(sorted(SUPPORTED_EXTENSIONS))} are "
            "(no reliable pure-Python .fbx loader; export an OBJ/glTF copy first)."
        )
    try:
        mesh = trimesh.load(str(path), force="mesh", process=False)
    except Exception as exc:
        raise UnreadableMeshError(f'Could not read "{Path(path).name}" as a mesh: {exc}') from exc
    if not hasattr(mesh, "vertices") or not hasattr(mesh, "faces") or len(mesh.faces) == 0:
        raise UnreadableMeshError(f'"{Path(path).name}" has no triangle mesh data.')
    return MeshBuffers(
        vertices=np.asarray(mesh.vertices, dtype=np.float32),
        faces=np.asarray(mesh.faces, dtype=np.uint32),
    )


@dataclass(frozen=True)
class LodMeshResult:
    ratio: float
    triangle_count: int
    vertices: np.ndarray
    faces: np.ndarray
    uvs: np.ndarray
    chart_count: int
    atlas_utilization: float
    simplify_error: float
    output_path: str | None = None


class LodGenerationError(RuntimeError):
    """Raised when the out-of-process simplify+unwrap worker fails or crashes."""


@dataclass(frozen=True)
class LodGenerationOutcome:
    ratio: float
    result: LodMeshResult | None = None
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.result is not None


def _run_lod_worker(
    mesh: MeshBuffers,
    ratio: float,
    *,
    target_error: float,
    lock_border: bool,
    timeout_s: int,
) -> LodMeshResult:
    """Runs one LOD level's simplify+unwrap in a subprocess (see module
    docstring for why) and returns the result, or raises LodGenerationError."""
    with tempfile.TemporaryDirectory(prefix="spiced-uv-lod-") as tmp:
        input_path = Path(tmp) / "input.npz"
        output_path = Path(tmp) / "output.npz"
        np.savez(input_path, vertices=mesh.vertices, faces=mesh.faces)

        command = [
            sys.executable,
            "-m",
            "spiced.automation._uv_lod_worker",
            str(input_path),
            str(output_path),
            str(ratio),
            str(target_error),
            str(int(lock_border)),
        ]
        try:
            completed = subprocess.run(command, timeout=timeout_s, capture_output=True)
        except subprocess.TimeoutExpired as exc:
            raise LodGenerationError(
                f"LOD generation timed out after {timeout_s}s at {ratio * 100:.0f}% triangle count."
            ) from exc

        if completed.returncode != 0 or not output_path.is_file():
            stderr_tail = completed.stderr.decode("utf-8", errors="replace")[-2000:]
            raise LodGenerationError(
                f"LOD generation failed at {ratio * 100:.0f}% triangle count "
                f"(exit code {completed.returncode}). This can happen on certain mesh "
                f"topologies that trip a crash in the xatlas library. {stderr_tail}".strip()
            )

        # np.load on an .npz keeps the file open lazily until closed -- on
        # Windows that blocks the TemporaryDirectory cleanup below unless
        # arrays are pulled out and the handle is closed first.
        with np.load(output_path) as data:
            faces = np.array(data["faces"])
            result = LodMeshResult(
                ratio=ratio,
                triangle_count=len(faces),
                vertices=np.array(data["vertices"]),
                faces=faces,
                uvs=np.array(data["uvs"]),
                chart_count=int(data["chart_count"]),
                atlas_utilization=float(data["atlas_utilization"]),
                simplify_error=float(data["simplify_error"]),
            )
        return result


def generate_uv_lod_chain(
    mesh: MeshBuffers,
    *,
    ratios: tuple[float, ...] = DEFAULT_LOD_RATIOS,
    target_error: float = DEFAULT_TARGET_ERROR,
    lock_border: bool = True,
    timeout_s: int = DEFAULT_WORKER_TIMEOUT_S,
    on_progress: Callable[[str], None] | None = None,
) -> list[LodGenerationOutcome]:
    """Simplify (per ratio, each independently from the full-resolution
    mesh -- not cascaded) and UV-unwrap every LOD level. One LOD level
    failing (including a worker crash) doesn't stop the others."""
    outcomes = []
    for ratio in ratios:
        if on_progress is not None:
            on_progress(f"Generating the {ratio * 100:.0f}% LOD (simplify + unwrap)...")
        try:
            result = _run_lod_worker(
                mesh, ratio, target_error=target_error, lock_border=lock_border, timeout_s=timeout_s
            )
            outcomes.append(LodGenerationOutcome(ratio=ratio, result=result))
        except LodGenerationError as exc:
            outcomes.append(LodGenerationOutcome(ratio=ratio, error=str(exc)))
    return outcomes


def export_lod(lod: LodMeshResult, output_path: str | Path) -> LodMeshResult:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out_mesh = trimesh.Trimesh(vertices=lod.vertices, faces=lod.faces, process=False)
    out_mesh.visual = trimesh.visual.TextureVisuals(uv=lod.uvs)
    out_mesh.export(str(output_path))
    return LodMeshResult(
        ratio=lod.ratio,
        triangle_count=lod.triangle_count,
        vertices=lod.vertices,
        faces=lod.faces,
        uvs=lod.uvs,
        chart_count=lod.chart_count,
        atlas_utilization=lod.atlas_utilization,
        simplify_error=lod.simplify_error,
        output_path=str(output_path),
    )


def _lod_label(index: int, ratio: float) -> str:
    return f"LOD{index}" if ratio < 1.0 else "LOD0"


def _summarize(succeeded: list[tuple[str, int]], *, total: int) -> str:
    if total == 0:
        return "No LOD levels were generated."
    if not succeeded:
        return f"All {total} LOD level(s) failed to generate."
    parts = ", ".join(f"{label}: {tri_count} tri" for label, tri_count in succeeded)
    failed = total - len(succeeded)
    failed_note = f" ({failed} failed)" if failed else ""
    return f"Generated {len(succeeded)} of {total} LOD level(s){failed_note} -- {parts}."


@dataclass(frozen=True)
class UvLodRunResult:
    finding: Finding
    lods: list[LodMeshResult] = field(default_factory=list)


def run_uv_lod_generation(
    mesh_path: str | Path,
    project_id: str,
    *,
    output_dir: str | Path,
    ratios: tuple[float, ...] = DEFAULT_LOD_RATIOS,
    target_error: float = DEFAULT_TARGET_ERROR,
    lock_border: bool = True,
    on_progress: Callable[[str], None] | None = None,
) -> UvLodRunResult:
    stem = Path(mesh_path).stem
    ext = Path(mesh_path).suffix.lower() or ".glb"

    try:
        mesh = load_mesh(mesh_path)
    except (UnsupportedMeshFormatError, UnreadableMeshError) as exc:
        finding = Finding(
            feature_id=FEATURE_ID,
            project_id=str(project_id),
            status="error",
            summary=str(exc),
            items=[FindingItem(asset_path=str(mesh_path), severity="error", message=str(exc))],
        )
        return UvLodRunResult(finding=finding)

    outcomes = generate_uv_lod_chain(
        mesh,
        ratios=ratios,
        target_error=target_error,
        lock_border=lock_border,
        on_progress=on_progress,
    )

    output_dir = Path(output_dir)
    exported: list[LodMeshResult] = []
    summary_parts: list[tuple[str, int]] = []
    items: list[FindingItem] = []
    for i, outcome in enumerate(outcomes):
        label = _lod_label(i, outcome.ratio)
        if not outcome.succeeded:
            items.append(
                FindingItem(
                    asset_path=str(mesh_path),
                    severity="error",
                    message=f"{label}: {outcome.error}",
                )
            )
            continue
        lod = outcome.result
        out_path = output_dir / f"{stem}_{label}{ext}"
        result = export_lod(lod, out_path)
        exported.append(result)
        summary_parts.append((label, result.triangle_count))
        items.append(
            FindingItem(
                asset_path=str(mesh_path),
                severity="info",
                message=(
                    f"{label}: {result.triangle_count} triangle(s), {result.chart_count} UV "
                    f"chart(s), {result.atlas_utilization * 100:.1f}% atlas utilization -> "
                    f"{out_path.name}"
                ),
                detail={
                    "lod_label": label,
                    "ratio": lod.ratio,
                    "triangle_count": result.triangle_count,
                    "chart_count": result.chart_count,
                    "atlas_utilization": round(result.atlas_utilization, 4),
                    "simplify_error": round(result.simplify_error, 5),
                    "output_path": result.output_path,
                },
            )
        )

    finding = Finding(
        feature_id=FEATURE_ID,
        project_id=str(project_id),
        status=Finding.status_for(items),
        summary=_summarize(summary_parts, total=len(outcomes)),
        items=items,
    )
    return UvLodRunResult(finding=finding, lods=exported)


class UvLodGenerationService:
    def __init__(self, findings: AutomationFindingRepository) -> None:
        self._findings = findings

    def generate(
        self,
        project,
        mesh_path: str | Path,
        *,
        output_dir: str | Path,
        ratios: tuple[float, ...] = DEFAULT_LOD_RATIOS,
        on_progress: Callable[[str], None] | None = None,
    ) -> UvLodRunResult:
        result = run_uv_lod_generation(
            mesh_path,
            str(project.id),
            output_dir=output_dir,
            ratios=ratios,
            on_progress=on_progress,
        )
        self._findings.create(project.id, result.finding)
        return result

    def history(self, project_id: int, limit: int = 20) -> list[AutomationFindingRecord]:
        return self._findings.list_for_project(project_id, feature_id=FEATURE_ID, limit=limit)


def _cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiced-uv-lod-generation",
        description="Auto-unwrap UVs and generate an LOD chain for a mesh (.obj/.gltf/.glb only).",
    )
    parser.add_argument("mesh_path", help="Path to the source mesh file.")
    parser.add_argument(
        "--output-dir", required=True, help="Where to write the generated LOD files."
    )
    parser.add_argument(
        "--ratios",
        type=float,
        nargs="+",
        default=list(DEFAULT_LOD_RATIOS),
        help=f"LOD triangle-count ratios (default: {list(DEFAULT_LOD_RATIOS)}).",
    )
    parser.add_argument("--project-id", default="cli", help="Project id to tag the run with.")
    parser.add_argument("--json", action="store_true", help="Print the full Finding as JSON.")
    args = parser.parse_args(argv)

    result = run_uv_lod_generation(
        args.mesh_path, args.project_id, output_dir=args.output_dir, ratios=tuple(args.ratios)
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
