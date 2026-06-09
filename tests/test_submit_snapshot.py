from ominime.input_snapshot import normalize_submission_text, should_save_submission_snapshot


def test_normalize_submission_text_keeps_full_content():
    text = "第一行\n第二行\n"
    assert normalize_submission_text(text) == text


def test_normalize_submission_text_ignores_blank_content():
    assert normalize_submission_text("  \n\t  ") == ""


def test_should_save_submission_snapshot_rejects_immediate_duplicate():
    current = ("Codex", "com.openai.codex", "完整输入内容")
    previous = ("Codex", "com.openai.codex", "完整输入内容", 100.0)
    assert not should_save_submission_snapshot(current, previous, now=100.3, debounce_seconds=0.8)


def test_should_save_submission_snapshot_allows_changed_content():
    current = ("Codex", "com.openai.codex", "新的完整输入内容")
    previous = ("Codex", "com.openai.codex", "完整输入内容", 100.0)
    assert should_save_submission_snapshot(current, previous, now=100.3, debounce_seconds=0.8)
