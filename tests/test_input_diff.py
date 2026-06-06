from ominime.input_diff import extract_inserted_text


def test_extract_inserted_text_append():
    assert extract_inserted_text("hello", "hello你好") == "你好"


def test_extract_inserted_text_middle_insert():
    assert extract_inserted_text("hello world", "hello 豆包 world") == "豆包 "


def test_extract_inserted_text_replacement_returns_new_text():
    assert extract_inserted_text("prefix old suffix", "prefix 新内容 suffix") == "新内容"


def test_extract_inserted_text_ignores_deletions():
    assert extract_inserted_text("hello", "hell") == ""


def test_extract_inserted_text_shorter_replacement_returns_new_text():
    assert extract_inserted_text("prefix old text suffix", "prefix 新 suffix") == "新"
