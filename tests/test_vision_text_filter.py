from ominime.kim_composer_capture import RecognizedLine, recognized_content_lines


def test_recognized_content_lines_removes_tiled_slanted_watermark_variants():
    lines = (
        RecognizedLine("panbaokun", 0.31, 0.15, 0.05, 0.03, slant_ratio=1.5),
        RecognizedLine("panbaokun", 0.46, 0.15, 0.05, 0.03, slant_ratio=1.5),
        RecognizedLine("panbaokun", 0.31, 0.09, 0.05, 0.03, slant_ratio=1.5),
        RecognizedLine("panbaokun", 0.46, 0.09, 0.05, 0.03, slant_ratio=1.5),
        RecognizedLine("panbaoku", 0.72, 0.15, 0.05, 0.03, slant_ratio=1.5),
        RecognizedLine("最终文本", 0.70, 0.30, 0.18, 0.04),
    )

    assert [line.text for line in recognized_content_lines(lines)] == ["最终文本"]


def test_recognized_content_lines_removes_sparse_slanted_latin_watermark():
    lines = (
        RecognizedLine("watermark", 0.12, 0.15, 0.10, 0.03, slant_ratio=0.8),
        RecognizedLine("hello 123", 0.70, 0.30, 0.18, 0.04),
    )

    assert [line.text for line in recognized_content_lines(lines)] == ["hello 123"]


def test_recognized_content_lines_keeps_repeated_words_in_one_visual_row():
    lines = (
        RecognizedLine("test test", 0.70, 0.30, 0.18, 0.04),
        RecognizedLine("第二行", 0.72, 0.24, 0.16, 0.04),
    )

    assert [line.text for line in recognized_content_lines(lines)] == [
        "test test",
        "第二行",
    ]
