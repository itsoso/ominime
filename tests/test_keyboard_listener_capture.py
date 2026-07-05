import importlib
import sys
import time
import types
from types import SimpleNamespace


def import_keyboard_listener(monkeypatch):
    quartz = types.ModuleType("Quartz")
    quartz.kCGEventKeyDown = 1
    quartz.kCGEventKeyUp = 2
    quartz.kCGEventFlagsChanged = 3
    quartz.kCGKeyboardEventKeycode = 4
    quartz.kCGSessionEventTap = 5
    quartz.kCGHeadInsertEventTap = 6
    quartz.kCGEventFlagMaskShift = 1 << 17
    quartz.kCGEventFlagMaskControl = 1 << 18
    quartz.kCGEventFlagMaskAlternate = 1 << 19
    quartz.kCGEventFlagMaskCommand = 1 << 20
    quartz.kCFRunLoopDefaultMode = "default"

    for name in (
        "CGEventTapEnable",
        "CGEventTapIsEnabled",
        "CFMachPortIsValid",
        "CFMachPortCreateRunLoopSource",
        "CFRunLoopAddSource",
        "CFRunLoopRemoveSource",
        "CFRunLoopGetCurrent",
        "CFRunLoopRun",
        "CFRunLoopStop",
        "CFRunLoopRunInMode",
        "CGEventGetFlags",
    ):
        setattr(quartz, name, lambda *args, **kwargs: None)
    quartz.CGEventGetFlags = lambda event: getattr(event, "flags", 0)

    captured = {}

    def fake_event_tap_create(*args):
        captured["event_mask"] = args[3]
        return object()

    quartz.CGEventTapCreate = fake_event_tap_create
    quartz.CGEventGetIntegerValueField = lambda event, field: getattr(event, "keycode", 0)
    quartz.CGEventKeyboardGetUnicodeString = (
        lambda event, max_length, actual_length, chars: (
            len(getattr(event, "text", "")),
            getattr(event, "text", ""),
        )
    )
    monkeypatch.setitem(sys.modules, "Quartz", quartz)

    appkit = types.ModuleType("AppKit")
    appkit.NSWorkspace = SimpleNamespace(sharedWorkspace=lambda: None)
    appkit.NSRunningApplication = SimpleNamespace
    monkeypatch.setitem(sys.modules, "AppKit", appkit)

    foundation = types.ModuleType("Foundation")
    foundation.NSObject = object
    foundation.NSRunLoop = SimpleNamespace
    foundation.NSDefaultRunLoopMode = "NSDefaultRunLoopMode"
    foundation.NSDistributedNotificationCenter = SimpleNamespace
    monkeypatch.setitem(sys.modules, "Foundation", foundation)

    objc = types.ModuleType("objc")
    objc.selector = lambda value, signature=None: value
    monkeypatch.setitem(sys.modules, "objc", objc)

    sys.modules.pop("ominime.keyboard_listener", None)
    module = importlib.import_module("ominime.keyboard_listener")
    return module, captured


def test_event_tap_listens_to_keydown_keyup_and_flags_changed(monkeypatch):
    keyboard_listener, captured = import_keyboard_listener(monkeypatch)

    listener = keyboard_listener.KeyboardListener(lambda event: None)
    assert listener._create_event_tap()

    assert captured["event_mask"] == (
        (1 << keyboard_listener.kCGEventKeyDown)
        | (1 << keyboard_listener.kCGEventKeyUp)
        | (1 << keyboard_listener.kCGEventFlagsChanged)
    )


def test_enter_keyup_can_emit_submission_snapshot(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: "需要被记录"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyUp,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "需要被记录"
    assert events[0].modifiers["submit_snapshot"] is True


def test_enter_emits_count_only_fallback_by_default_when_ax_value_is_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=12),  # q
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=13),  # w
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE),
        None,
    )

    assert len(events) == 1
    assert events[0].character == keyboard_listener.UNREADABLE_SUBMISSION_PLACEHOLDER
    assert events[0].modifiers["fallback_source"] == "count_unreadable"
    assert events[0].modifiers["redacted_content"] is True
    assert events[0].modifiers["char_count_override"] == 2


def test_enter_does_not_emit_pinyin_key_event_text_fallback_when_ax_value_is_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    for event in (
        SimpleNamespace(keycode=12, text="p"),
        SimpleNamespace(keycode=34, text="i"),
        SimpleNamespace(keycode=45, text="n"),
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
    ):
        listener._event_callback(None, keyboard_listener.kCGEventKeyDown, event, None)

    assert events == []


def test_enter_uses_recent_ax_snapshot_when_enter_snapshot_is_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    listener._recent_text_snapshots = {
        ("Codex", "com.openai.codex"): ("你好", time.monotonic())
    }
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "你好"
    assert events[0].modifiers["fallback_source"] == "recent_ax_snapshot"


def test_backspace_keyup_clears_recent_ax_snapshot_when_field_becomes_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    listener._recent_text_snapshots = {
        ("Codex", "com.openai.codex"): ("旧内容", time.monotonic())
    }
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyUp,
        SimpleNamespace(keycode=51, text=""),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []


def test_enter_uses_cjk_key_event_text_fallback_by_default_when_ax_value_is_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=12, text="你"),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=13, text="好"),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "你好"
    assert events[0].modifiers["submit_snapshot"] is True
    assert events[0].modifiers["fallback_source"] == "key_event_text"
    assert events[0].modifiers["redacted_content"] is False
    assert "char_count_override" not in events[0].modifiers


