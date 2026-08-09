"""Out-of-process worker for one LOD level's simplify+unwrap step
(Implementation Bible, Feature 8).

Why this is a separate process rather than an in-process function call:
testing this module against real meshes in this environment surfaced a
reproducible native access violation (segfault) inside ``xatlas.Atlas.
generate()`` on certain mesh topologies -- not predictable from triangle
count alone (an 82k-triangle icosphere crashed; a 128k-triangle UV sphere
did not). A native crash kills the whole process and can't be caught by
Python's ``try``/``except`` -- if this ran in Spiced's own process, that
mesh would take down the entire desktop app, not just this one feature.
Running it as a subprocess means a crash there is just a failed subprocess
call the parent (``uv_lod_generation.generate_uv_lod_chain``) can catch and
report as an error for that one LOD level, the same "one bad item doesn't
kill the whole run" principle ``BatchRunner`` (Feature 0) already applies.

Invoked as ``python -m spiced.automation._uv_lod_worker <input.npz>
<output.npz> <ratio> <target_error> <lock_border 0|1>``. Not a public API --
only ``uv_lod_generation`` calls this.
"""

from __future__ import annotations

import sys

import meshoptimizer
import numpy as np
import xatlas


def _simplify_faces(
    vertices: np.ndarray, faces: np.ndarray, ratio: float, *, target_error: float, lock_border: bool
) -> tuple[np.ndarray, float]:
    if ratio >= 1.0:
        return faces.copy(), 0.0
    indices = faces.reshape(-1).astype(np.uint32)
    target_index_count = max(3, int(len(indices) * ratio))
    target_index_count -= target_index_count % 3
    destination = np.zeros(len(indices), dtype=np.uint32)
    result_error = np.zeros(1, dtype=np.float32)
    options = meshoptimizer.SIMPLIFY_LOCK_BORDER if lock_border else 0
    n = meshoptimizer.simplify(
        destination,
        indices,
        vertices,
        target_index_count=target_index_count,
        target_error=target_error,
        options=options,
        result_error=result_error,
    )
    return destination[:n].reshape(-1, 3), float(result_error[0])


def _unwrap(
    vertices: np.ndarray, faces: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int, float]:
    atlas = xatlas.Atlas()
    atlas.add_mesh(vertices, faces)
    atlas.generate()
    vmapping, indices, uvs = atlas.get_mesh(0)
    return (
        vertices[vmapping],
        indices.reshape(-1, 3),
        uvs,
        atlas.get_mesh_chart_count(0),
        atlas.get_utilization(0),
    )


def main() -> None:
    input_path, output_path, ratio_s, target_error_s, lock_border_s = sys.argv[1:6]
    ratio = float(ratio_s)
    target_error = float(target_error_s)
    lock_border = bool(int(lock_border_s))

    data = np.load(input_path)
    vertices = data["vertices"].astype(np.float32)
    faces = data["faces"].astype(np.uint32)

    simplified_faces, simplify_error = _simplify_faces(
        vertices, faces, ratio, target_error=target_error, lock_border=lock_border
    )
    new_vertices, new_faces, uvs, chart_count, utilization = _unwrap(vertices, simplified_faces)

    np.savez(
        output_path,
        vertices=new_vertices,
        faces=new_faces,
        uvs=uvs,
        chart_count=np.array(chart_count),
        atlas_utilization=np.array(utilization),
        simplify_error=np.array(simplify_error),
    )


if __name__ == "__main__":
    main()
