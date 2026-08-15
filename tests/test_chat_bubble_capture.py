from datetime import datetime

import pytest

from ominime.chat_bubble_capture import (
    KIM_BUBBLE_PROFILE,
    WECHAT_BUBBLE_PROFILE,
    VisualBubbleSource,
)
from ominime.chat_window_capture import WindowFrame
from ominime.kim_composer_capture import NormalizedRect, RecognizedLine
from ominime.post_send_capture import MAX_TRUSTED_SUBMISSION_CHARS, SendIntent


def _frame(image="current", *, window_id=42, width=1000, height=800):
    return WindowFrame(image, window_id, 123, width, height, 10.2)


def _intent(*, app_name="Kim", bundle_id="Kem", baseline=None, intent_id="send-1"):
    return SendIntent(
        intent_id=intent_id,
        submitted_at=10.0,
        timestamp=datetime(2026, 8, 15, 12, 0),
        app_name=app_name,
        bundle_id=bundle_id,
        target_pid=123,
        modifiers={},
        physical_key_count=4,
        validation_text="",
        baseline=baseline or _frame("baseline"),
    )


def _source(lines, changed, *, current=None, clock=lambda: 10.25):
    return VisualBubbleSource(
        frame_provider=lambda pid: current or _frame(),
        ocr_provider=lambda image, bounds: tuple(lines),
        difference_provider=lambda before, after, bounds: tuple(changed),
        clock=clock,
    )


def test_profiles_derive_search_bounds_from_actual_frame_dimensions():
    kim = KIM_BUBBLE_PROFILE.search_bounds(_frame(width=1000, height=800))
    wechat_small = WECHAT_BUBBLE_PROFILE.search_bounds(
        _frame(width=880, height=640)
    )
    wechat_large = WECHAT_BUBBLE_PROFILE.search_bounds(
        _frame(width=1200, height=900)
    )

    assert tuple(round(value, 3) for value in (kim.x, kim.y, kim.width, kim.height)) == (
        0.28,
        0.20,
        0.70,
        0.71,
    )
    assert round(wechat_small.x * 880) == 305
    assert round(wechat_large.x * 1200) == 305
    assert round(wechat_small.y * 640) == 146
    assert round(wechat_large.y * 900) == 146
    assert round((1 - wechat_small.y - wechat_small.height) * 640) == 64
    assert round((1 - wechat_large.y - wechat_large.height) * 900) == 64


def test_visual_source_excludes_header_sidebar_and_composer_chrome():
    lines = (
        RecognizedLine("顶部导航", 0.5, 0.95, 0.2, 0.03),
        RecognizedLine("左侧会话", 0.05, 0.5, 0.15, 0.03),
        RecognizedLine("底部输入", 0.6, 0.05, 0.2, 0.03),
    )
    source = _source(lines, (NormalizedRect(0, 0, 1, 1),))

    result = source.read(_intent())

    assert result.failure_reason == "ocr_no_outgoing_bubble"
    assert result.content == ""


def test_visual_source_preserves_wrapped_line_order_in_outgoing_bubble():
    lines = (
        RecognizedLine("第二行", 0.72, 0.48, 0.20, 0.035),
        RecognizedLine("第一行", 0.70, 0.54, 0.22, 0.035),
    )
    changed = (NormalizedRect(0.68, 0.46, 0.27, 0.14),)

    result = _source(lines, changed).read(_intent())

    assert result.content == "第一行\n第二行"
    assert result.source == "kim_postsend_ocr"
    assert result.stability_key is not None


def test_visual_source_rejects_incoming_and_unchanged_old_bubbles():
    incoming = RecognizedLine("对方消息", 0.32, 0.5, 0.20, 0.04)
    old_outgoing = RecognizedLine("旧消息", 0.74, 0.65, 0.18, 0.04)
    unrelated_change = NormalizedRect(0.70, 0.3, 0.2, 0.08)

    result = _source(
        (incoming, old_outgoing),
        (unrelated_change,),
    ).read(_intent())

    assert result.failure_reason == "ocr_no_new_outgoing_bubble"


