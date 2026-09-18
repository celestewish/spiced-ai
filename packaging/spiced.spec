# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Spiced (Connect-a-Project Setup Simplification spec,
Finding 3 fixes 2-3).

``--onedir``, not ``--onefile``: startup time and the ability to diagnose a
missing bundled file both matter more here than a single-file download (a
onedir build unpacks nothing at launch and a missing DLL shows up as a
folder listing, not an opaque unpack failure).

Run from the repo root:
    pyinstaller packaging/spiced.spec

Output lands in dist/Spiced/ (the whole folder is what Inno Setup
(packaging/inno_setup.iss) wraps into Spiced-Setup.exe). See
packaging/README.md for the full build.
"""

from pathlib import Path

REPO_ROOT = Path(SPECPATH).resolve().parent  # SPECPATH is packaging/ itself
SRC = REPO_ROOT / "src"

# Bundled Baloo 2 / Nunito font files (pyproject.toml's
# [tool.setuptools.package-data]) -- setuptools package-data isn't
# something PyInstaller's import-graph analysis discovers on its own, so it
# has to be listed explicitly here. These are the only non-.py package
# assets in src/spiced as of this spec (audited alongside this fix -- see
# Finding 3 fix 3).
datas = [
    (str(SRC / "spiced" / "ui" / "assets" / "fonts" / "*.ttf"), "spiced/ui/assets/fonts"),
]

# A static ffmpeg.exe placed here by a maintainer before a release build
# (Finding 3 fix 4 -- see packaging/vendor/README.md for how to obtain one
# and its license terms). Skipped quietly if absent so a plain local
# `pyinstaller packaging/spiced.spec` still works without it; the installer
# script (packaging/inno_setup.iss) only advertises loudness normalization
# as working out of the box when it's actually present.
ffmpeg_exe = REPO_ROOT / "packaging" / "vendor" / "ffmpeg" / "ffmpeg.exe"
if ffmpeg_exe.is_file():
    datas.append((str(ffmpeg_exe), "."))

# Maintainer-bundled default AI provider key(s) (Pre-Alpha Testing spec) --
# placed here by hand (or by the release CI workflow from a repo secret)
# before a release build, same spot/same "skipped quietly if absent"
# pattern as ffmpeg above. See packaging/vendor/README.md for the required
# spend-cap precaution before bundling a real key this way --
# core.api_key_store.get_bundled_api_key reads it back at runtime from
# right next to Spiced.exe.
for _provider_key in ("openai", "gemini"):
    bundled_key_file = REPO_ROOT / "packaging" / "vendor" / f"bundled_{_provider_key}_key.txt"
    if bundled_key_file.is_file():
        datas.append((str(bundled_key_file), "."))

a = Analysis(
    [str(SRC / "spiced" / "app" / "main.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Spiced",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Spiced",
)
