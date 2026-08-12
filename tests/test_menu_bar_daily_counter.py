from datetime import date, datetime
from types import SimpleNamespace
import importlib
import sys
import types

import pytest
from ominime import runtime_state


@pytest.fixture(autouse=True)
def reset_runtime_state(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime_state, "_state_file_path", tmp_path / "runtime-state.json")
    runtime_state.reset_runtime_state()
    yield
    runtime_state.reset_runtime_state()


def install_menu_bar_import_stubs(monkeypatch):
    rumps = types.ModuleType("rumps")

    class App:
        def __init__(self, *args, **kwargs):
            self.title = kwargs.get("title")

    rumps.App = App
    rumps.MenuItem = lambda *args, **kwargs: SimpleNamespace(set_callback=lambda callback: None)
    rumps.Timer = lambda *args, **kwargs: SimpleNamespace(start=lambda: None, stop=lambda: None)
    rumps.notification = lambda *args, **kwargs: None
    rumps.alert = lambda *args, **kwargs: None
    rumps.quit_application = lambda: None
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
        "kCGEventLeftMouseDown",
        "kCGEventRightMouseDown",
        "kCGEventOtherMouseDown",
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
    def __init__(self, today_total, storage_total=None):
        self.today_total = today_total
        self.storage_total = storage_total

    def get_total_chars_today(self):
        return self.today_total

    def get_total_chars_for_storage_date(self, target_date):
        return self.today_total if self.storage_total is None else self.storage_total


class FakeTimer:
    def __init__(self, callback, interval):
        self.callback = callback
        self.interval = interval
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


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


