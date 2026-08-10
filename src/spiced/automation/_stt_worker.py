"""Out-of-process worker: local speech-to-text transcription via
``faster-whisper`` (Implementation Bible, Feature 13).

Why this is a separate process rather than an in-process function call:
``faster-whisper``/``ctranslate2`` is a heavier native/ML dependency,
matching Feature 8's "run the risky step out-of-process so a crash there
is a catchable subprocess failure, not a dead Spiced" reasoning
(``automation._uv_lod_worker``) -- transcription inference is exactly that
category of dependency, even though no specific crash has been reproduced
here (unlike Feature 8's xatlas segfault, which was reproduced against a
real mesh). See ``docs/faster_whisper_model_caching.md`` for the model
download/caching behavior.

Invoked as ``python -m spiced.automation._stt_worker <audio_path>
<model_size> <device> <compute_type>``. Prints a JSON result to stdout on
success: ``{"text": "..."}``. On failure to even import
``faster_whisper``, prints the literal string ``STT_NOT_AVAILABLE`` to
stdout and exits 1, which the parent
(``localization_content_verification.run_stt_transcription``) checks for
specifically, the same convention ``connectors._renderdoc_worker`` uses
for ``RENDERDOC_NOT_AVAILABLE``. Not a public API -- only
``localization_content_verification`` calls this.
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    audio_path, model_size, device, compute_type = sys.argv[1:5]

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("STT_NOT_AVAILABLE")
        sys.exit(1)

    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _info = model.transcribe(audio_path)
    text = " ".join(segment.text.strip() for segment in segments).strip()

    print(json.dumps({"text": text}))


if __name__ == "__main__":
    main()
