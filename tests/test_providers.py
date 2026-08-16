from spiced.ai import DEFAULT_PROVIDER, MockProvider, OpenAIProvider, build_provider
from spiced.ai.base import AIProvider, AIResponse
from spiced.ai.gemini_provider import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from spiced.ai.gemini_provider import GeminiProvider
from spiced.ai.openai_provider import DEFAULT_MODEL as OPENAI_DEFAULT_MODEL


def test_mock_provider_always_available():
    provider = MockProvider()
    assert provider.is_available()
    response = provider.generate("Why is my player falling through the floor?")
    assert response.provider == "mock"
    assert response.text


# --- Streaming ---


def test_mock_generate_stream_emits_multiple_chunks_and_final_text_matches():
    provider = MockProvider()
    chunks: list[str] = []
    prompt = "Why is my player falling through the floor?"
    response = provider.generate_stream(prompt, chunks.append)
    assert len(chunks) > 1
    assert "".join(chunks) == response.text


def test_default_generate_stream_fallback_emits_whole_response_once():
    class _OnlyGenerate(AIProvider):
        name = "only-generate"

        def is_available(self) -> bool:
            return True

        def generate(self, prompt: str) -> AIResponse:
            return AIResponse(text="whole response", provider=self.name)

    chunks: list[str] = []
    response = _OnlyGenerate().generate_stream("hello", chunks.append)
    assert chunks == ["whole response"]
    assert response.text == "whole response"


class _FakeOpenAIDelta:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeOpenAIChoice:
    def __init__(self, content: str | None) -> None:
        self.delta = _FakeOpenAIDelta(content)


class _FakeOpenAIChunk:
    def __init__(self, content: str | None) -> None:
        self.choices = [_FakeOpenAIChoice(content)]


class _FakeOpenAIClient:
    captured_kwargs: dict = {}

    def __init__(self, api_key: str | None = None) -> None:
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        _FakeOpenAIClient.captured_kwargs = kwargs
        return [_FakeOpenAIChunk("Hello "), _FakeOpenAIChunk("world"), _FakeOpenAIChunk(None)]


def test_openai_generate_stream_accumulates_delta_content(monkeypatch):
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAIClient)

    provider = OpenAIProvider(model="gpt-4o-mini")
    chunks: list[str] = []
    response = provider.generate_stream("hello", chunks.append)

    assert chunks == ["Hello ", "world"]
    assert response.text == "Hello world"
    assert _FakeOpenAIClient.captured_kwargs["stream"] is True


class _FakeGeminiChunk:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeGeminiModel:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name

    def generate_content(self, prompt: str, *, stream: bool = False):
        assert stream is True
        return [_FakeGeminiChunk("Hi "), _FakeGeminiChunk("there")]


def test_gemini_generate_stream_accumulates_text_chunks(monkeypatch):
    import google.generativeai as genai

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(genai, "configure", lambda **kwargs: None)
    monkeypatch.setattr(genai, "GenerativeModel", _FakeGeminiModel)

    provider = GeminiProvider(model="gemini-2.0-flash")
    chunks: list[str] = []
    response = provider.generate_stream("hello", chunks.append)

    assert chunks == ["Hi ", "there"]
    assert response.text == "Hi there"


# --- Provider factory / default selection ---


def test_default_provider_is_openai():
    assert DEFAULT_PROVIDER == "openai"


def test_factory_builds_known_providers():
    assert isinstance(build_provider("openai"), OpenAIProvider)
    assert isinstance(build_provider("mock"), MockProvider)
    assert isinstance(build_provider("gemini"), GeminiProvider)


def test_factory_defaults_to_openai_when_empty():
    assert isinstance(build_provider(""), OpenAIProvider)


# --- OpenAI provider (default) ---


def test_openai_default_model():
    assert OPENAI_DEFAULT_MODEL == "gpt-4o-mini"


def test_openai_model_configurable_via_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    assert OpenAIProvider().model == "gpt-4o"


def test_openai_explicit_model_overrides_default(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert OpenAIProvider(model="custom-model").model == "custom-model"
    assert OpenAIProvider().model == OPENAI_DEFAULT_MODEL


def test_openai_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAIProvider().is_available() is False


def test_openai_generate_raises_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    try:
        OpenAIProvider().generate("hello")
    except RuntimeError as exc:
        assert "OPENAI_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError when key is missing")


def test_openai_model_not_found_error_mentions_openai_model():
    provider = OpenAIProvider(model="gpt-nope")
    err = provider._friendly_error(Exception("The model `gpt-nope` does not exist"))
    assert "OPENAI_MODEL" in str(err)
    assert "gpt-nope" in str(err)


def test_openai_bad_key_error_is_friendly():
    provider = OpenAIProvider(model="gpt-4o-mini")
    err = provider._friendly_error(Exception("Error code: 401 - invalid api key"))
    assert "OPENAI_API_KEY" in str(err)


# --- Gemini provider (optional, no longer default) ---


def test_gemini_default_model():
    assert GEMINI_DEFAULT_MODEL == "gemini-2.0-flash"


def test_gemini_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiProvider().is_available() is False


def test_gemini_generate_raises_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        GeminiProvider().generate("hello")
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError when key is missing")


def test_gemini_model_not_found_error_mentions_gemini_model():
    provider = GeminiProvider(model="gemini-1.5-flash")
    err = provider._friendly_error(
        Exception("404 models/gemini-1.5-flash is not found for API version v1beta")
    )
    assert "GEMINI_MODEL" in str(err)
    assert "gemini-1.5-flash" in str(err)
