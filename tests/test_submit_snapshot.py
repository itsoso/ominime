from ominime.input_snapshot import (
    format_submission_terminal_notice,
    normalize_submission_text,
    should_save_submission_snapshot,
)


def test_normalize_submission_text_keeps_full_content():
    text = "第一行\n第二行\n"
    assert normalize_submission_text(text) == text


def test_normalize_terminal_snapshot_keeps_only_last_non_empty_line():
    text = "Last login: Sun May 31\nbuild output\n\n➜  ominime git status"

    assert (
        normalize_submission_text(
            text,
            app_name="Terminal",
            bundle_id="com.apple.Terminal",
        )
        == "➜  ominime git status"
    )


def test_normalize_terminal_snapshot_skips_oversized_command_line():
    text = "old output\n" + "x" * 600

    assert (
        normalize_submission_text(
            text,
            app_name="iTerm",
            bundle_id="com.googlecode.iterm2",
        )
        == ""
    )


def test_normalize_submission_text_ignores_blank_content():
    assert normalize_submission_text("  \n\t  ") == ""


def test_normalize_submission_text_ignores_browser_location_history_suggestion():
    text = "快手差旅 https://smart-travel.example.com location from history，依次按 Tab 键即可移除建议。"

    assert (
        normalize_submission_text(
            text,
            app_name="Google Chrome",
            bundle_id="com.google.Chrome",
        )
        == ""
    )


def test_should_save_submission_snapshot_rejects_immediate_duplicate():
    current = ("Codex", "com.openai.codex", "完整输入内容")
    previous = ("Codex", "com.openai.codex", "完整输入内容", 100.0)
    assert not should_save_submission_snapshot(current, previous, now=100.3, debounce_seconds=0.8)


def test_should_save_submission_snapshot_allows_changed_content():
    current = ("Codex", "com.openai.codex", "新的完整输入内容")
    previous = ("Codex", "com.openai.codex", "完整输入内容", 100.0)
    assert should_save_submission_snapshot(current, previous, now=100.3, debounce_seconds=0.8)


def test_format_submission_terminal_notice_omits_raw_content():
    raw_content = "this is a long private prompt that should not be echoed"
    notice = format_submission_terminal_notice(raw_content)
    assert "private prompt" not in notice
    assert str(len(raw_content)) in notice
