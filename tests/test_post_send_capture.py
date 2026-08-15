from datetime import datetime

import pytest

from ominime.post_send_capture import (
    MAX_TRUSTED_SUBMISSION_CHARS,
    MessageSourceChain,
    SendIntent,
    SourceResult,
)


class FakeSource:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def read(self, intent):
        self.calls.append(intent)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def intent():
    return SendIntent(
        intent_id="send-1",
        submitted_at=10.0,
        timestamp=datetime(2026, 8, 15, 12, 0),
        app_name="Kim",
        bundle_id="Kem",
        target_pid=123,
        modifiers={},
        physical_key_count=4,
        validation_text="测试",
        baseline=None,
    )


def test_send_intent_is_immutable(intent):
    with pytest.raises(AttributeError):
        intent.target_pid = 456


def test_source_chain_returns_first_trusted_result(intent):
    unavailable = FakeSource(SourceResult.unavailable("ax_unavailable"))
    trusted = FakeSource(
        SourceResult.success(
            "  测试\n完成  ",
            "kim_postsend_ocr",
            "bubble-1",
            target_pid=123,
            observed_at=10.2,
        )
    )
    unused = FakeSource(
        SourceResult.success(
            "wrong",
            "unused",
            "bubble-2",
            target_pid=123,
            observed_at=10.3,
        )
    )

    result = MessageSourceChain([unavailable, trusted, unused]).read(intent)

    assert result.content == "测试\n完成"
    assert len(unavailable.calls) == 1
    assert len(trusted.calls) == 1
    assert unused.calls == []


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (
            SourceResult.success(
                "   ",
                "kim_postsend_ocr",
                "bubble-empty",
                target_pid=123,
                observed_at=10.2,
            ),
            "empty_content",
        ),
        (
            SourceResult.success(
                "x" * (MAX_TRUSTED_SUBMISSION_CHARS + 1),
                "kim_postsend_ocr",
                "bubble-long",
                target_pid=123,
                observed_at=10.2,
            ),
            "content_too_long",
        ),
        (
            SourceResult.success(
                "测试",
                "kim_postsend_ocr",
                "bubble-pid",
                target_pid=456,
                observed_at=10.2,
            ),
            "target_pid_mismatch",
        ),
        (
            SourceResult.success(
                "测试",
                "kim_postsend_ocr",
                "bubble-stale",
                target_pid=123,
                observed_at=9.9,
            ),
            "stale_observation",
        ),
    ],
)
def test_source_chain_rejects_untrusted_result(intent, result, reason):
    fallback = FakeSource(SourceResult.unavailable("fallback_unavailable"))

    outcome = MessageSourceChain([FakeSource(result), fallback]).read(intent)

    assert outcome.failure_reason == "fallback_unavailable"
    assert reason in outcome.diagnostics
    assert len(fallback.calls) == 1


def test_source_exception_is_named_and_next_source_runs(intent):
    fallback = FakeSource(
        SourceResult.success(
            "测试",
            "kim_postsend_ocr",
            "bubble-ok",
            target_pid=123,
            observed_at=10.2,
        )
    )

    result = MessageSourceChain(
        [FakeSource(RuntimeError("private candidate text")), fallback]
    ).read(intent)

    assert result.content == "测试"
    assert result.diagnostics == ("source_exception:FakeSource",)
    assert "private candidate text" not in repr(result)
