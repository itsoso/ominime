from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_only_one_menu_bar_implementation_remains():
    main = (ROOT / "src/ominime/main.py").read_text(encoding="utf-8")
    menu_app = (ROOT / "src/ominime/menu_bar_app.py").read_text(encoding="utf-8")

    assert not (ROOT / "src/ominime/menu_bar.py").exists()
    assert "from .menu_bar import" not in main
    assert "AppTracker" not in menu_app


def test_unused_input_diff_and_app_tracker_modules_are_removed():
    assert not (ROOT / "src/ominime/input_diff.py").exists()
    assert not (ROOT / "src/ominime/app_tracker.py").exists()


def test_production_listener_constructs_local_chat_captures():
    source = (ROOT / "src/ominime/keyboard_listener.py").read_text(encoding="utf-8")

    assert "kim_composer_capture or KimPreSubmitCapture()" in source
    assert "wechat_composer_capture or WeChatPreSubmitCapture()" in source