def test_visual_source_accepts_lowest_new_right_side_bubble():
    lines = (
        RecognizedLine("旧消息", 0.74, 0.68, 0.18, 0.04),
        RecognizedLine("最终文本", 0.72, 0.36, 0.20, 0.04),
        RecognizedLine("对方插话", 0.34, 0.28, 0.20, 0.04),
    )
    changed = (NormalizedRect(0.70, 0.34, 0.24, 0.09),)

    result = _source(lines, changed).read(_intent())

    assert result.content == "最终文本"
    assert result.message_identity.startswith("send-1:123:42:")


def test_identical_consecutive_messages_get_distinct_identities():
    line = RecognizedLine("相同文本", 0.72, 0.36, 0.20, 0.04)
    changed = (NormalizedRect(0.70, 0.34, 0.24, 0.09),)
    observed = iter((10.25, 10.55))
    source = _source((line,), changed, clock=lambda: next(observed))

    first = source.read(_intent(intent_id="send-1"))
    second = source.read(_intent(intent_id="send-2"))

    assert first.content == second.content == "相同文本"
    assert first.message_identity != second.message_identity


@pytest.mark.parametrize(
    ("lines", "failure"),
    [
        ((RecognizedLine("边缘裁切", 0.70, 0.201, 0.22, 0.04),), "ocr_edge_clipped"),
        (
            tuple(
                RecognizedLine("watermark", 0.70, 0.35 + index * 0.04, 0.2, 0.03)
                for index in range(3)
            ),
            "ocr_repeated_text_untrusted",
        ),
        ((RecognizedLine(" ", 0.72, 0.36, 0.2, 0.04),), "ocr_no_outgoing_bubble"),
        (
            (
                RecognizedLine(
                    "x" * (MAX_TRUSTED_SUBMISSION_CHARS + 1),
                    0.70,
                    0.36,
                    0.22,
                    0.04,
                ),
            ),
            "ocr_content_too_long",
        ),
    ],
)
def test_visual_source_rejects_untrusted_candidates(lines, failure):
    result = _source(
        lines,
        (NormalizedRect(0.68, 0.19, 0.28, 0.40),),
    ).read(_intent())

    assert result.failure_reason == failure
    assert result.content == ""


def test_post_send_bubble_accepts_committed_latin_without_doubao_preedit_rules():
    line = RecognizedLine("ceshi", 0.72, 0.36, 0.20, 0.04)

    result = _source(
        (line,),
        (NormalizedRect(0.70, 0.34, 0.24, 0.09),),
    ).read(_intent())

    assert result.content == "ceshi"


def test_visual_failure_diagnostic_never_contains_raw_candidate_text():
    private_text = "private-candidate-123"
    line = RecognizedLine(private_text, 0.30, 0.4, 0.20, 0.04)

    result = _source(
        (line,),
        (NormalizedRect(0.28, 0.38, 0.24, 0.09),),
    ).read(_intent())

    assert result.failure_reason == "ocr_no_outgoing_bubble"
    assert private_text not in repr(result)


def test_visual_source_rejects_mismatched_current_window():
    source = _source(
        (RecognizedLine("错误窗口", 0.72, 0.36, 0.20, 0.04),),
        (NormalizedRect(0.70, 0.34, 0.24, 0.09),),
        current=_frame(window_id=99),
    )

    result = source.read(_intent())

    assert result.failure_reason == "window_identity_mismatch"


def test_visual_source_propagates_cooperative_cancellation():
    cancelled = []

    class CancellableProvider:
        def __call__(self, *args):
            return ()

        def cancel(self):
            cancelled.append(type(self).__name__)

    source = VisualBubbleSource(
        frame_provider=lambda pid: _frame(),
        ocr_provider=CancellableProvider(),
        difference_provider=CancellableProvider(),
    )

    source.cancel()

    assert cancelled == ["CancellableProvider", "CancellableProvider"]
