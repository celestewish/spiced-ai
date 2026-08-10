# Localization Content Verification -- the `faster-whisper` model cache

Localization Audio Sync Checker, Content Verification
(`spiced.automation.localization_content_verification`) uses
[`faster-whisper`](https://github.com/SYSTRAN/faster-whisper), a fully local,
self-hosted speech-to-text engine -- no audio ever leaves the machine, and no
network call is made once a model is cached.

## First run vs. every run after

The first time a given model size (default: `tiny.en`) is used, `faster-whisper`
downloads it from Hugging Face Hub and caches it under the OS's usual
Hugging Face cache directory (`~/.cache/huggingface/hub` on Linux/macOS,
`%USERPROFILE%\.cache\huggingface\hub` on Windows). That first download needs
an internet connection; every run after that is fully offline, reading the
model from the local cache.

If you want to pre-warm the cache (e.g. for an offline machine, or a CI
runner with no network access), run a transcription once on any machine with
internet access, then copy that cache directory over.

## Model size

`tiny.en` is the default -- fast (well under a second per short voice line on
a modern CPU) and English-only. Larger models (`base`, `small`, `medium`, ...)
are more accurate but slower and larger to download; pass a different
`model_size` to `run_stt_transcription`/the CLI's `--model-size` flag if
accuracy on a specific project's voice lines needs it.

## Isolation

Transcription runs in a subprocess (`spiced.automation._stt_worker`), the
same isolation pattern Feature 8 (UV Unwrapping + LOD Generation) uses for
its xatlas unwrap step -- a heavier native/ML dependency crashing shouldn't
be able to take down the whole desktop app either. If `faster-whisper` (or
one of its native dependencies, `ctranslate2`) isn't importable in the
worker's own Python environment, the worker reports that cleanly instead of
crashing, the same way `connectors._renderdoc_worker` reports
`RENDERDOC_NOT_AVAILABLE` when `renderdoc` can't be imported.
