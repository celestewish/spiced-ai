"""Google Gemini provider.

Reads the API key from the GEMINI_API_KEY environment variable. The key is
never hardcoded, logged, or written to disk by this module.
"""

from __future__ import annotations

import os

from spiced.ai.base import AIProvider, AIResponse

DEFAULT_MODEL = "gemini-1.5-flash"


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)

    def _api_key(self) -> str | None:
        key = os.environ.get("GEMINI_API_KEY")
        return key.strip() if key else None

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
                ".env file (see .env.example) to use the Gemini provider."
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
        result = model.generate_content(prompt)
        text = getattr(result, "text", None) or "(No text returned by Gemini.)"
        return AIResponse(text=text, provider=self.name, model=self.model)

    def display_name(self) -> str:
        return f"Gemini ({self.model})"
