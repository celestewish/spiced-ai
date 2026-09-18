"""Google Gemini provider.

Reads the API key from the GEMINI_API_KEY environment variable. If the
environment variable isn't set, falls back to a key saved through the
Settings screen (see core.api_key_store), then to a maintainer-bundled
default key baked into a packaged build (Pre-Alpha Testing spec) -- see
core.api_key_store.get_bundled_api_key's own docstring. The key is never
hardcoded or logged by this module.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from spiced.ai.base import AIProvider, AIResponse
from spiced.core.api_key_store import get_api_key, get_bundled_api_key

DEFAULT_MODEL = "gemini-2.0-flash"


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)

    def _api_key(self) -> str | None:
        key = os.environ.get("GEMINI_API_KEY")
        if key and key.strip():
            return key.strip()
        return get_api_key("gemini") or get_bundled_api_key("gemini")

    def is_available(self) -> bool:
        if not self._api_key():
            return False
        try:
            import google.generativeai  # noqa: F401
        except ImportError:
            return False
        return True

    def generate(self, prompt: str) -> AIResponse:
        key = self._api_key()
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your environment or a local "
                ".env file (see .env.example), or paste it into Settings -> API key, "
                "to use the Gemini provider."
            )
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError(
                "The 'google-generativeai' package is not installed. "
                "Install project dependencies to use Gemini."
            ) from exc

        genai.configure(api_key=key)
        model = genai.GenerativeModel(self.model)
        try:
            result = model.generate_content(prompt)
        except Exception as exc:
            raise self._friendly_error(exc) from exc
        text = getattr(result, "text", None) or "(No text returned by Gemini.)"
        return AIResponse(text=text, provider=self.name, model=self.model)

    def generate_stream(self, prompt: str, on_chunk: Callable[[str], None]) -> AIResponse:
        key = self._api_key()
        if not key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to your environment or a local "
                ".env file (see .env.example), or paste it into Settings -> API key, "
                "to use the Gemini provider."
            )
        try:
            import google.generativeai as genai
        except ImportError as exc:
            raise RuntimeError(
                "The 'google-generativeai' package is not installed. "
                "Install project dependencies to use Gemini."
            ) from exc

        genai.configure(api_key=key)
        model = genai.GenerativeModel(self.model)
        parts: list[str] = []
        try:
            for event in model.generate_content(prompt, stream=True):
                delta = getattr(event, "text", None)
                if delta:
                    parts.append(delta)
                    on_chunk(delta)
        except Exception as exc:
            raise self._friendly_error(exc) from exc
        text = "".join(parts) or "(No text returned by Gemini.)"
        return AIResponse(text=text, provider=self.name, model=self.model)

    def _friendly_error(self, exc: Exception) -> RuntimeError:
        message = str(exc)
        if "not found" in message.lower() or "is not supported" in message.lower():
            return RuntimeError(
                f"The Gemini model '{self.model}' isn't available for your API key. "
                "Set GEMINI_MODEL to a supported model (for example 'gemini-2.0-flash') "
                "in your environment or local .env file, then try again."
            )
        return RuntimeError(f"Gemini request failed: {message}")

    def display_name(self) -> str:
        return f"Gemini ({self.model})"
