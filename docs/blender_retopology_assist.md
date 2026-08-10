# Retopology Assist -- the `Blender` system dependency

Retopology Assist (`spiced.automation.retopology_assist`) uses Blender's
QuadriFlow remesher (`bpy.ops.object.quadriflow_remesh`), driven headlessly
via `blender --background --python <worker script>`. Blender itself is a
large external dependency -- the same category `ffmpeg` is for Feature 1
(see `docs/loudness_normalize_ffmpeg.md`) -- and is **not** something `pip`
can install. Blender (4.0+, for a current QuadriFlow remesher) must already
be on the host machine, either on `PATH` as `blender`, or pointed to
explicitly via the `--blender-path` CLI flag / `blender_path` argument.

If Blender isn't found, `run_retopology_assist()` raises/reports a
`BlenderNotAvailableError` before any file is touched -- never partway
through a run.

## Installing Blender

- **Windows:** `winget install BlenderFoundation.Blender` (or download from
  https://www.blender.org/download/ and add its install folder to `PATH`).
- **macOS:** `brew install --cask blender`
- **Linux:** your distro's package manager, or the official download above.

Spiced itself never installs Blender on the user's behalf, the same as every
other system-dependency integration in this codebase (ffmpeg, Unity, RenderDoc).

## Verification status

The Blender-side worker script
(`spiced.automation._blender_quadriflow_worker.WORKER_SCRIPT_SOURCE`) has
**not** been run against a real Blender install in the environment this
feature was built in -- no Blender install was available there. It follows
Blender's documented public API (`bpy.ops.import_scene`/
`bpy.ops.object.quadriflow_remesh`/`bpy.ops.export_scene`, `bmesh` for
manifold checking), the same way `connectors.renderdoc_analysis` (Feature 9)
follows RenderDoc's documented Python API without a verified real install --
see that module's docstring for the same category of caveat. Every automated
test in this codebase mocks the `blender` subprocess call itself rather than
assuming the worker script works; treat it as a credible first draft until
it's been run against a real Blender install on a real mesh.
