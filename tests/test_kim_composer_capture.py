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


def test_assemble_recognized_text_ignores_tiled_watermarks():
    lines = (
        RecognizedLine(
            "panbaokun", x=0.31, y=0.15, width=0.05, height=0.03,
            slant_ratio=1.5,
        ),
        RecognizedLine(
            "panbaokun", x=0.46, y=0.15, width=0.05, height=0.03,
            slant_ratio=1.5,
        ),
        RecognizedLine(
            "panbaokun", x=0.31, y=0.09, width=0.05, height=0.03,
            slant_ratio=1.5,
        ),
        RecognizedLine(
            "panbaokun", x=0.46, y=0.09, width=0.05, height=0.03,
            slant_ratio=1.5,
        ),
        RecognizedLine(
            "panbaoku", x=0.72, y=0.15, width=0.05, height=0.03,
            slant_ratio=1.5,
        ),
        RecognizedLine("测试", x=0.32, y=0.12, width=0.08, height=0.03),
    )

    assert assemble_recognized_text(lines) == "测试"


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
    assert ocr_text_matches_physical_count("Kim稀疏水印0810", 1)
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


def test_prepare_selects_frontmost_eligible_window_for_target_pid():
    selected = []
    capture = KimPreSubmitCapture(
        window_provider=lambda: (
            WindowInfo(7, 123, 0, 800, 600),
            WindowInfo(8, 123, 0, 1400, 1000),
        ),
        image_provider=lambda window_id: selected.append(window_id) or "image",
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
    )

    assert capture.prepare(123)
    assert capture.freeze(123) is not None
    assert selected == [7]


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


def test_failed_or_expired_window_cache_can_be_prepared_again():
    now = [0.0]
    window_id = [1]
    capture = KimPreSubmitCapture(
        clock=lambda: now[0],
        window_provider=lambda: (
            WindowInfo(window_id[0], 123, 0, 1197, 925),
        ),
        image_provider=lambda selected_id: (
            None if selected_id == 1 else f"image-{selected_id}"
        ),
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
    )

    assert capture.prepare(123)
    assert capture.freeze(123) is None
    window_id[0] = 2
    assert capture.prepare(123)
    assert capture.freeze(123).image == "image-2"

    now[0] = 10.0
    assert capture.freeze(123).image == "image-2"
    window_id[0] = 3
    assert capture.prepare(123)
    assert capture.freeze(123).image == "image-3"


def test_recognize_uses_kim_roi_and_returns_trusted_text():
    calls = []
    capture = KimPreSubmitCapture(
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
        ocr_provider=lambda image, roi: calls.append((image, roi))
        or (RecognizedLine("测试成功", 0.31, 0.10, 0.2, 0.02),),
    )
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)

    assert capture.recognize(frame) == ("测试成功", None)
    assert calls == [("image", KIM_COMPOSER_ROI)]


def test_recognize_ignores_tiled_watermarks_at_roi_edges():
    capture = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine(
                "Kim缓存验收0810",
                0.31003,
                0.155,
                0.1085,
                0.01821,
            ),
            RecognizedLine(
                "panbaokun", 0.29652, 0.09781, 0.04825, 0.02757, 1.5
            ),
            RecognizedLine(
                "panbaokun", 0.40718, 0.09532, 0.04924, 0.03107, 1.5
            ),
            RecognizedLine(
                "panbaokun", 0.46276, 0.14555, 0.04927, 0.03168, 1.5
            ),
            RecognizedLine(
                "panbaokun", 0.68502, 0.14568, 0.05008, 0.03171, 1.5
            ),
            RecognizedLine(
                "panbaoku", 0.7971, 0.14643, 0.0439, 0.0285, 1.5
            ),
        ),
    )
    frame = CapturedFrame(
        "image",
        29805,
        1197,
        925,
        12.5,
        DOUBAO_BUNDLE_ID,
    )

    assert capture.recognize(frame) == ("Kim缓存验收0810", None)


def test_recognize_rejects_empty_and_uncommitted_doubao_text():
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    empty = KimPreSubmitCapture(
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
        ocr_provider=lambda image, roi: (),
    )
    pinyin = KimPreSubmitCapture(
        input_source_provider=lambda: DOUBAO_BUNDLE_ID,
        ocr_provider=lambda image, roi: (
            RecognizedLine("ce'shi", 0.31, 0.10, 0.2, 0.02),
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
            RecognizedLine("nihao", 0.31, 0.10, 0.2, 0.02),
        ),
    )
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    current_source[0] = "com.apple.keylayout.ABC"

    assert capture.recognize(frame) == ("", "kim_ocr_uncommitted_text")


def test_recognize_rejects_multiline_or_edge_clipped_text():
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    multiline = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("第一行", 0.31, 0.14, 0.2, 0.02),
            RecognizedLine("第二行", 0.31, 0.08, 0.2, 0.02),
        )
    )
    bottom_clipped = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("底部被截断", 0.31, 0.051, 0.2, 0.02),
        )
    )
    top_clipped = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("顶部被截断", 0.31, 0.164, 0.2, 0.02),
        )
    )

    assert multiline.recognize(frame) == ("", "kim_ocr_multiline_untrusted")
    assert bottom_clipped.recognize(frame) == ("", "kim_ocr_edge_clipped")
    assert top_clipped.recognize(frame) == ("", "kim_ocr_edge_clipped")


def test_recognize_does_not_treat_repeated_horizontal_text_as_watermark():
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    capture = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("测试", 0.31, 0.15, 0.05, 0.02),
            RecognizedLine("测试", 0.46, 0.15, 0.05, 0.02),
            RecognizedLine("测试", 0.31, 0.09, 0.05, 0.02),
            RecognizedLine("测试", 0.46, 0.09, 0.05, 0.02),
            RecognizedLine("提交", 0.32, 0.12, 0.08, 0.02),
        )
    )

    assert capture.recognize(frame) == ("", "kim_ocr_multiline_untrusted")


def test_recognize_keeps_horizontal_prefix_of_slanted_watermark():
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    capture = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("panbaokun", 0.31, 0.15, 0.05, 0.02, 1.5),
            RecognizedLine("panbaokun", 0.46, 0.15, 0.05, 0.02, 1.5),
            RecognizedLine("panbaokun", 0.31, 0.09, 0.05, 0.02, 1.5),
            RecognizedLine("panbaokun", 0.46, 0.09, 0.05, 0.02, 1.5),
            RecognizedLine("panbaoku", 0.32, 0.13, 0.08, 0.02, 0.0),
            RecognizedLine("提交", 0.32, 0.11, 0.08, 0.02, 0.0),
        )
    )

    assert capture.recognize(frame) == ("", "kim_ocr_multiline_untrusted")


def test_recognize_filters_sparse_slanted_latin_watermarks_near_edges():
    frame = CapturedFrame("image", 123, 1197, 925, 12.5, DOUBAO_BUNDLE_ID)
    capture = KimPreSubmitCapture(
        ocr_provider=lambda image, roi: (
            RecognizedLine("Kim动态诊断0810", 0.31, 0.155, 0.14, 0.018, 0.02),
            RecognizedLine("panbaokun", 0.296, 0.097, 0.049, 0.029, 1.54),
            RecognizedLine("panbaokun", 0.463, 0.145, 0.049, 0.032, 1.82),
            RecognizedLine("panbaoku", 0.797, 0.146, 0.044, 0.029, 1.74),
        )
    )

    assert capture.recognize(frame) == ("Kim动态诊断0810", None)
