from datetime import date
import sys
from types import SimpleNamespace

from ominime import analyzer as analyzer_module
from ominime.analyzer import Analyzer
from ominime.database import AppDailyStats
from ominime.llm_backend import LLMMessage, OllamaBackend, QwenLocalBackend


class FailingBackend:
    def __init__(self):
        self.calls = 0

    def chat(self, **_kwargs):
        self.calls += 1
        raise RuntimeError("backend unavailable")


def test_ai_summary_failure_falls_back_without_recursion(monkeypatch):
    backend = FailingBackend()
    analyzer = object.__new__(Analyzer)
    analyzer._llm_backend = backend
    monkeypatch.setattr(analyzer_module.config, "ai_enabled", True)
    stats = [
        AppDailyStats(
            app_name="Codex",
            display_name="Codex",
            total_chars=42,
            session_count=1,
            total_time_minutes=0,
            sample_content=["a sufficiently long local input sample"],
        )
    ]

    summary = analyzer._generate_summary(stats, date(2026, 8, 11))

    assert backend.calls == 1
    assert "今日共输入 42 个字符" in summary


def test_ollama_chat_uses_finite_timeout(monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "ok"}}

    class Session:
        trust_env = True

        def post(self, *args, **kwargs):
            calls.append((self.trust_env, args, kwargs))
            return Response()

    monkeypatch.setitem(sys.modules, "requests", SimpleNamespace(Session=Session))

    OllamaBackend().chat([])

    trust_env, _args, kwargs = calls[0]
    assert trust_env is False
    assert kwargs["timeout"] == 30
    assert kwargs["allow_redirects"] is False


def test_qwen_greedy_generation_disables_sampling_at_zero_temperature():
    calls = []

    class Inputs(dict):
        input_ids = [[1, 2]]

        def to(self, _device):
            return self

    class Tokenizer:
        def apply_chat_template(self, *_args, **_kwargs):
            return "prompt"

        def __call__(self, *_args, **_kwargs):
            return Inputs(input_ids=self.input_ids)

        def batch_decode(self, *_args, **_kwargs):
            return ["ok"]

        input_ids = [[1, 2]]

    class Model:
        device = "cpu"

        def generate(self, **kwargs):
            calls.append(kwargs)
            return [[1, 2, 3]]

    backend = QwenLocalBackend()
    backend._tokenizer = Tokenizer()
    backend._model = Model()

    response = backend.chat([LLMMessage(role="user", content="test")], temperature=0)

    assert response.content == "ok"
    assert calls[0]["do_sample"] is False
    assert "temperature" not in calls[0]
