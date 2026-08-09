"""Local pre-submit text recovery for the legacy Kim desktop client."""

from dataclasses import dataclass


DOUBAO_BUNDLE_ID = "com.bytedance.inputmethod.doubaoime"
MAX_OCR_TEXT_CHARS = 4000
KIM_CHROME_LABELS = frozenset(
    {
        "↩︎ 发送 / ⌘↩︎ 换行",
        "↩ 发送 / ⌘↩ 换行",
    }
)


@dataclass(frozen=True)
class RecognizedLine:
    text: str
    x: float
    y: float
    width: float
    height: float


def assemble_recognized_text(lines) -> str:
    """Order Vision observations into bounded plain text."""
    usable = [
        line
        for line in lines
        if line.text.strip() and line.text.strip() not in KIM_CHROME_LABELS
    ]
    usable.sort(key=lambda line: (-(line.y + line.height / 2), line.x))

    rows: list[list[RecognizedLine]] = []
    for line in usable:
        if not rows:
            rows.append([line])
            continue
        previous = rows[-1]
        previous_center = sum(
            item.y + item.height / 2 for item in previous
        ) / len(previous)
        line_center = line.y + line.height / 2
        row_height = max(item.height for item in previous)
        if abs(previous_center - line_center) <= max(row_height, line.height) * 0.6:
            previous.append(line)
        else:
            rows.append([line])

    text = "\n".join(
        " ".join(item.text.strip() for item in sorted(row, key=lambda item: item.x))
        for row in rows
    )
    return text[:MAX_OCR_TEXT_CHARS]


def ocr_text_is_trusted(text: str, input_source_bundle_id: str) -> bool:
    """Reject raw Doubao pre-edit text while accepting committed CJK."""
    if not isinstance(text, str) or not text.strip():
        return False
    if input_source_bundle_id != DOUBAO_BUNDLE_ID:
        return True
    return any(
        "\u3400" <= character <= "\u4dbf"
        or "\u4e00" <= character <= "\u9fff"
        or "\uf900" <= character <= "\ufaff"
        for character in text
    )
