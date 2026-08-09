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
    assert WECHAT_COMPOSER_ROI.x == 0.35
    assert WECHAT_COMPOSER_ROI.y == 0.01


def test_wechat_capture_uses_wechat_failure_codes():
    empty = WeChatPreSubmitCapture(ocr_provider=lambda image, roi: ())
    bottom_clipped = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("底部截断", 0.38, 0.011, 0.2, 0.02),
        )
    )
    top_clipped = WeChatPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("顶部截断", 0.38, 0.205, 0.2, 0.015),
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


def test_wechat_capture_rejects_multiline_and_uncommitted_pinyin():
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

    assert multiline.recognize(_frame()) == (
        "",
        "wechat_ocr_multiline_untrusted",
    )
    assert pinyin.recognize(_frame()) == (
        "",
        "wechat_ocr_uncommitted_text",
    )
