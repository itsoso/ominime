import ominime.llm_backend as llm_backend


def test_openai_backend_is_not_available():
    assert not hasattr(llm_backend, "OpenAIBackend")


def test_factory_rejects_remote_backend_name(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "openai")

    assert llm_backend.get_llm_backend() is None


def test_factory_defaults_to_local_ollama(monkeypatch):
    monkeypatch.delenv("LLM_BACKEND", raising=False)
    monkeypatch.setattr(llm_backend.OllamaBackend, "is_available", lambda self: True)

    backend = llm_backend.get_llm_backend()

    assert isinstance(backend, llm_backend.OllamaBackend)


def test_factory_rejects_non_loopback_ollama_endpoint(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://models.example.com")
    monkeypatch.setattr(
        llm_backend.OllamaBackend,
        "is_available",
        lambda self: (_ for _ in ()).throw(AssertionError("remote health check attempted")),
    )

    assert llm_backend.get_llm_backend() is None