def test_full_menu_bar_refreshes_input_source_on_main_timer(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    refresh_calls = []
    timers = []

    def make_timer(callback, interval):
        timer = FakeTimer(callback, interval)
        timers.append(timer)
        return timer

    monkeypatch.setattr(menu_bar_app.rumps, "Timer", make_timer)
    monkeypatch.setattr(
        menu_bar_app,
        "refresh_input_source_cache",
        lambda: refresh_calls.append(True),
        raising=False,
    )
    monkeypatch.setattr(menu_bar_app, "AppTracker", lambda: SimpleNamespace())
    monkeypatch.setattr(menu_bar_app, "get_database", lambda: FakeDb(0))
    monkeypatch.setattr(menu_bar_app, "set_recording_status", lambda status: None)
    monkeypatch.setattr(menu_bar_app.OmniMeMenuBarApp, "_build_menu", lambda self: None)
    monkeypatch.setattr(
        menu_bar_app.threading,
        "Thread",
        lambda *args, **kwargs: SimpleNamespace(start=lambda: None),
    )

    app = menu_bar_app.OmniMeMenuBarApp()

    assert refresh_calls == [True]
    assert len(timers) == 2
    assert app._input_source_timer.interval == 0.25
    assert app._input_source_timer.started

    app._input_source_timer.callback(None)

    assert refresh_calls == [True, True]


def test_full_menu_bar_quit_stops_all_timers(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    quit_calls = []
    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.listener = None
    app._stats_timer = FakeTimer(lambda _: None, 60)
    app._input_source_timer = FakeTimer(lambda _: None, 0.25)
    monkeypatch.setattr(
        menu_bar_app.rumps,
        "quit_application",
        lambda: quit_calls.append(True),
    )

    app._quit(None)

    assert app._stats_timer.stopped
    assert app._input_source_timer.stopped
    assert quit_calls == [True]


def test_full_menu_bar_increments_live_counter_after_submission(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    monkeypatch.setattr(menu_bar_app, "business_today", lambda: date(2026, 6, 17))

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=1_420_000)
    app._today_chars = 4
    app._today_date = date(2026, 6, 17)
    app._last_submission_snapshot = None

    app._save_submission_snapshot = lambda event, content: True
    app._update_title = lambda *args, **kwargs: None

    app._on_key_event(make_submit_event("hello"))

    assert app._today_chars == 9


def test_full_menu_bar_rolls_live_counter_when_day_changes(monkeypatch):
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


def test_full_menu_bar_rolls_live_counter_on_business_day_even_when_storage_day_unchanged(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    monkeypatch.setattr(menu_bar_app, "business_today", lambda: date(2026, 7, 7))

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=0)
    app._is_recording = True
    app._today_chars = 891
    app._today_date = date(2026, 7, 6)
    app._last_title_update = 0

    app._update_title(force=True)

    assert app._today_date == date(2026, 7, 7)
    assert app._today_chars == 0
    assert app.title == "⌨️ 0"


def test_full_menu_bar_title_does_not_backfill_business_day_history(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    monkeypatch.setattr(menu_bar_app, "business_today", lambda: date(2026, 7, 6))

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=0, storage_total=61_596)
    app._is_recording = True
    app._today_chars = 0
    app._today_date = date(2026, 7, 4)
    app._last_title_update = 0

    app._update_title(force=True)

    assert app._today_date == date(2026, 7, 6)
    assert app._today_chars == 0
    assert app.title == "⌨️ 0"


def test_full_menu_bar_does_not_mix_skipped_key_estimate_into_saved_chars(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    monkeypatch.setattr(menu_bar_app, "business_today", lambda: date(2026, 6, 17))

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app.db = FakeDb(today_total=1_420_000)
    app._today_chars = 4
    app._today_date = date(2026, 6, 17)
    app._last_title_update = 0
    app._is_recording = True
    app.title = "⌨️ 4"

    app._save_capture_diagnostic(
        {
            "event_type": "enter_keydown",
            "decision_action": "skip",
            "decision_reason": "focused_element_not_text_input",
            "physical_key_count": 5,
        }
    )
    app._save_capture_diagnostic(
        {
            "event_type": "enter_keyup",
            "decision_action": "skip",
            "decision_reason": "focused_element_not_text_input",
            "physical_key_count": 0,
        }
    )

    assert app._today_chars == 4
    assert app.title == "⌨️ 4"


def test_full_menu_bar_start_updates_runtime_recording_state(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    runtime_state.reset_runtime_state()

    class FakeListener:
        def __init__(self, callback, diagnostics_callback=None):
            self.callback = callback
            self.diagnostics_callback = diagnostics_callback
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
    assert app.listener.diagnostics_callback == app._save_capture_diagnostic
    assert state.recording_status == "recording"
    assert state.is_recording is True


def test_full_menu_bar_reuses_existing_healthy_web_service(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    monkeypatch.setattr(menu_bar_app, "_is_web_service_healthy", lambda: True)

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app._web_server_running = False
    app._web_server_thread = None

    app._start_web_server()

    assert app._web_server_running is True
    assert app._web_server_thread is None


def test_full_menu_bar_defers_to_managed_standalone_web_service(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar_app = importlib.import_module("ominime.menu_bar_app")
    monkeypatch.setattr(menu_bar_app, "_is_web_service_healthy", lambda: False)
    monkeypatch.setattr(
        menu_bar_app,
        "_is_standalone_web_service_managed",
        lambda: True,
    )

    app = object.__new__(menu_bar_app.OmniMeMenuBarApp)
    app._web_server_running = False
    app._web_server_thread = None

    app._start_web_server()

    assert app._web_server_running is True
    assert app._web_server_thread is None


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

    def save_snapshot(event, content):
        saved.append(content)
        return True

    app._save_submission_snapshot = save_snapshot
    app._update_title = lambda *args, **kwargs: None

    app._on_key_event(
        make_submit_event(
            "old terminal output\nanother log line\n\n➜  ominime pytest",
            app_name="Terminal",
            app_bundle_id="com.apple.Terminal",
        )
    )

    assert saved == ["➜  ominime pytest"]
    assert app._today_chars == len("➜  ominime pytest")


def test_legacy_menu_bar_increments_live_counter_after_submission(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")
    monkeypatch.setattr(menu_bar, "business_today", lambda: date(2026, 6, 17))

    app = object.__new__(menu_bar.OmniMeApp)
    app.db = FakeDb(today_total=1_420_000)
    app._today_chars = 4
    app._today_date = date(2026, 6, 17)
    app._last_submission_snapshot = None

    app._save_submission_snapshot = lambda event, content: True
    app._update_title = lambda: None

    app._on_key_event(make_submit_event("hello"))

    assert app._today_chars == 9


def test_legacy_menu_bar_rolls_live_counter_when_day_changes(monkeypatch):
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


def test_legacy_menu_bar_rolls_live_counter_on_business_day_even_when_storage_day_unchanged(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")
    monkeypatch.setattr(menu_bar, "business_today", lambda: date(2026, 7, 7))

    app = object.__new__(menu_bar.OmniMeApp)
    app.db = FakeDb(today_total=0)
    app._is_recording = True
    app._today_chars = 891
    app._today_date = date(2026, 7, 6)

    app._update_title()

    assert app._today_date == date(2026, 7, 7)
    assert app._today_chars == 0
    assert app.title == "⌨️ 0"


def test_legacy_menu_bar_title_does_not_backfill_business_day_history(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")
    monkeypatch.setattr(menu_bar, "business_today", lambda: date(2026, 7, 6))

    app = object.__new__(menu_bar.OmniMeApp)
    app.db = FakeDb(today_total=0, storage_total=61_596)
    app._is_recording = True
    app._today_chars = 0
    app._today_date = date(2026, 7, 4)

    app._update_title()

    assert app._today_date == date(2026, 7, 6)
    assert app._today_chars == 0
    assert app.title == "⌨️ 0"


def test_legacy_menu_bar_does_not_mix_skipped_key_estimate_into_saved_chars(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")
    monkeypatch.setattr(menu_bar, "business_today", lambda: date(2026, 6, 17))

    app = object.__new__(menu_bar.OmniMeApp)
    app.db = FakeDb(today_total=1_420_000)
    app._today_chars = 4
    app._today_date = date(2026, 6, 17)
    app._is_recording = True
    app.title = "⌨️ 4"

    app._save_capture_diagnostic(
        {
            "event_type": "enter_keydown",
            "decision_action": "skip",
            "decision_reason": "focused_element_not_text_input",
            "physical_key_count": 5,
        }
    )
    app._save_capture_diagnostic(
        {
            "event_type": "enter_keyup",
            "decision_action": "skip",
            "decision_reason": "focused_element_not_text_input",
            "physical_key_count": 0,
        }
    )

    assert app._today_chars == 4
    assert app.title == "⌨️ 4"


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


def test_legacy_menu_bar_start_passes_diagnostics_callback(monkeypatch):
    install_menu_bar_import_stubs(monkeypatch)
    menu_bar = importlib.import_module("ominime.menu_bar")
    runtime_state.reset_runtime_state()
    monkeypatch.setattr(menu_bar, "check_accessibility_permission", lambda: True)

    class FakeListener:
        def __init__(self, callback, diagnostics_callback=None):
            self.callback = callback
            self.diagnostics_callback = diagnostics_callback
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr(menu_bar, "KeyboardListener", FakeListener)

    app = object.__new__(menu_bar.OmniMeApp)
    app.db = FakeDb(today_total=3)
    app._is_recording = False
    app._today_date = date(2026, 6, 17)
    app._today_chars = 0
    app._update_title = lambda *args, **kwargs: None
    sender = SimpleNamespace(title="▶️ 开始记录")

    app._start_recording(sender)

    assert app.listener.diagnostics_callback == app._save_capture_diagnostic
    assert app.listener.started is True
