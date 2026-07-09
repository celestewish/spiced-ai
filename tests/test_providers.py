from spiced.ai import DEFAULT_PROVIDER, MockProvider, OpenAIProvider, build_provider
from spiced.ai.gemini_provider import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
from spiced.ai.gemini_provider import GeminiProvider
from spiced.ai.openai_provider import DEFAULT_MODEL as OPENAI_DEFAULT_MODEL


def test_mock_provider_always_available():
    provider = MockProvider()
    assert provider.is_available()
    response = provider.generate("Why is my player falling through the floor?")
    assert response.provider == "mock"
    assert response.text


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