def test_key_event_text_fallback_captures_committed_cjk_from_keyup(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyUp,
        SimpleNamespace(keycode=49, text="你好"),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "你好"
    assert events[0].modifiers["fallback_source"] == "key_event_text"


def test_cjk_key_event_fallback_preferred_over_latin_ax_snapshot(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: "nihao"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyUp,
        SimpleNamespace(keycode=49, text="你好"),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "你好"
    assert events[0].modifiers["fallback_source"] == "key_event_text"


def test_enter_uses_clipboard_copy_fallback_after_recent_input_when_ax_and_key_text_are_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Kim", "Kem")
    listener._get_focused_text_snapshot = lambda: ""
    listener._copy_focused_submission_via_clipboard = lambda app_name, bundle_id, fallback_count=0: "今天记录中文"
    listener._can_use_clipboard_copy_fallback = lambda: True
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=49, text=" "),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "今天记录中文"
    assert events[0].modifiers["fallback_source"] == "clipboard_copy"
    assert events[0].modifiers["redacted_content"] is False


def test_enter_without_recent_input_does_not_use_clipboard_copy_fallback(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    copy_calls = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: ""
    listener._can_use_clipboard_copy_fallback = lambda: True
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )

    def copy_fallback(app_name, bundle_id, fallback_count=0):
        copy_calls.append((app_name, bundle_id, fallback_count))
        return "whole conversation copied"

    listener._copy_focused_submission_via_clipboard = copy_fallback
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert copy_calls == []


def test_clipboard_copy_fallback_wins_over_count_only_fallback(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Kim", "Kem")
    listener._get_focused_text_snapshot = lambda: ""
    listener._copy_focused_submission_via_clipboard = lambda app_name, bundle_id, fallback_count=0: "输入框原文"
    listener._can_use_clipboard_copy_fallback = lambda: True
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=49, text=" "),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "输入框原文"
    assert events[0].modifiers["fallback_source"] == "clipboard_copy"
    assert events[0].modifiers["redacted_content"] is False
    assert "char_count_override" not in events[0].modifiers


def test_rejected_clipboard_copy_does_not_fall_back_to_count_only(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    copy_calls = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: ""
    listener._can_use_clipboard_copy_fallback = lambda: True

    def copy_fallback(app_name, bundle_id, fallback_count=0):
        copy_calls.append((app_name, bundle_id, fallback_count))
        return ""

    listener._copy_focused_submission_via_clipboard = copy_fallback
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=49, text=" "),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert copy_calls == [("Claude", "com.anthropic.claudefordesktop", 1)]


def test_latin_ime_commit_enter_does_not_copy_or_emit_until_next_enter(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    copy_calls = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Kim", "Kem")
    listener._get_focused_text_snapshot = lambda: ""
    listener._can_use_clipboard_copy_fallback = lambda: True
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )

    def copy_fallback(app_name, bundle_id, fallback_count=0):
        copy_calls.append((app_name, bundle_id, fallback_count))
        return "mixed English"

    listener._copy_focused_submission_via_clipboard = copy_fallback
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    for event in (
        SimpleNamespace(keycode=46, text="m"),
        SimpleNamespace(keycode=34, text="i"),
        SimpleNamespace(keycode=6, text="x"),
    ):
        listener._event_callback(None, keyboard_listener.kCGEventKeyDown, event, None)

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyUp,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert copy_calls == []

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "mixed English"
    assert events[0].modifiers["fallback_source"] == "clipboard_copy"
    assert copy_calls == [("Kim", "Kem", 3)]


def test_latin_ime_clipboard_allowance_bounds_copied_content(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: ""
    listener._can_use_clipboard_copy_fallback = lambda: True
    listener._snapshot_general_pasteboard = lambda: None
    listener._restore_general_pasteboard = lambda snapshot: None
    listener._post_command_key = lambda keycode: True
    listener._post_plain_key = lambda keycode: True
    listener._read_general_pasteboard_text = lambda: "x" * 1000
    monkeypatch.setattr(keyboard_listener.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    for event in (
        SimpleNamespace(keycode=46, text="m"),
        SimpleNamespace(keycode=34, text="i"),
        SimpleNamespace(keycode=6, text="x"),
    ):
        listener._event_callback(None, keyboard_listener.kCGEventKeyDown, event, None)

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyUp,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []


def test_key_event_text_fallback_drops_pinyin_prefix_before_committed_cjk(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    for event in (
        SimpleNamespace(keycode=12, text="p"),
        SimpleNamespace(keycode=34, text="i"),
        SimpleNamespace(keycode=45, text="n"),
        SimpleNamespace(keycode=12, text="你"),
        SimpleNamespace(keycode=13, text="好"),
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
    ):
        listener._event_callback(None, keyboard_listener.kCGEventKeyDown, event, None)

    assert len(events) == 1
    assert events[0].character == "你好"


def test_key_event_text_fallback_handles_backspace(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener.config,
        "capture_key_event_text_fallback",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    for event in (
        SimpleNamespace(keycode=0, text="你"),
        SimpleNamespace(keycode=11, text="好"),
        SimpleNamespace(keycode=51, text=""),
        SimpleNamespace(keycode=8, text="吗"),
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
    ):
        listener._event_callback(None, keyboard_listener.kCGEventKeyDown, event, None)

    assert len(events) == 1
    assert events[0].character == "你吗"


def test_enter_does_not_emit_count_only_fallback_when_disabled(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=12),  # q
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=13),  # w
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE),
        None,
    )

    assert events == []
