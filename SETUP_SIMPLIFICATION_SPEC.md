# Spiced Desktop — Connect-a-Project Setup Simplification Spec

Scope: the one flow that sits under the flagship "test, debug, and get feedback
across Unity, Godot, and Unreal" story — connecting a project's folder and
(where needed) its engine executable. Root-caused against the actual
codebase (`spiced-ai`). Hand this to Claude Code as-is — it has file/line
references throughout.

**In scope as of this revision:** packaging Spiced as a real Windows
installer (Finding 3 below), folded in at Lauren's request rather than left
as a someday-initiative.

**Still out of scope, deliberately:** the exact-Unity-Editor-version
enforcement in `core.unity_test_runner` (a deliberate safety choice,
documented in `README.md`'s "Enabling Run Unity Tests" section — not
friction to remove).

---

## Finding 1 — the app asks which engine before it's seen the folder

### Root cause

`ui/screens/projects.py`'s "New project" card asks for a name and an engine
*before* a folder is ever chosen: a `ScrollSafeComboBox` seeded with
`["Unity", "Godot", "Unreal", "Other"]` (`projects.py:119-121`), read in
`_create()` (`projects.py:1137-1148`) and stored on the `Project` row via
`ProjectsService.create_project` (`core/projects_service.py:17-24`).

Only afterward does `_choose_folder()` (`projects.py:1173-1200`) open a
folder picker and call `ProjectsService.attach_engine_folder`
(`core/projects_service.py:32-65`), which dispatches purely on the
already-stored `project.engine` string:

```python
if project.engine == "Godot":
    detection = detect_godot_project(folder)
elif project.engine == "Unreal":
    detection = detect_unreal_project(folder)
else:
    detection = detect_unity_project(folder)
```

If the folder doesn't match the engine picked three steps earlier — a new
user browsing to their actual project without re-reading the combo box they
filled in first, or simply not realizing "Other" defaults to Unity-shaped
validation — the result is `detection.is_valid == False` and a warning
dialog ("That doesn't look like a Unity project... missing 'Assets/'...")
that reads like something is wrong with the *project*, when the real
mistake was a stale dropdown value from a step ago.

This is backwards for the app's own flagship claim (works the same across
three engines): the user has to already know and correctly state which
engine they're using before Spiced will even try to recognize their
project, when `connectors.unity.detect_unity_project`,
`connectors.godot.detect_godot_project`, and
`connectors.unreal.detect_unreal_project` are all cheap, pure,
side-effect-free functions that could just be run against the folder
directly and asked which one of them recognizes it.

### Fix spec

1. **Add an auto-detect dispatcher.** New function in `core/engine_dispatch.py`
   (the existing home for the `ENGINE_UNITY`/`ENGINE_GODOT`/`ENGINE_UNREAL`
   constants):

   ```python
   def detect_engine(folder: str | Path) -> tuple[str, DetectionResult]:
       """Run all three folder detectors against `folder` and return the
       engine whose marker file matched, plus its detection result.
       Godot (`project.godot`) and Unreal (`*.uproject`) each have one
       unambiguous marker file, so at most one should ever match; if
       none match, fall back to Unity's detector (matching
       ProjectsService.attach_engine_folder's existing "Other" ->
       Unity-shaped behavior) so an unrecognized folder still gets a
       consistent, actionable warning instead of three different ones.
       """
   ```

   Check Godot and Unreal first (single unambiguous marker file each —
   `project.godot` at root, exactly one `*.uproject` at root), Unity last
   (its `Assets/` + `ProjectSettings/` pair check is also the fallback
   shape, so it can't "win" a real Godot/Unreal folder by accident, but
   checking it last keeps the precedence explicit rather than relying on
   that being incidentally true).

