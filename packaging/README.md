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

`packaging/spiced.spec` was actually run (`pyinstaller packaging/spiced.spec`)
against a real environment -- Analysis/PYZ/EXE/COLLECT all complete, the
font `datas=` entry lands correctly, and the ffmpeg-bundling conditional
was exercised (both present and absent). The resulting exe's own runtime
behavior is where a real, unresolved issue turned up -- see the next
section.

`packaging/inno_setup.iss` was **not** compiled or run -- no Inno Setup /
`iscc` install was available in the environment this spec was authored in.
The script (including the `[Code]` section's `WM_SETTINGCHANGE` broadcast,
Inno Setup's own documented pattern for making a just-written registry env
var visible to new processes immediately) is written to Inno Setup 6's
documented syntax, but compile it once (`iscc packaging\inno_setup.iss`)
and sanity-check the install/uninstall/registry-write flow on a real
Windows machine before relying on it for a release.

## Known issue: Qt6Core.dll crash on a from-scratch build (unresolved)

Building `packaging/spiced.spec` against **PySide6 6.11.1 / PyInstaller
6.22.2 / Python 3.14** produced a `dist/Spiced/Spiced.exe` that completed
`Analysis`/`PYZ`/`EXE`/`COLLECT` without error, correctly bundled the font
`datas=` entry, and correctly included `opengl32sw.dll` (the one binary
this combination is known to sometimes drop) -- but the built exe itself
crashed on launch (`--smoke-test` included) with a Windows fault inside
`Qt6Core.dll`, exception code `0xc0000409`, both with and without
`QT_QPA_PLATFORM=offscreen` set, and both with `console=True` and
`console=False`. The exact same PySide6 install runs Spiced fine
un-frozen (`python -m spiced.app.main --smoke-test` succeeds), so this is
specific to the frozen build, not a Spiced code bug or a headless/display
limitation.

Not yet root-caused -- diagnosing further needs a debugger attached to the
frozen exe (WinDbg or similar) or trying an older, more established
PySide6/Python pairing, neither of which was available in the environment
this spec was authored in. Likely candidates, in rough order of
probability: a Qt platform-plugin compatibility gap between this
particular (very recent) PySide6 6.11.1 release and
`pyinstaller-hooks-contrib`'s PySide6 hook; a Python 3.14 / PyInstaller
bootloader compatibility gap (3.14 is new enough that native-extension
tooling may not have fully caught up). **Before relying on this spec for a
real release, build it and run `--smoke-test` against the actual exe once
(see above) to confirm this either doesn't reproduce on your toolchain
versions or has been fixed** -- `.github/workflows/release.yml`'s own
smoke-test step exists specifically to catch this class of thing
automatically, but hasn't itself been exercised on a real `windows-latest`
runner yet either. Pinning an older, more widely-used PySide6 (e.g. 6.7.x)
is the first thing worth trying if it reproduces there too.

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
