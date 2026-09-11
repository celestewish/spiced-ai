"""OpenAI provider.

Reads the API key from the OPENAI_API_KEY environment variable and the model
from OPENAI_MODEL (defaulting to a conservative, widely available model). If
the environment variable isn't set, falls back to a key saved through the
Settings screen (see core.api_key_store) -- the environment variable always
wins when both are present. The key is never hardcoded or logged by this
module.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from spiced.ai.base import AIProvider, AIResponse
from spiced.core.api_key_store import get_api_key

DEFAULT_MODEL = "gpt-4o-mini"


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self, model: str | None = None) -> None:
        self.model = model or os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)

    def _api_key(self) -> str | None:
        key = os.environ.get("OPENAI_API_KEY")
        if key and key.strip():
            return key.strip()
        return get_api_key("openai")

    def is_available(self) -> bool:
        if not self._api_key():
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def generate(self, prompt: str) -> AIResponse:
        key = self._api_key()
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your environment or a local "
                ".env file (see .env.example), or paste it into Settings -> API key, "
                "to use the OpenAI provider."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is not installed. "
                "Install project dependencies to use OpenAI."
            ) from exc

        client = OpenAI(api_key=key)
        try:
            result = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise self._friendly_error(exc) from exc
        text = (result.choices[0].message.content or "").strip() or "(No text returned by OpenAI.)"
        return AIResponse(text=text, provider=self.name, model=self.model)

    def generate_stream(self, prompt: str, on_chunk: Callable[[str], None]) -> AIResponse:
        key = self._api_key()
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to your environment or a local "
                ".env file (see .env.example), or paste it into Settings -> API key, "
                "to use the OpenAI provider."
            )
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "The 'openai' package is not installed. "
                "Install project dependencies to use OpenAI."
            ) from exc

        client = OpenAI(api_key=key)
        parts: list[str] = []
        try:
            stream = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for event in stream:
                delta = event.choices[0].delta.content if event.choices else None
                if delta:
                    parts.append(delta)
                    on_chunk(delta)
        except Exception as exc:
            raise self._friendly_error(exc) from exc
        text = "".join(parts).strip() or "(No text returned by OpenAI.)"
        return AIResponse(text=text, provider=self.name, model=self.model)

    def _friendly_error(self, exc: Exception) -> RuntimeError:
        message = str(exc)
        lowered = message.lower()
        if "model" in lowered and ("not found" in lowered or "does not exist" in lowered):
            return RuntimeError(
                f"The OpenAI model '{self.model}' isn't available for your API key. "
                "Set OPENAI_MODEL to a supported model (for example 'gpt-4o-mini') "
                "in your environment or local .env file, then try again."
            )
        if "api key" in lowered or "authentication" in lowered or "401" in lowered:
            return RuntimeError(
                "OpenAI rejected the API key. Check OPENAI_API_KEY in your environment "
                "or local .env file, then try again."
            )
        return RuntimeError(f"OpenAI request failed: {message}")

    def display_name(self) -> str:
        return f"OpenAI ({self.model})"
