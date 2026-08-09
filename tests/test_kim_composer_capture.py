from ominime.kim_composer_capture import (
    DOUBAO_BUNDLE_ID,
    RecognizedLine,
    assemble_recognized_text,
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
        RecognizedLine(
            "↩︎ 发送 / ⌘↩︎ 换行",
            x=0.1,
            y=0.5,
            width=0.5,
            height=0.1,
        ),
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


def test_non_doubao_ocr_accepts_nonempty_latin_text():
    assert ocr_text_is_trusted("hello", "com.apple.keylayout.ABC")
    assert not ocr_text_is_trusted("  ", "com.apple.keylayout.ABC")
