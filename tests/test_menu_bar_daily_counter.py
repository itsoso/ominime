from datetime import date, datetime
from types import SimpleNamespace
import importlib
import sys
import types

import pytest
from ominime import runtime_state


@pytest.fixture(autouse=True)
def reset_runtime_state():
    runtime_state.reset_runtime_state()
    yield
    runtime_state.reset_runtime_state()


def install_menu_bar_import_stubs(monkeypatch):
    rumps = types.ModuleType("rumps")

    class App:
        pass

    rumps.App = App
    rumps.MenuItem = lambda *args, **kwargs: SimpleNamespace(set_callback=lambda callback: None)
    rumps.Timer = lambda *args, **kwargs: SimpleNamespace(start=lambda: None, stop=lambda: None)
    rumps.notification = lambda *args, **kwargs: None
    rumps.alert = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "rumps", rumps)

    quartz = types.ModuleType("Quartz")
    for name in (
        "CGEventTapCreate",
        "CGEventTapEnable",
        "CGEventTapIsEnabled",
        "CFMachPortIsValid",
        "CGEventGetIntegerValueField",
        "CFMachPortCreateRunLoopSource",
        "CFRunLoopAddSource",
        "CFRunLoopRemoveSource",
        "CFRunLoopGetCurrent",
        "CFRunLoopRun",
        "CFRunLoopStop",
        "CGEventGetFlags",
    ):
        setattr(quartz, name, lambda *args, **kwargs: None)
    for name in (
        "kCGSessionEventTap",
        "kCGHeadInsertEventTap",
        "kCGEventKeyDown",
        "kCGEventKeyUp",
        "kCGEventFlagsChanged",
        "kCGKeyboardEventKeycode",
        "kCGEventFlagMaskShift",
        "kCGEventFlagMaskControl",
        "kCGEventFlagMaskAlternate",
        "kCGEventFlagMaskCommand",
    ):
        setattr(quartz, name, 0)
    monkeypatch.setitem(sys.modules, "Quartz", quartz)

    appkit = types.ModuleType("AppKit")
    appkit.NSWorkspace = SimpleNamespace(sharedWorkspace=lambda: None)
    appkit.NSRunningApplication = SimpleNamespace
    appkit.NSWorkspaceDidActivateApplicationNotification = (
        "NSWorkspaceDidActivateApplicationNotification"
    )
    monkeypatch.setitem(sys.modules, "AppKit", appkit)

    foundation = types.ModuleType("Foundation")
    foundation.NSObject = object
    foundation.NSRunLoop = SimpleNamespace
    foundation.NSDefaultRunLoopMode = "NSDefaultRunLoopMode"
    foundation.NSDistributedNotificationCenter = SimpleNamespace
    foundation.NSNotificationCenter = SimpleNamespace(defaultCenter=lambda: None)
    monkeypatch.setitem(sys.modules, "Foundation", foundation)

    monkeypatch.setitem(sys.modules, "objc", types.ModuleType("objc"))


class FakeDb:
    def __init__(self, today_total):
        self.today_total = today_total

    def get_total_chars_today(self):
        return self.today_total


def make_submit_event(
    content,
    app_name="Codex",
    app_bundle_id="com.openai.codex",
):
    return SimpleNamespace(
        timestamp=datetime(2026, 6, 17, 0, 0, 1),
        keycode=36,
        character=content,
        app_name=app_name,
        app_bundle_id=app_bundle_id,
        modifiers={"submit_snapshot": True},
    )


def test_full_menu_bar_refreshes_today_total_after_submission(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=5)
    app._today_chars = 1_420_000
    app._last_submission_snapshot = None

    app._save_submission_snapshot = lambda event, content: None
    app._update_title = lambda *args, **kwargs: None

    app._on_key_event(make_submit_event("hello"))

    assert app._today_chars == 5