2. **Reorder the UI flow: folder first, engine confirmed after.**
   In `projects.py`, change `_create()` (or add a new entry point) so
   creating a project asks for a name and a folder
   (`QFileDialog.getExistingDirectory`, reusing the dialog already in
   `_choose_folder`), runs `detect_engine()` against it immediately, and
   pre-selects `self._engine_input`'s combo box to the detected engine
   before the user ever has to touch it. Show what was found: *"Looks like
   a Godot project (Fixture Game) — connect it as Godot?"* with the combo
   box still visible and editable underneath for the override case
   (a monorepo with multiple engines, or a folder that doesn't match any
   detector). This keeps the manual dropdown as an escape hatch — never
   silently overridden — it just stops being the thing the user has to get
   right first.

3. **Make the mismatch warning actionable, not just descriptive**, for
   whatever's left of the manual-override path: if `attach_engine_folder`
   comes back invalid, and `detect_engine()` on that same folder *does*
   recognize a different engine, say so directly — *"This doesn't look like
   a Unity project, but it does look like a Godot one — switch this
   project to Godot?"* — instead of only listing what's missing
   (`projects.py:1191-1200`'s current warning path).

4. **Regression tests.** `tests/test_projects.py` and a new
   `tests/test_engine_dispatch.py` (there's no dedicated test module for
   `core/engine_dispatch.py` yet — it's currently only exercised
   indirectly): fixture folders for all three engines (the same shapes
   `tests/e2e/conftest.py` already builds — `make_godot_fixture_project`,
   `make_unreal_fixture_project`, and an equivalent minimal Unity folder)
   run through `detect_engine()`, asserting the right engine wins and that
   an empty/unrecognized folder falls back to the existing Unity-shaped
   "invalid" result rather than raising.

---

## Finding 2 — Godot and Unreal executables have no auto-discovery at all

### Root cause

`core/engine_executable_resolve.py`'s own module docstring states this
outright: *"there is no Hub-equivalent for either Godot or Unreal — no local
registry of installed versions to query. Both engines require a manual,
explicit path."* `resolve_godot_executable` and `resolve_unreal_uat` /
`resolve_unreal_editor_cmd` (`engine_executable_resolve.py:24-52`) only
validate a path the user already typed or browsed to
(`projects.py:263-286`'s `_on_browse_unity_editor`, which for Unreal opens a
folder picker captioned "Choose the Unreal Engine install folder" and for
Godot a file picker captioned "Choose the Godot executable" — both starting
from nothing, no pre-fill).

This is real, asymmetric friction against Unity, which *does* auto-discover
installed Editor versions via Unity Hub's CLI
(`core/unity_test_runner.resolve_unity_editor`, referenced from
`README.md`'s "Enabling Run Unity Tests" section) — undercutting the
"works the same across three engines" story right at the point where a new
user is deciding whether Godot/Unreal support feels as first-class as
Unity's.

It's not fully fixable — Godot in particular is often a portable executable
with no installer and no OS-level registry of where it lives — but there's
real, unclaimed ground for both engines before falling back to "ask the
user":

- **Unreal has a real, discoverable manifest.** The Epic Games Launcher
  writes every installed engine version's root path to
  `%ProgramData%\Epic\UnrealEngineLauncher\LauncherInstalled.dat`, a small
  JSON file (`{"InstallationList": [{"InstallLocation": "...",
  "AppName": "UE_5.3", ...}, ...]}`). This repo's Unreal support is
  Windows-first already (`engine_executable_resolve.py:36`'s docstring
  says as much for the `.bat`-only UAT path), so this file existing or not
  is a fair, in-scope check.
- **Godot is at least sometimes on `PATH`.** Anyone who installed it via a
  package manager (Scoop, Chocolatey, winget) or added it manually has
  `godot`/`godot.exe` resolvable with stdlib `shutil.which` — free,
  no new dependency, same "stdlib only" philosophy the codebase already
  applies to the Discord integration (`README.md`'s Discord section: *"Uses
  only Python's standard library... no extra dependency to install"*).

### Fix spec

1. **`resolve_unreal_uat`/`resolve_unreal_editor_cmd`: try the launcher
   manifest before falling back to the manual override.** Add a
   `find_installed_unreal_engines() -> dict[str, str]` (version string →
   install root) in `engine_executable_resolve.py` that reads
   `LauncherInstalled.dat` if present, returns `{}` on any parse/IO error
   (never raises — matches every other detector in this codebase's
   "best-effort, never raises" convention, e.g.
   `connectors.unity._read_unity_version`). In `projects.py`'s Unreal
   branch (`_on_browse_unity_editor`, `_update_...` around
   `projects.py:263-322`), if no override is set yet, look up the
   project's already-parsed `engine_association` (from
   `UnrealDetectionResult.engine_association`, e.g. `"5.3"`) against this
   dict and pre-fill the folder picker's starting directory — or, better,
   surface it directly: *"Found Unreal Engine 5.3 installed at
   `C:\Program Files\Epic Games\UE_5.3` — use this?"* with one click to
   accept, and the existing manual browse button still available if the
   user says no or nothing matched.
2. **`resolve_godot_executable`: try `shutil.which` first.** Same
   pre-fill-and-confirm treatment — check `shutil.which("godot")` and
   `shutil.which("godot.exe")` before opening the file picker with nothing
   in it; if found, offer it as a one-click default rather than requiring
   a browse.
3. **Never auto-apply either without confirmation.** Both stay pre-fill
   suggestions the user accepts or overrides, not silent auto-configuration
   — consistent with the "opt-in, never silent" rule stated repeatedly in
   `README.md`'s Ethical Purpose section for everything else that touches
   an external engine/process.
4. **Regression tests.** `tests/test_engine_executable_resolve.py`
   (doesn't exist yet as a dedicated module — current coverage is
   indirect via the UI test modules) covering: a fake
   `LauncherInstalled.dat` with 1-2 installs parses correctly and a
   missing/malformed one degrades to `{}` without raising; `shutil.which`
   found vs. not-found, mocked rather than depending on the CI runner's
   actual `PATH`.

---

## Finding 3 — there is no installer; "setup" means cloning a repo

### Root cause

`README.md`'s "Setup" section is a developer workflow, not an end-user
one: create a Python virtualenv, `pip install -e ".[dev]"`, then edit a
`.env` file (or set a shell environment variable) to configure an AI
provider key. Spiced's own target user — an indie dev, not necessarily a
Python developer — has no path to "just run the app" today. This is the
single largest remaining barrier to "minimal setup," and it sits upstream
of Findings 1 and 2: neither matters if the user never gets the app
running at all.

Four concrete things stand in the way of a naive PyInstaller build,
found by reading `pyproject.toml` and the docs already written for each
dependency:

- **No packaging entry point exists.** `[project.gui-scripts] spiced =
  "spiced.app.main:main"` (`pyproject.toml:100-101`) is meant for a `pip`
  environment's generated launcher script, not a standalone `.exe` — there
  is no PyInstaller/Nuitka spec file anywhere in the repo.
- **A heavy, partly-native dependency footprint** (`pyproject.toml:15-71`):
  `PySide6`, `numpy`, `trimesh`/`xatlas`/`meshoptimizer` (Feature 8's mesh
  tooling), and `faster-whisper` (which pulls in `ctranslate2`) will bloat
  and complicate a default PyInstaller analysis if not scoped deliberately.
- **`ffmpeg-normalize` needs a real `ffmpeg` binary `pip` cannot install.**
  Per `docs/loudness_normalize_ffmpeg.md`: not found on `PATH` raises a
  clean `FfmpegNotAvailableError` up front (good — never fails partway
  through a batch), and accepts an explicit override via the `FFMPEG_PATH`
  environment variable (very good — that's a bundling hook already built
  in, not something to add).
- **`faster-whisper` downloads a model on first use.** Per
  `docs/faster_whisper_model_caching.md`: the default `tiny.en` model is
  fetched from Hugging Face Hub the first time any feature touches
  transcription, cached under the OS's standard Hugging Face cache
  directory, then fully offline after that. Needs a network connection at
  an unpredictable first moment if not addressed.
- **There is no in-app way to enter an API key at all.** `settings.py`'s
  provider section (`settings.py:377`, `settings.py:1159`) only ever reads
  `OPENAI_API_KEY`/`GEMINI_API_KEY` from the process environment — there
  is no `QLineEdit` anywhere that lets a user type a key and have Spiced
  remember it. That's a non-issue for a source checkout with a `.env`
  file, but it's a dead end for someone running a packaged `.exe` with no
  shell, no repo, and no idea what an environment variable is. The mock
  provider needing zero setup doesn't help someone who specifically wants
  real AI-assisted review.

### Fix spec

1. **Add an in-app API key field before anything else here.** This
   unblocks non-technical users even before an installer exists, so it's
   the one fix in this finding worth doing first regardless of packaging
   timeline. Add a password-`EchoMode` `QLineEdit` to `settings.py`'s
   provider section (next to the existing "Send test prompt" button,
   `settings.py:377`) that writes to a small local key-store Spiced
   manages itself — a plain file under the OS's per-user app-data
   directory (same trust tier as the existing local SQLite DB; reuse the
   README's existing secrets language: "never sent anywhere but the
   provider itself"), read as a fallback wherever `OPENAI_API_KEY`/
   `GEMINI_API_KEY` are currently read from the environment
   (`settings.py:1159`). A shell-set environment variable should still
   take precedence for anyone who prefers that, so nothing breaks for the
   existing developer workflow.
2. **Build a Windows installer.** A PyInstaller `--onedir` build (not
   `--onefile` — startup time and the ability to diagnose a missing
   bundled file both matter more here than a single-file download) of the
   `spiced` gui-script entry point, wrapped in an Inno Setup script that
   produces one `Spiced-Setup.exe`. Windows-first matches every other
   engine-specific decision already made in this codebase (Unreal's
   `.bat`-only UAT path, the Windows-flavored error text in
   `BUGFIX_SPEC.md`) — a macOS/Linux build is a real follow-up, not
   attempted in the same pass.
3. **Explicit `datas=` entries for anything PyInstaller's static analysis
   won't find on its own.** The bundled Baloo 2/Nunito font files
   (`ui/assets/fonts/*.ttf`, declared as setuptools `package-data` at
   `pyproject.toml:113-114`) are the one already-known case — setuptools
   package-data isn't something PyInstaller's import-graph analysis
   discovers automatically, it has to be listed explicitly in the
   `.spec` file. Audit for other bundled non-`.py` assets (demo project
   data, any other packaged resource) while doing this.
4. **Bundle a static `ffmpeg` build and point `FFMPEG_PATH` at it.** Since
   `ffmpeg-normalize` already honors that environment variable
   (`docs/loudness_normalize_ffmpeg.md`), the installer can set it once at
   install time to a copy of `ffmpeg.exe` placed alongside the app —
   loudness normalization then works out of the box instead of sending
   the user to `winget install ffmpeg` first. (A static Windows build is
   freely redistributable under ffmpeg's LGPL "essentials" builds; confirm
   the specific build's license terms before shipping it.)
5. **Leave `faster-whisper`'s model lazy, but say so out loud.** Don't
   spend installer size/build-time bundling the model — keep the existing
   first-use download behavior — but surface it as a one-time, plain-
   language in-app notice ("Downloading a small speech-recognition model
   the first time you use this — after that it works fully offline")
   instead of a silent multi-second stall the first time someone touches
   Localization Audio Sync or Content Verification.
6. **Don't bundle `git`.** The Git connector already assumes a working
   `git` CLI on `PATH` (`pyproject.toml`'s own `GitPython` comment,
   lines 61-71), and the audience for a version-control feature has
   overwhelmingly already got git installed. Add a friendly, specific
   "git isn't on PATH — install it from git-scm.com" message the first
   time the connector can't find it, rather than a raw
   `subprocess`/`FileNotFoundError` traceback reaching the UI (the same
   class of fix `BUGFIX_SPEC.md`'s Bug 1 already applied to
   `WinError 10061`).
7. **Budget for code signing as a real decision, not an afterthought.** An
   unsigned `.exe` trips Windows SmartScreen's "unrecognized publisher"
   warning — which reads as a virus alert to exactly the non-technical
   indie devs this installer exists to reach, and will generate support
   messages asking if Spiced is safe. A code-signing certificate (roughly
   $100–400/year from a standard CA) is the fix; flag it here so it's a
   deliberate yes/no rather than something discovered after the first
   confused user.
8. **Wire the build into CI, not a local manual step.** A new
   `.github/workflows/release.yml` (or an additional job alongside the
   existing `e2e-tests.yml`) that builds the installer on a version tag —
   the same "CI does it, not a laptop" discipline the E2E suite already
   established for testing. The workflow should also run the built
   `.exe` once headlessly (e.g. a `--version`-style smoke invocation) on
   a clean Windows runner before publishing the release artifact, to
   catch a missing-DLL/missing-font/missing-`FFMPEG_PATH` bundling gap
   before a user does.
9. **Auto-update is explicitly deferred**, not silently dropped: a
   natural v2 is a lightweight "check GitHub releases" ping surfaced on
   the **Roadmap** screen, which already has a real changelog feed
   (`core/roadmap_service.py`) to hook a "new version available" line
   into. Not attempted in this pass — bundling and first-run experience
   are the higher-value fix, and auto-update adds its own real scope
   (download integrity, in-place replace of a running `.exe`).

### Regression / verification

- The CI smoke-run in fix 8 is the main automated check here — it can't
  validate everything a human would notice about a first run, but it can
  catch the class of bug that only shows up in a bundled build and never
  in a source checkout (a file PyInstaller silently didn't include, an
  environment variable no longer set, a relative path that assumed the
  source tree's layout).
- `tests/test_settings_screen.py` gets a case for the new key-store: a
  key entered through the field is read back correctly, an environment
  variable still wins if both are set, and an empty/missing key-store
  file degrades to "no key configured" rather than raising — matching
  every other "best-effort, never raises" detector already in this
  codebase.

---

## Suggested order of work

1. Finding 1, fix 1 (the `detect_engine()` dispatcher) — small, pure,
   immediately unlocks fix 2.
2. Finding 1, fix 2 (reorder the UI flow) — the actual friction removal;
   depends on fix 1.
3. Finding 1, fix 3 (actionable mismatch warning) — cheap follow-on once
   `detect_engine()` exists, covers whoever still hits the manual path.
4. Finding 2, fixes 1-2 (Unreal launcher manifest, Godot `PATH` check) —
   independent of Finding 1, can happen in parallel or after.
5. Finding 3, fix 1 (in-app API key field) — do this regardless of
   installer timeline; it unblocks non-technical users on its own and
   every later fix in Finding 3 benefits from it existing first.
6. Finding 3, fixes 2-4 (PyInstaller + Inno Setup build, font/asset
   `datas=` audit, bundled `ffmpeg`) — the actual installer, in that
   order since each depends on the last producing a working build to
   extend.
7. Finding 3, fixes 5-6 (faster-whisper first-use notice, friendly
   missing-git message) — small, independent, can slot in anywhere above.
8. Finding 3, fix 8 (CI release workflow + smoke run) — once fix 6
   produces a real installer to build in CI.
9. Finding 3, fixes 7 and 9 (code signing, auto-update) — deliberate
   go/no-go decisions for Lauren, not blocking the first installer build.
10. Regression tests alongside each fix, not batched at the end — same
    discipline `E2E_TEST_PLAN.md` and `CLAUDE.md` already establish for
    this codebase.

## Explicitly not attempting here

- Auto-discovering Godot when it's *not* on `PATH` — there's no reliable
  signal (no installer, no registry) without depending on a specific
  package manager being the one the user happens to use. Manual browse
  stays the fallback, just no longer the only path.
- Changing Unity's exact-Editor-version match requirement — that's a
  deliberate correctness choice (avoiding an unwanted project
  upgrade/reimport from a mismatched Editor), not setup friction.
- A macOS/Linux installer — everything Unreal-specific in this codebase
  is already Windows-first by prior decision; a cross-platform build is a
  real, separate follow-up once the Windows installer is proven out.
- Auto-update (Finding 3, fix 9) — deferred on purpose, not forgotten;
  see that fix's note on why.
