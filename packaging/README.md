# Building the Windows installer

Connect-a-Project Setup Simplification spec, Finding 3: today's `README.md`
"Setup" section is a developer workflow (venv, `pip install -e ".[dev]"`,
edit a `.env`) -- Spiced's own target user (an indie dev, not necessarily a
Python developer) has no path to "just run the app." This directory builds
`Spiced-Setup.exe`, a real Windows installer, so they don't need one.

This is a maintainer/CI concern, not something a Spiced user or a Spiced
contributor working on app features needs to touch -- the `dev` extra
(`pip install -e ".[dev]"`) doesn't pull in any of this.

## Build steps

From the repo root, with a Python environment that has the `build` extra
installed:

```bash
pip install -e ".[build]"
# Add ",gemini" too if this build should support the Gemini provider --
# see pyproject.toml's optional-dependencies.

pyinstaller packaging/spiced.spec
# Produces dist/Spiced/ (a --onedir build -- see spiced.spec's own
# docstring for why not --onefile).
```

Then, with [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed and
its `iscc` compiler on PATH:

```bash
iscc packaging/inno_setup.iss
# Produces packaging/output/Spiced-Setup.exe
```

### Optional: bundle ffmpeg (Finding 3 fix 4)

Place a static `ffmpeg.exe` at `packaging/vendor/ffmpeg/ffmpeg.exe` *before*
running `pyinstaller` above -- see `packaging/vendor/README.md` for where to
get one and its license terms. `spiced.spec` folds it into the build
automatically if present, and `inno_setup.iss` points `FFMPEG_PATH` at it
at install time. Skipped quietly if absent; loudness normalization then
behaves exactly like a source checkout (needs `ffmpeg` on the user's own
PATH -- see `docs/loudness_normalize_ffmpeg.md`).

### Optional: bundle a default AI provider key (Pre-Alpha Testing spec)

So a pre-alpha tester gets working AI features with no account/key of
their own, place the raw key at `packaging/vendor/bundled_openai_key.txt`
(and/or `bundled_gemini_key.txt`) *before* running `pyinstaller` above.
**Read `packaging/vendor/README.md`'s "Bundled default AI provider key"
section first** -- this is not secret storage, and it requires setting a
hard spending cap on that key at the provider before bundling it anywhere.
Skipped quietly if absent, same as ffmpeg.

### Smoke-testing the build (Finding 3 fix 8)

`spiced.app.main.main()` takes a `--smoke-test` flag: constructs the real
app (`Services`, `MainWindow`, every screen) and exits without ever calling
`.show()`/`.exec()`. Run it against the *built* exe, not the source
checkout, to catch a PyInstaller bundling gap (a missing DLL, a missing
font, an unset `FFMPEG_PATH`) before a real user does:

```bash
dist\Spiced\Spiced.exe --smoke-test
```

Exits 0 and prints `Spiced smoke test OK` on success. `.github/workflows/
release.yml` runs this automatically on every tagged build.

## What's been verified vs. not, as of this revision

The full pipeline -- `pyinstaller packaging/spiced.spec`, the built exe's
own `--smoke-test`, and `iscc packaging\inno_setup.iss` -- has now run
**end to end, successfully, on a real `windows-latest` GitHub Actions
runner** (`.github/workflows/release.yml`, triggered via
`workflow_dispatch`, Python 3.12.10 / PySide6 6.11.2 / PyInstaller
6.22.3 / Inno Setup 6.7.1), producing a real, working `Spiced-Setup.exe`
as a workflow artifact. Both real bugs that blocked this before are fixed
-- see the two subsections below. Install/uninstall/registry-write
behavior (the `[Code]` section's `WM_SETTINGCHANGE` broadcast) still
hasn't been manually exercised by actually running the installer and
clicking through it on a machine -- the CI pipeline confirms it *compiles
and produces an exe*, not that every installer-time code path behaves
exactly as intended.

### Fixed: the packaged build's silent crash was sys.stdout/stderr being None

The exe used to fail `--smoke-test` with zero output and no Windows
Application-log crash record at all -- genuinely unexplained at the time.
Root-caused by building a diagnostic console-subsystem variant (which ran
clean) and comparing: a frozen, **windowed** (`console=False`, the shape
this spec actually ships) build has `sys.stdout`/`sys.stderr` as `None`,
since there's no console for them to be connected to. This module's own
`print("Spiced smoke test OK")` on the success path -- along with
anything else that touches those streams -- raised an uncaught
`AttributeError` that killed the process before it could report
anything. Fixed at the source in `spiced.app.main._ensure_std_streams()`:
redirects either stream to a real per-user log file
(`~/.spiced/spiced_stdio.log`) when it's `None`, rather than leaving
Spiced unable to report a startup failure a real (non-technical) user
hits. See that function's own docstring, and `tests/test_app_main_std_streams.py`.

If you're chasing a *different*-looking crash locally (in particular, an
actual Windows Application-log record naming `Qt6Core.dll` with exception
code `0xc0000409`) that persists after this fix, that's a separate issue
from the one above -- it did not reproduce on CI's clean
`windows-latest`/Python 3.12 environment even before this fix, so it may
be specific to a particular local toolchain/Python version pairing rather
than something wrong with this spec.

### Fixed: inno_setup.iss had never actually been compiled

First real `iscc packaging\inno_setup.iss` run caught a genuine bug: the
`[Code]` section's own `HWND_BROADCAST` constant declaration collided
with Inno Setup 6's built-in identifier of the same name ("Duplicate
identifier 'HWND_BROADCAST'", compile aborted). Removed the redundant
declaration -- `WM_SETTINGCHANGE`/`SMTO_ABORTIFHUNG` weren't flagged, so
those are still declared locally as before.

## Code signing (Finding 3 fix 7 -- open decision, not yet made)

`Spiced-Setup.exe` is **unsigned** as of this writing. An unsigned `.exe`
trips Windows SmartScreen's "unrecognized publisher" warning on first run
-- which reads as a virus alert to exactly the non-technical indie devs
this installer exists to reach, and will generate support messages asking
if Spiced is safe. A code-signing certificate (roughly $100-400/year from a
standard CA) fixes this. This is flagged here deliberately, as a real
yes/no decision for Lauren to make with eyes open -- not something to
silently skip or silently decide alone. No code changes are needed either
way; signing is a build-step addition (`signtool sign ...` against the
compiled `Spiced-Setup.exe`) once a certificate exists.

## Auto-update (Finding 3 fix 9 -- explicitly deferred)

Not attempted in this pass. A natural v2 is a lightweight "check GitHub
releases" ping surfaced on the Roadmap screen, which already has a real
changelog feed (`core.roadmap_service`) to hook a "new version available"
line into. Bundling and first-run experience were the higher-value fix for
this pass; auto-update adds its own real scope (download integrity,
in-place replace of a running `.exe`).
