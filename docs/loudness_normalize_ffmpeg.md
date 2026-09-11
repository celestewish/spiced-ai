# Loudness Normalization — the `ffmpeg` system dependency

Batch Processing & Loudness Normalization (`spiced.automation.loudness_normalize`)
uses the `ffmpeg-normalize` PyPI package, which is installed automatically
with Spiced's other Python dependencies. That package is only a wrapper,
though — it drives the real `ffmpeg` command-line tool, which is **not**
something `pip` can install. `ffmpeg` (v4.2 or newer, for the `loudnorm`
filter) must already be on the host machine's `PATH` (or pointed to via the
`FFMPEG_PATH` environment variable) before this feature can run.

If `ffmpeg` isn't found, `normalize_folder()` raises `FfmpegNotAvailableError`
before touching any file — never partway through a batch.

## Installing ffmpeg (source checkout / macOS / Linux)

- **Windows:** `winget install ffmpeg` (or download a build from
  https://ffmpeg.org/download.html and add its `bin/` folder to `PATH`).
- **macOS:** `brew install ffmpeg`
- **Linux:** `apt install ffmpeg` / `dnf install ffmpeg` / your distro's
  package manager.

## The Windows installer bundles its own

Connect-a-Project Setup Simplification spec, Finding 3 fix 4: the packaged
Windows installer (`packaging/inno_setup.iss`) bundles a static
`ffmpeg.exe` (see `packaging/vendor/README.md` for the build a maintainer
places before running a release build) and points `FFMPEG_PATH` at it via
a machine-level environment variable set at install time — loudness
normalization works out of the box for anyone using the installer, no
separate `ffmpeg` install needed. A source checkout (or a build run
without a vendored `ffmpeg.exe` present) still needs the manual install
above; a missing `ffmpeg` either way still fails cleanly with
`FfmpegNotAvailableError` before any file is touched, rather than partway
through a batch.
