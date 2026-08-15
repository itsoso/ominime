from ominime.kim_composer_capture import (
    CapturedFrame,
    DOUBAO_BUNDLE_ID,
    RecognizedLine,
)
from ominime.wechat_composer_capture import (
    WECHAT_COMPOSER_ROI,
    WeChatPreSubmitCapture,
)


def _frame():
    return CapturedFrame(
        "image",
        4318,
        880,
        640,
        12.5,
        DOUBAO_BUNDLE_ID,
    )


def test_wechat_capture_uses_bottom_composer_roi():
    calls = []
    capture = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: calls.append((image, roi))
        or (RecognizedLine("微信验收", 0.38, 0.08, 0.2, 0.02),)
    )

    assert capture.recognize(_frame()) == ("微信验收", None)
    assert calls == [("image", WECHAT_COMPOSER_ROI)]
    assert round(WECHAT_COMPOSER_ROI.x * 880, 3) == 305
    assert round(WECHAT_COMPOSER_ROI.y * 640, 3) == 6


def test_wechat_capture_accepts_observed_single_line_draft_position():
    capture = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine(
                "微信边界校准0809",
                0.3659,
                0.1938,
                0.1386,
                0.0234,
            ),
        )
    )

    assert capture.recognize(_frame()) == ("微信边界校准0809", None)


def test_wechat_roi_keeps_fixed_point_margins_when_window_resizes():
    capture = WeChatPreSubmitCapture()
    current = capture.composer_roi_for_frame(_frame())
    larger = capture.composer_roi_for_frame(
        CapturedFrame(
            "image",
            4318,
            1200,
            900,
            12.5,
            DOUBAO_BUNDLE_ID,
        )
    )

    assert round(current.x * 880, 3) == round(larger.x * 1200, 3)
    assert round(current.y * 640, 3) == round(larger.y * 900, 3)
    assert round((current.x + current.width) * 880, 3) == 872
    assert round((larger.x + larger.width) * 1200, 3) == 1192
    assert round((current.y + current.height) * 640, 3) == 146
    assert round((larger.y + larger.height) * 900, 3) == 146


def test_wechat_capture_uses_wechat_failure_codes():
    empty = WeChatPreSubmitCapture(ocr_provider=lambda image, roi: ())
    bottom_clipped = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("底部截断", 0.38, 0.011, 0.2, 0.02),
        )
    )
    top_clipped = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("顶部截断", 0.38, 0.216, 0.2, 0.012),
        )
    )
    left_clipped = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("左侧截断", roi.x, 0.08, 0.2, 0.02),
        )
    )

    assert empty.recognize(_frame()) == ("", "wechat_ocr_empty")
    assert bottom_clipped.recognize(_frame()) == (
        "",
        "wechat_ocr_edge_clipped",
    )
    assert top_clipped.recognize(_frame()) == (
        "",
        "wechat_ocr_edge_clipped",
    )
    assert left_clipped.recognize(_frame()) == (
        "",
        "wechat_ocr_edge_clipped",
    )


def test_wechat_capture_accepts_multiline_but_rejects_uncommitted_pinyin():
    multiline = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("第一行", 0.38, 0.14, 0.2, 0.02),
            RecognizedLine("第二行", 0.38, 0.08, 0.2, 0.02),
        )
    )
    pinyin = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("weixin", 0.38, 0.08, 0.2, 0.02),
        )
    )

    assert multiline.recognize(_frame()) == ("第一行\n第二行", None)
    assert pinyin.recognize(_frame()) == (
        "",
        "wechat_ocr_uncommitted_text",
    )


def test_wechat_capture_rejects_three_repeated_ocr_rows():
    capture = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("重复", 0.38, 0.14, 0.2, 0.02),
            RecognizedLine("重复", 0.38, 0.11, 0.2, 0.02),
            RecognizedLine("重复", 0.38, 0.08, 0.2, 0.02),
        )
    )

    assert capture.recognize(_frame()) == (
        "",
        "wechat_ocr_repeated_text_untrusted",
    )
