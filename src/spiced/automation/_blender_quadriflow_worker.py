"""Blender-side worker script for Retopology Assist (Implementation Bible,
Feature 10). UNVERIFIED -- no Blender install is available in this
environment, so this script (unlike Feature 8's real, verified xatlas/
meshoptimizer worker) has not actually been run inside Blender's embedded
Python interpreter. It's written against Blender's documented public API
(``bpy.ops.import_scene``/``bpy.ops.object.quadriflow_remesh``/
``bpy.ops.export_scene``, ``bmesh`` for manifold checking) the same way
``connectors._renderdoc_worker`` is written against RenderDoc's documented
Python API -- treat it as a credible first draft, not a confirmed-working
integration, until it's been run against a real Blender install. Every
Python-side test in this codebase mocks the ``blender`` subprocess call
itself rather than assuming this script works (see
``tests/test_retopology_assist.py``).

Not imported anywhere -- ``retopology_assist.py`` writes this file's
*source text* out to a temp ``.py`` file and hands that path to
``blender --background --python <path> -- <args>``, since Blender only
runs Python inside its own embedded interpreter (``bpy`` isn't
pip-installable), the same reason Feature 8's segfault-isolation worker
runs as its own subprocess rather than an in-process import -- except here
the isolation is *inherent* (Blender's Python and Spiced's Python are two
different processes by construction), not something this module has to
set up itself.

Invoked as ``blender --background --python <this file> -- <input_mesh>
<output_mesh> <target_face_count> <result_json_path>``. Prints nothing of
its own on success -- the result is written to ``result_json_path`` as
JSON: ``{"before_face_count", "after_face_count", "quad_count",
"triangle_count", "other_polygon_count", "non_manifold_edge_count",
"output_path"}``.
"""

WORKER_SCRIPT_SOURCE = '''\
"""Runs inside Blender's embedded Python interpreter -- see the generating
module's docstring (spiced.automation._blender_quadriflow_worker) for why
this is UNVERIFIED against a real Blender install."""
import json
import sys

import bmesh
import bpy


def _import_mesh(path):
    lowered = path.lower()
    if lowered.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    elif lowered.endswith(".glb") or lowered.endswith(".gltf"):
        bpy.ops.import_scene.gltf(filepath=path)
    else:
        raise RuntimeError("Unsupported mesh format for Blender import: " + path)


def _export_mesh(path):
    lowered = path.lower()
    if lowered.endswith(".obj"):
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=True)
    elif lowered.endswith(".glb") or lowered.endswith(".gltf"):
        bpy.ops.export_scene.gltf(filepath=path, use_selection=True)
    else:
        raise RuntimeError("Unsupported mesh format for Blender export: " + path)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:]
    input_path, output_path, target_faces_s, result_path = argv[:4]
    target_face_count = int(target_faces_s)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    _import_mesh(input_path)

    mesh_objects = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError("No mesh object found after import.")
    obj = mesh_objects[0]
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)

    before_face_count = len(obj.data.polygons)

    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.quadriflow_remesh(target_faces=target_face_count, use_mesh_symmetry=False)

    mesh = obj.data
    after_face_count = len(mesh.polygons)
    quad_count = sum(1 for p in mesh.polygons if len(p.vertices) == 4)
    triangle_count = sum(1 for p in mesh.polygons if len(p.vertices) == 3)
    other_polygon_count = after_face_count - quad_count - triangle_count

    bm = bmesh.new()
    bm.from_mesh(mesh)
    non_manifold_edge_count = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()

    _export_mesh(output_path)

    result = {
        "before_face_count": before_face_count,
        "after_face_count": after_face_count,
        "quad_count": quad_count,
        "triangle_count": triangle_count,
        "other_polygon_count": other_polygon_count,
        "non_manifold_edge_count": non_manifold_edge_count,
        "output_path": output_path,
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f)


main()
'''
