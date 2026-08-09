from ominime.kim_composer_capture import (
    CapturedFrame,
    DOUBAO_BUNDLE_ID,
    KIM_COMPOSER_ROI,
    KimPreSubmitCapture,
    RecognizedLine,
    WindowInfo,
    assemble_recognized_text,
    ocr_text_matches_physical_count,
    ocr_text_is_trusted,
)


def test_assemble_recognized_text_orders_visual_rows():
    lines = (
        RecognizedLine("第二行", x=0.1, y=0.2, width=0.3, height=0.1),
        RecognizedLine("后半", x=0.5, y=0.8, width=0.2, height=0.1),
        RecognizedLine("第一行", x=0.1, y=0.8, width=0.3, height=0.1),
    )

    assert assemble_recognized_text(lines) == "第一行 后半\n第二行"


def test_assemble_recognized_text_ignores_empty_and_chrome_only_lines():
    lines = (
        RecognizedLine("  ", x=0.1, y=0.9, width=0.2, height=0.1),
        RecognizedLine("「", x=0.9, y=0.8, width=0.05, height=0.1),
        RecognizedLine(
            "↩︎ 发送 / ⌘↩︎ 换行",
            x=0.1,
            y=0.5,
            width=0.5,
            height=0.1,
        ),
        RecognizedLine("B I S", x=0.5, y=0.4, width=0.3, height=0.1),
        RecognizedLine("有效内容", x=0.1, y=0.2, width=0.3, height=0.1),
    )

    assert assemble_recognized_text(lines) == "有效内容"


def test_assemble_recognized_text_bounds_output():
    text = assemble_recognized_text(
        (RecognizedLine("测" * 5000, x=0, y=0.5, width=1, height=0.1),)
    )

    assert len(text) == 4000


def test_doubao_ocr_requires_committed_cjk_text():
    assert ocr_text_is_trusted("测试", DOUBAO_BUNDLE_ID)
    assert not ocr_text_is_trusted("ce'shi", DOUBAO_BUNDLE_ID)
    assert not ocr_text_is_trusted("  ceshi  ", DOUBAO_BUNDLE_ID)
    assert not ocr_text_is_trusted("你好 shijie", DOUBAO_BUNDLE_ID)


def test_non_doubao_ocr_accepts_nonempty_latin_text():
    assert ocr_text_is_trusted("hello", "com.apple.keylayout.ABC")
    assert not ocr_text_is_trusted("  ", "com.apple.keylayout.ABC")


def test_ocr_text_must_be_plausible_for_physical_key_count():
    assert ocr_text_matches_physical_count("测试", 6)
    assert ocr_text_matches_physical_count("测试成功", 1)
    assert not ocr_text_matches_physical_count("测试", 0)
    assert not ocr_text_matches_physical_count("测试", 100)


def test_freeze_selects_largest_normal_window_for_target_pid():
    selected = []
    window_calls = []

    def windows():
        window_calls.append(True)
        return (
            WindowInfo(1, 123, 0, 66, 20),
            WindowInfo(2, 999, 0, 1200, 900),
            WindowInfo(3, 123, 4, 1200, 900),
            WindowInfo(4, 123, 0, 1197, 925),
        )

    capture = KimPreSubmitCapture(
        clock=lambda: 12.5,
        window_provider=windows,
        image_provider=lambda window_id: selected.append(window_id) or "image",
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
    )

    assert capture.prepare(123)
    frame = capture.freeze(123)

    assert frame == CapturedFrame(
        "image",
        123,
        1197,
        925,
        12.5,
        DOUBAO_BUNDLE_ID,
    )
    assert selected == [4]
    assert window_calls == [True]


def test_freeze_does_not_enumerate_windows_on_callback_path():
    calls = []
    capture = KimPreSubmitCapture(
        window_provider=lambda: calls.append(True)
        or (WindowInfo(4, 123, 0, 1197, 925),),
        image_provider=lambda window_id: "image",
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
    )

    assert capture.freeze(123) is None
    assert calls == []


def test_freeze_rejects_invalid_or_missing_target_window():
    capture = KimPreSubmitCapture(
        window_provider=lambda: (WindowInfo(1, 123, 0, 66, 20),),
        image_provider=lambda window_id: "image",
    )

    assert capture.freeze(0) is None
    assert capture.freeze(123) is None


def test_freeze_returns_none_when_native_image_capture_fails():
    def fail_image(window_id):
        raise RuntimeError("capture failed")

    capture = KimPreSubmitCapture(
        window_provider=lambda: (WindowInfo(4, 123, 0, 1197, 925),),
        image_provider=fail_image,
    )

    assert capture.prepare(123)
    assert capture.freeze(123) is None


def test_recognize_uses_kim_roi_and_returns_trusted_text():
    calls = []
    capture = KimPreSubmitCapture(
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
        ocr_provider=lambda image, roi: calls.append((image, roi))
        or (RecognizedLine("测试成功", 0.1, 0.5, 0.4, 0.1),),
    )
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)

    assert capture.recognize(frame) == ("测试成功", None)
    assert calls == [("image", KIM_COMPOSER_ROI)]


def test_recognize_rejects_empty_and_uncommitted_doubao_text():
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    empty = KimPreSubmitCapture(
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
        ocr_provider=lambda image, roi: (),
    )
    pinyin = KimPreSubmitCapture(
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
        ocr_provider=lambda image, roi: (
            RecognizedLine("ce'shi", 0.1, 0.5, 0.4, 0.1),
        ),
    )

    assert empty.recognize(frame) == ("", "kim_ocr_empty")
    assert pinyin.recognize(frame) == ("", "kim_ocr_uncommitted_text")


def test_recognize_reports_native_failure_without_content():
    def fail_ocr(image, roi):
        raise RuntimeError("vision failed")

    capture = KimPreSubmitCapture(ocr_provider=fail_ocr)

    assert capture.recognize(
        CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    ) == (
        "",
        "kim_ocr_native_error",
    )


def test_recognize_uses_input_source_captured_with_frame():
    current_source = [DOUBAO_BUNDLE_ID]
    capture = KimPreSubmitCapture(
        input_source_provider=lambda: current_source[0],
        ocr_provider=lambda image, roi: (
            RecognizedLine("nihao", 0.1, 0.5, 0.3, 0.1),
        ),
    )
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    current_source[0] = "com.apple.keylayout.ABC"

    assert capture.recognize(frame) == ("", "kim_ocr_uncommitted_text")


def test_recognize_rejects_multiline_or_edge_clipped_text():
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    multiline = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("第一行", 0.1, 0.8, 0.3, 0.1),
            RecognizedLine("第二行", 0.1, 0.2, 0.3, 0.1),
        )
    )
    clipped = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("可能被截断", 0.1, 0.01, 0.4, 0.1),
        )
    )

    assert multiline.recognize(frame) == ("", "kim_ocr_multiline_untrusted")
    assert clipped.recognize(frame) == ("", "kim_ocr_edge_clipped")
