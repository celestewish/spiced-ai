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

## Installing ffmpeg

- **Windows:** `winget install ffmpeg` (or download a build from
  https://ffmpeg.org/download.html and add its `bin/` folder to `PATH`).
- **macOS:** `brew install ffmpeg`
- **Linux:** `apt install ffmpeg` / `dnf install ffmpeg` / your distro's
  package manager.

Spiced's installer should document this as a prerequisite, the same way it
already documents a Unity install for engine-connected features — Spiced
itself never installs `ffmpeg` on the user's behalf.