def test_full_menu_bar_rolls_title_counter_when_day_changes(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    monkeypatch.setattr(menu_bar_app, "business_today", lambda: date(2026, 6, 27))

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=0)
    app._is_recording = True
    app._today_chars = 4_997
    app._today_date = date(2026, 6, 26)
    app._last_title_update = 0

    app._update_title(force=True)

    assert app._today_date == date(2026, 6, 27)
    assert app._today_chars == 0
    assert app.title == "⌨️ 0"


def test_full_menu_bar_start_updates_runtime_recording_state(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    runtime_state.reset_runtime_state()

    class FakeListener:
        def __init__(self, callback):
            self.callback = callback
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr(menu_bar_app, "KeyboardListener", FakeListener)

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=8)
    app._is_recording = False
    app._last_title_update = 0
    app._update_title = lambda *args, **kwargs: None
    app._recording_toggle_item = SimpleNamespace(title="▶️ 开始记录")

    app._start_recording_internal()

    state = runtime_state.get_runtime_state()
    assert app._is_recording is True
    assert app._recording_toggle_item.title == "⏸️ 暂停记录"
    assert state.recording_status == "recording"
    assert state.is_recording is True


def test_full_menu_bar_shows_permission_warning_when_auto_start_cannot_record(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    runtime_state.reset_runtime_state()
    monkeypatch.setattr(menu_bar_app, "check_accessibility_permission", lambda: False)

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.title = "⌨️"
    app._is_recording = False
    app._start_recording_internal = lambda: pytest.fail("recording should not start")

    app._auto_start_recording()

    state = runtime_state.get_runtime_state()
    assert app._is_recording is False
    assert app.title == "⌨️ ⚠"
    assert state.recording_status == "permission_missing"
    assert state.is_recording is False


def test_full_menu_bar_saves_only_terminal_command_line(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=12)
    app._today_chars = 0
    app._last_submission_snapshot = None
    saved = []

    app._save_submission_snapshot = lambda event, content: saved.append(content)
    app._update_title = lambda *args, **kwargs: None

    app._on_key_event(
        make_submit_event(
            "old terminal output\nanother log line\n\n➜  ominime pytest",
            app_name="Terminal",
            app_bundle_id="com.apple.Terminal",
        )
    )

    assert saved == ["➜  ominime pytest"]
    assert app._today_chars == 12


def test_legacy_menu_bar_refreshes_today_total_after_submission(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")

    app = object.__new__(menu_bar.OmniMeApp)
    app.db = FakeDb(today_total=5)
    app._today_chars = 1_420_000
    app._last_submission_snapshot = None

    app._save_submission_snapshot = lambda event, content: None
    app._update_title = lambda: None

    app._on_key_event(make_submit_event("hello"))

    assert app._today_chars == 5


def test_legacy_menu_bar_rolls_title_counter_when_day_changes(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")
    monkeypatch.setattr(menu_bar, "business_today", lambda: date(2026, 6, 27))

    app = object.__new__(menu_bar.OmniMeApp)
    app.db = FakeDb(today_total=0)
    app._is_recording = True
    app._today_chars = 4_997
    app._today_date = date(2026, 6, 26)

    app._update_title()

    assert app._today_date == date(2026, 6, 27)
    assert app._today_chars == 0
    assert app.title == "⌨️ 0"


def test_legacy_menu_bar_shows_permission_warning_when_start_fails(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")
    runtime_state.reset_runtime_state()
    monkeypatch.setattr(menu_bar, "check_accessibility_permission", lambda: False)
    monkeypatch.setattr(menu_bar, "request_accessibility_permission", lambda: None)

    app = object.__new__(menu_bar.OmniMeApp)
    app.title = "⌨️"
    app._is_recording = False
    sender = SimpleNamespace(title="▶️ 开始记录")

    app._start_recording(sender)

    state = runtime_state.get_runtime_state()
    assert app._is_recording is False
    assert app.title == "⌨️ ⚠"
    assert sender.title == "▶️ 开始记录"
    assert state.recording_status == "permission_missing"
    assert state.is_recording is False
