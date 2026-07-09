
from spiced.ai import MockProvider, build_provider
from spiced.ai.gemini_provider import DEFAULT_MODEL, GeminiProvider


def test_mock_provider_always_available():
    provider = MockProvider()
    assert provider.is_available()
    response = provider.generate("Why is my player falling through the floor?")
    assert response.provider == "mock"
    assert response.text


def test_factory_builds_known_providers():
    assert isinstance(build_provider("mock"), MockProvider)
    assert isinstance(build_provider("gemini"), GeminiProvider)


def test_gemini_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiProvider().is_available() is False


def test_gemini_generate_raises_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider()
    try:
        provider.generate("hello")
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError when key is missing")


def test_default_model_is_current_and_supported():
    assert DEFAULT_MODEL == "gemini-2.0-flash"


def test_gemini_model_configurable_via_env(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    assert GeminiProvider().model == "gemini-2.5-flash"


def test_explicit_model_overrides_default(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert GeminiProvider(model="custom-model").model == "custom-model"
    assert GeminiProvider().model == DEFAULT_MODEL


def test_model_not_found_error_mentions_gemini_model():
    provider = GeminiProvider(model="gemini-1.5-flash")
    err = provider._friendly_error(
        Exception("404 models/gemini-1.5-flash is not found for API version v1beta")
    )
    assert "GEMINI_MODEL" in str(err)
    assert "gemini-1.5-flash" in str(err)
