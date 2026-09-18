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

## Bundled default AI provider key (Pre-Alpha Testing spec)

So a pre-alpha tester gets working AI features (Debugging Buddy's crash
analysis, etc.) with zero setup -- no account, no key of their own --
the build can bundle a maintainer-supplied default key. It's read back at
runtime by `core.api_key_store.get_bundled_api_key`, and is always the
*last* fallback: an environment variable or a key the developer saved
themselves in Settings both take priority. A tester can still paste their
own key in Settings at any time to stop using the bundled one.

**This is not secret storage.** Anyone with the built installer can
extract this key (PyInstaller's bundling is not obfuscation, let alone
encryption) -- the same way any bundled asset can be pulled out of a
`dist/Spiced/` folder or the installer. Treat it accordingly:

1. **Create a key dedicated to this purpose** at your provider (OpenAI/
   Google) -- not one you use anywhere else, so it can be revoked or
   rotated independently without breaking something unrelated.
2. **Set a hard monthly spending cap on that key** in the provider's own
   dashboard before bundling it anywhere (OpenAI: Settings -> Billing ->
   Limits; Google AI Studio / Cloud Console: budgets & alerts on the
   associated project). This is what actually bounds the damage if the
   key leaks -- not keeping it hidden, since it won't stay hidden.
3. Save the raw key value, nothing else (no quotes, no `KEY=` prefix), to:

   ```
   packaging/vendor/bundled_openai_key.txt
   ```

   (or `bundled_gemini_key.txt` for Gemini -- `packaging/spiced.spec`
   checks for both independently).

4. **Never commit this file.** `packaging/vendor/bundled_*_key.txt` is
   git-ignored for exactly that reason -- double-check `git status` before
   committing anything in this directory regardless.

For a CI-built release (`.github/workflows/release.yml`), the same file is
written from a GitHub Actions repository secret instead of a local file --
see that workflow for the exact secret name it expects. Configuring that
secret (Settings -> Secrets and variables -> Actions on the repo) is a
one-time setup step only a repo admin can do.

### If it's absent

Same "skipped quietly" shape as ffmpeg above: `packaging/spiced.spec`
checks whether either bundled-key file exists and only bundles the ones
that are actually there. A build without one behaves exactly like today's
source checkout for that provider -- a tester (or developer) needs their
own key in Settings, or uses the always-available MockProvider.
