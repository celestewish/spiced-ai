"""Local storage for AI provider API keys entered through the Settings screen.

Connect-a-Project Setup Simplification spec, Finding 3 fix 1: a packaged
``.exe`` build has no shell and no ``.env`` file for a non-technical user to
edit, so ``OPENAI_API_KEY``/``GEMINI_API_KEY`` need an in-app fallback.
``ai.openai_provider``/``ai.gemini_provider`` each check the environment
variable first, falling back to ``get_api_key`` here only if it's unset --
see each provider's ``_api_key()``.

Deliberately a standalone plain-file store rather than a row in
``storage.settings.SettingsRepository`` (the app's general SQLite-backed
settings table): providers are constructible with zero arguments today and
don't otherwise depend on the app's database/``Services`` layer, and this
keeps it that way. Same trust tier as the existing local SQLite database
(``storage.database.default_db_path``) -- both live under the per-user
``~/.spiced`` folder -- and same promise as every other secret this codebase
handles: never sent anywhere but the provider itself.

Best-effort on read, like every other optional-metadata read in this
codebase (e.g. ``connectors.unity``'s version reads) -- a missing or
corrupt store just means "no key configured" rather than a crash.

``get_bundled_api_key`` below (Pre-Alpha Testing spec) is a different,
maintainer-supplied key -- see ``packaging/vendor/README.md`` -- baked into
a packaged build so a tester gets working AI features with zero setup, no
account or key of their own required. It is always the *last* fallback: an
environment variable or a key a developer saved here themselves (this
module's own ``get_api_key``) both take priority -- see each provider's
``_api_key()``. It is explicitly not secret storage: anyone with the built
installer can extract it, which is why ``packaging/vendor/README.md``
requires a hard provider-side spending cap on whatever key is bundled this
way, not confidentiality, as the actual safeguard.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _store_path() -> Path:
    base = Path.home() / ".spiced"
    base.mkdir(parents=True, exist_ok=True)
    return base / "api_keys.json"


def get_api_key(provider_key: str) -> str | None:
    """Return the stored key for ``provider_key`` (e.g. ``"openai"``), or
    ``None`` if none is saved or the store can't be read."""
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(provider_key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_api_key(provider_key: str, value: str) -> None:
    """Save the key for ``provider_key``, or clear it if ``value`` is blank."""
    path = _store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    value = value.strip()
    if value:
        data[provider_key] = value
    else:
        data.pop(provider_key, None)
    path.write_text(json.dumps(data), encoding="utf-8")


def _bundled_key_path(provider_key: str) -> Path:
    """Where a maintainer-bundled default key for ``provider_key`` lives.

    In a frozen (PyInstaller) build, ``packaging/spiced.spec`` bundles it
    next to ``Spiced.exe`` itself if present at build time. Running from a
    source checkout instead reads straight from ``packaging/vendor/`` --
    the same spot a maintainer drops it into *before* building (see
    ``packaging/vendor/README.md``), so the bundled-key fallback can be
    exercised/tested without actually building the frozen exe.
    """
    filename = f"bundled_{provider_key}_key.txt"
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / filename
    # src/spiced/core/api_key_store.py -> repo root is three parents up,
    # same depth packaging/spiced.spec computes for itself (REPO_ROOT).
    return Path(__file__).resolve().parents[3] / "packaging" / "vendor" / filename


def get_bundled_api_key(provider_key: str) -> str | None:
    """A maintainer-provided default key baked into a packaged build --
    see this module's own docstring and ``packaging/vendor/README.md``.
    Best-effort: a missing or unreadable file just means "no bundled key",
    the same degrade-quietly behavior as ``get_api_key`` above.
    """
    try:
        text = _bundled_key_path(provider_key).read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    return text or None
