# Bundled `ffmpeg` (Finding 3 fix 4)

Loudness normalization (`spiced.automation.loudness_normalize`) drives the
real `ffmpeg` binary, which `pip` can't install -- see
`docs/loudness_normalize_ffmpeg.md`. A source checkout still expects the
user to install `ffmpeg` themselves; the packaged installer bundles a
static build instead, so loudness normalization works out of the box.

## Getting a build

Download a Windows static build from one of the LGPL "essentials" builds
(no GPL-only components, so it's freely redistributable):

- https://www.gyan.dev/ffmpeg/builds/ ("release essentials" build)
- https://github.com/BtbN/FFmpeg-Builds/releases (`ffmpeg-master-latest-win64-lgpl.zip`)

Extract it and copy just `bin\ffmpeg.exe` to:

```
packaging/vendor/ffmpeg/ffmpeg.exe
```

That's the only file `packaging/spiced.spec` looks for -- `ffprobe.exe`
and the rest of the archive aren't needed.

## License

Confirm the specific build's license terms before shipping it (LGPL
"essentials" builds are freely redistributable, but verify the exact
build you download -- some mirrors bundle GPL-only codecs). Do not commit
`ffmpeg.exe` itself to this repo; `packaging/vendor/ffmpeg/` is
git-ignored for exactly that reason (a compiled binary has no business in
version control, and redistribution terms are a build-time decision, not
a commit).

## If it's absent

`packaging/spiced.spec` checks whether `packaging/vendor/ffmpeg/ffmpeg.exe`
exists and skips bundling it quietly if not -- a plain local
`pyinstaller packaging/spiced.spec` still produces a working build without
it. `packaging/inno_setup.iss`'s `FFMPEG_PATH` registry entry is
conditioned on the same file existing in the built output, so an installer
built without it behaves exactly like today's source checkout: loudness
normalization raises a clear `FfmpegNotAvailableError` pointing at
`docs/loudness_normalize_ffmpeg.md` instead of finding nothing and
crashing.
