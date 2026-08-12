from datetime import date
import sys
from types import SimpleNamespace

from ominime import analyzer as analyzer_module
from ominime.analyzer import Analyzer
from ominime.database import AppDailyStats
from ominime.llm_backend import OllamaBackend


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

    monkeypatch.setitem(
        sys.modules,
        "requests",
        SimpleNamespace(
            post=lambda *args, **kwargs: calls.append((args, kwargs)) or Response()
        ),
    )

    OllamaBackend().chat([])

    assert calls[0][1]["timeout"] == 30
