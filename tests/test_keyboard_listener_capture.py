import importlib
import sys
import time
import types
from types import SimpleNamespace

import pytest


def import_keyboard_listener(monkeypatch):
    quartz = types.ModuleType("Quartz")
    quartz.kCGEventKeyDown = 1
    quartz.kCGEventKeyUp = 2
    quartz.kCGEventFlagsChanged = 3
    quartz.kCGEventLeftMouseDown = 4
    quartz.kCGEventRightMouseDown = 5
    quartz.kCGEventOtherMouseDown = 6
    quartz.kCGEventTapDisabledByTimeout = 90
    quartz.kCGEventTapDisabledByUserInput = 91
    quartz.kCGKeyboardEventKeycode = 4
    quartz.kCGKeyboardEventAutorepeat = 5
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
    quartz.CGEventGetIntegerValueField = lambda event, field: (
        getattr(event, "target_pid", 0)
        if field == 40
        else (
            getattr(event, "autorepeat", 0)
            if field == quartz.kCGKeyboardEventAutorepeat
            else getattr(event, "keycode", 0)
        )
    )
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
        | (1 << keyboard_listener.kCGEventLeftMouseDown)
        | (1 << keyboard_listener.kCGEventRightMouseDown)
        | (1 << keyboard_listener.kCGEventOtherMouseDown)
    )


def test_disabled_event_tap_is_reenabled_immediately(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    enabled = []
    monkeypatch.setattr(
        keyboard_listener,
        "CGEventTapEnable",
        lambda tap, value: enabled.append((tap, value)),
    )
    listener = keyboard_listener.KeyboardListener(lambda event: None)
    listener._tap = object()
    event = object()

    returned = listener._event_callback(
        None,
        keyboard_listener.EVENT_TAP_DISABLED_BY_TIMEOUT,
        event,
        None,
    )

    assert enabled == [(listener._tap, True)]
    assert returned is event


def test_running_event_tap_callback_only_enqueues_raw_event(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    listener = keyboard_listener.KeyboardListener(lambda event: None)
    monkeypatch.setattr(
        keyboard_listener,
        "get_current_app",
        lambda: ("Codex", "com.openai.codex"),
    )
    listener._capture_focused_context = lambda: (_ for _ in ()).throw(
        AssertionError("EventTap callback must not read Accessibility")
    )
    listener._has_started = True
    listener._event_worker_running = True

    raw_event = SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text="")
    returned = listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        raw_event,
        None,
    )

    queued = listener._event_queue.get_nowait()
    assert queued.event_type == keyboard_listener.kCGEventKeyDown
    assert queued.keycode == keyboard_listener.ENTER_KEYCODE
    assert queued.app_name == "Codex"
    assert returned is raw_event


class FakeKimComposerCapture:
    def __init__(
        self,
        frame="kim-frame",
        *,
        raises=False,
        recognize_result=("", "kim_ocr_empty"),
    ):
        self.frame = frame
        self.raises = raises
        self.recognize_result = recognize_result
        self.freeze_calls = []
        self.recognize_calls = []
        self.prepare_calls = []

    def prepare(self, target_pid):
        self.prepare_calls.append(target_pid)
        return True

    def freeze(self, target_pid):
        self.freeze_calls.append(target_pid)
        if self.raises:
            raise RuntimeError("capture failed")
        return self.frame

    def recognize(self, frame):
        self.recognize_calls.append(frame)
        return self.recognize_result


def test_kim_presubmit_frame_is_frozen_before_enter_is_enqueued(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture()
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        kim_composer_capture=capture,
    )
    monkeypatch.setattr(keyboard_listener, "get_current_app", lambda: ("Kim", "Kem"))
    listener._target_app_identities[123] = ("Kim", "Kem")
    listener._has_started = True
    listener._event_worker_running = True
    native_event = SimpleNamespace(
        keycode=keyboard_listener.ENTER_KEYCODE,
        text="",
        target_pid=123,
    )

    returned = listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        native_event,
        None,
    )

    queued = listener._event_queue.get_nowait()
    assert capture.freeze_calls == [123]
    assert queued.pre_submit_frame == "kim-frame"
    assert returned is native_event


@pytest.mark.parametrize(
    ("event_type", "keycode", "app", "flags"),
    (
        (1, 0, ("Kim", "Kem"), 0),
        (2, 36, ("Kim", "Kem"), 0),
        (1, 36, ("Kima", "Kim"), 0),
        (1, 36, ("微信", "com.tencent.xinWeChat"), 0),
        (1, 36, ("Kim", "Kem"), 1 << 17),
    ),
)
def test_kim_presubmit_frame_is_not_frozen_outside_exact_plain_enter(
    monkeypatch,
    event_type,
    keycode,
    app,
    flags,
):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture()
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        kim_composer_capture=capture,
    )
    monkeypatch.setattr(keyboard_listener, "get_current_app", lambda: app)
    listener._target_app_identities[123] = app
    listener._has_started = True
    listener._event_worker_running = True

    listener._event_callback(
        None,
        event_type,
        SimpleNamespace(keycode=keycode, text="", target_pid=123, flags=flags),
        None,
    )

    queued = listener._event_queue.get_nowait()
    assert capture.freeze_calls == []
    assert queued.pre_submit_frame is None


def test_kim_presubmit_capture_failure_does_not_block_enter(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture(raises=True)
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        kim_composer_capture=capture,
    )
    monkeypatch.setattr(keyboard_listener, "get_current_app", lambda: ("Kim", "Kem"))
    listener._target_app_identities[123] = ("Kim", "Kem")
    listener._has_started = True
    listener._event_worker_running = True
    native_event = SimpleNamespace(
        keycode=keyboard_listener.ENTER_KEYCODE,
        text="",
        target_pid=123,
    )

    returned = listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        native_event,
        None,
    )

    queued = listener._event_queue.get_nowait()
    assert queued.pre_submit_frame is None
    assert queued.pre_submit_capture_failure == "kim_ocr_capture_error"
    assert returned is native_event


def test_kim_presubmit_missing_frame_is_diagnosable(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture(frame=None)
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        kim_composer_capture=capture,
    )
    monkeypatch.setattr(keyboard_listener, "get_current_app", lambda: ("Kim", "Kem"))
    listener._target_app_identities[123] = ("Kim", "Kem")
    listener._has_started = True
    listener._event_worker_running = True

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            target_pid=123,
        ),
        None,
    )

    queued = listener._event_queue.get_nowait()
    assert queued.pre_submit_frame is None
    assert queued.pre_submit_capture_failure == "kim_ocr_frame_unavailable"


def test_kim_presubmit_does_not_trust_stale_app_identity(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture()
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        kim_composer_capture=capture,
    )
    monkeypatch.setattr(keyboard_listener, "get_current_app", lambda: ("Kim", "Kem"))
    listener._target_app_identities[999] = ("Chrome", "com.google.Chrome")
    listener._has_started = True
    listener._event_worker_running = True

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            target_pid=999,
        ),
        None,
    )

    queued = listener._event_queue.get_nowait()
    assert capture.freeze_calls == []
    assert queued.pre_submit_frame is None


def test_kim_window_is_prepared_on_worker_before_enter(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture()
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        kim_composer_capture=capture,
    )
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    listener._process_raw_event(
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=8,
            text="c",
            app_name="Kim",
            bundle_id="Kem",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=123,
        )
    )

    assert capture.prepare_calls == [123]
    assert listener._target_app_identities[123] == ("Kim", "Kem")


def test_wechat_presubmit_frame_is_frozen_before_enter_is_enqueued(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture(frame="wechat-frame")
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        wechat_composer_capture=capture,
    )
    app = ("微信", "com.tencent.xinWeChat")
    monkeypatch.setattr(keyboard_listener, "get_current_app", lambda: app)
    listener._target_app_identities[4318] = app
    listener._has_started = True
    listener._event_worker_running = True

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            target_pid=4318,
        ),
        None,
    )

    queued = listener._event_queue.get_nowait()
    assert capture.freeze_calls == [4318]
    assert queued.pre_submit_frame == "wechat-frame"


def test_wechat_window_is_prepared_on_worker_before_enter(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture(frame="wechat-frame")
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        wechat_composer_capture=capture,
    )
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("微信", "com.tencent.xinWeChat"),
    )

    listener._process_raw_event(
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=8,
            text="c",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
        )
    )

    assert capture.prepare_calls == [4318]
    assert listener._target_app_identities[4318] == (
        "微信",
        "com.tencent.xinWeChat",
    )


def test_event_tap_callback_never_processes_synchronously_after_start(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    listener = keyboard_listener.KeyboardListener(lambda event: None)
    listener._has_started = True
    listener._event_worker_running = False
    listener._capture_focused_context = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("native callback must never read Accessibility")
    )
    monkeypatch.setattr(
        keyboard_listener,
        "get_current_app",
        lambda: ("Codex", "com.openai.codex"),
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert listener._dropped_event_count == 1


def test_submission_context_capture_receives_event_target_pid(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture_calls = []
    listener = keyboard_listener.KeyboardListener(events.append)
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("Codex", "com.openai.codex"),
    )

    def fake_capture(*, target_pid=None, **_kwargs):
        capture_calls.append(target_pid)
        return SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_protected=False,
            focused_value="targeted context",
            capture_status="ok",
        )

    listener._capture_focused_context = fake_capture
    listener._context_to_dict_safe = lambda context: {"capture_status": "ok"}

    listener._process_raw_event(
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            app_name="Codex",
            bundle_id="com.openai.codex",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=123,
        )
    )

    assert capture_calls == [123]
    assert len(events) == 1


def test_start_refuses_to_spawn_second_live_event_worker(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    listener = keyboard_listener.KeyboardListener(lambda event: None)
    listener._event_worker_thread = SimpleNamespace(is_alive=lambda: True)

    try:
        listener.start()
    except RuntimeError as exc:
        assert "still stopping" in str(exc)
    else:
        raise AssertionError("start must not create a second event worker")


def test_enter_keydown_and_keyup_produce_one_submission_attempt(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: "one submission"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    enter = SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text="")
    listener._event_callback(None, keyboard_listener.kCGEventKeyDown, enter, None)
    listener._event_callback(None, keyboard_listener.kCGEventKeyUp, enter, None)

    assert len(events) == 1
    assert diagnostics == []


def test_enter_keyup_still_finishes_same_attempt_after_long_key_hold(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    listener = keyboard_listener.KeyboardListener(lambda event: None)
    now = [100.0]
    monkeypatch.setattr(keyboard_listener.time, "monotonic", lambda: now[0])

    listener._ignore_enter_keyup_once("Codex", "com.openai.codex")
    now[0] += 5.0

    assert listener._should_ignore_enter_keyup(
        "Codex",
        "com.openai.codex",
        keyboard_listener.kCGEventKeyUp,
    )


def test_enter_autorepeat_does_not_create_another_attempt(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: "submit once"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, autorepeat=0, text=""),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, autorepeat=1, text=""),
        None,
    )

    assert len(events) == 1


def test_new_enter_keydown_recovers_when_previous_keyup_was_lost(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: "submit again"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    enter = SimpleNamespace(
        keycode=keyboard_listener.ENTER_KEYCODE,
        autorepeat=0,
        text="",
    )
    listener._event_callback(None, keyboard_listener.kCGEventKeyDown, enter, None)
    listener._event_callback(None, keyboard_listener.kCGEventKeyDown, enter, None)

    assert len(events) == 2


def test_shift_enter_is_newline_not_submission(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: "draft"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: (_ for _ in ()).throw(AssertionError("newline must not read AX")),
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            flags=keyboard_listener.kCGEventFlagMaskShift,
        ),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "newline_modifier"


def test_secure_field_enter_never_saves_text(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Safari", "com.apple.Safari")
    listener._get_focused_text_snapshot = lambda: "super secret"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextField",
            focused_subrole="AXSecureTextField",
            focused_protected=True,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {
            "focused_role": context.focused_role,
            "focused_subrole": context.focused_subrole,
            "focused_protected": context.focused_protected,
            "capture_status": context.capture_status,
        },
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "secure_text_input"


def test_oversized_ax_value_is_rejected_as_probable_document(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: "x" * (keyboard_listener.MAX_TRUSTED_SUBMISSION_CHARS + 1)
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "suspected_whole_document"


def test_enter_in_editor_text_area_is_newline_not_submission(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("TextEdit", "com.apple.TextEdit")
    listener._get_focused_text_snapshot = lambda: "a short document"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "editor_newline"


def test_enter_in_generic_browser_text_area_is_newline_not_submission(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Safari", "com.apple.Safari")
    listener._get_focused_text_snapshot = lambda: "short document body"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="article-body",
            focused_title=None,
            focused_description=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "editor_newline"


def test_enter_in_browser_prompt_text_area_is_allowed(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Chrome", "com.google.Chrome")
    listener._get_focused_text_snapshot = lambda: "hello from browser chat"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt-textarea",
            focused_title=None,
            focused_description="Message composer",
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1


def test_enter_in_browser_message_composer_defaults_to_newline(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Chrome", "com.google.Chrome")
    listener._get_focused_text_snapshot = lambda: "email paragraph"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="message-composer",
            focused_title="Message body",
            focused_description="Compose message",
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "editor_newline"


def test_degraded_context_is_not_reported_as_non_text_focus(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(
        events.append,
        diagnostics_callback=diagnostics.append,
    )
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role=None,
            focused_subrole=None,
            focused_protected=False,
            capture_status="degraded",
        ),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {"capture_status": "degraded"},
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "degraded_context"


def test_degraded_diagnostic_retains_capture_error(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        diagnostics_callback=diagnostics.append,
    )
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role=None,
            focused_subrole=None,
            focused_protected=False,
            capture_status="degraded",
            capture_error="focused element unavailable (system-wide and pid 123)",
        ),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {
            "capture_status": context.capture_status,
            "capture_error": context.capture_error,
        },
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert diagnostics[-1]["diagnostics"]["capture_error"] == (
        "focused element unavailable (system-wide and pid 123)"
    )


@pytest.mark.parametrize(
    ("app_name", "bundle_id"),
    (("Kim", "Kem"), ("微信", "com.tencent.xinWeChat")),
)
def test_degraded_chat_app_persists_cjk_key_event_text(
    monkeypatch,
    app_name,
    bundle_id,
):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: (app_name, bundle_id)
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role=None,
            focused_subrole=None,
            focused_protected=False,
            capture_status="degraded",
            capture_error="focused element unavailable",
        ),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {
            "capture_status": context.capture_status,
            "capture_error": context.capture_error,
        },
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=0, text="你"),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "你"
    assert events[0].modifiers["fallback_source"] == "degraded_key_event_text"
    assert events[0].modifiers["redacted_content"] is False
    assert events[0].modifiers["context"]["capture_status"] == "degraded"


def test_degraded_chat_app_persists_only_count_for_latin_input(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Kim", "Kem")
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role=None,
            focused_subrole=None,
            focused_protected=False,
            capture_status="degraded",
        ),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {"capture_status": context.capture_status},
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=0, text="a"),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == keyboard_listener.UNREADABLE_SUBMISSION_PLACEHOLDER
    assert events[0].modifiers["fallback_source"] == "degraded_count_unreadable"
    assert events[0].modifiers["redacted_content"] is True
    assert events[0].modifiers["char_count_override"] == 1


def test_secure_chat_field_still_skips_compatibility_fallback(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(
        events.append,
        diagnostics_callback=diagnostics.append,
    )
    listener._get_event_target_app = lambda event: ("Kim", "Kem")
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextField",
            focused_subrole="AXSecureTextField",
            focused_protected=True,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {
            "focused_role": context.focused_role,
            "focused_subrole": context.focused_subrole,
            "focused_protected": context.focused_protected,
            "capture_status": context.capture_status,
        },
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=0, text="密"),
        None,
    )
    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "secure_text_input"


def test_enter_does_not_reuse_recent_snapshot_from_another_field(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    listener._recent_text_snapshots[("Codex", "com.openai.codex")] = (
        "text from first field",
        time.monotonic(),
        "id::first-field",
    )
    monkeypatch.setattr(
        keyboard_listener.config,
        "count_unreadable_submissions",
        False,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="second-field",
            focused_frame=None,
            window_title=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "no_trusted_content"


def test_enter_does_not_reuse_cjk_fallback_from_another_field(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: "english in second field"
    app_key = ("Claude", "com.anthropic.claudefordesktop")
    listener._active_field_ids[app_key] = "id::first-field"
    listener._text_fallback_buffers[app_key] = ["第一个输入框"]
    listener._text_fallback_buffer_updated_at[app_key] = time.monotonic()
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="second-field",
            focused_frame=None,
            window_title=None,
            focused_protected=False,
            capture_status="ok",
        ),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "english in second field"


def test_ignored_app_never_reads_accessibility(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    listener = keyboard_listener.KeyboardListener(lambda event: None)
    listener._get_event_target_app = lambda event: ("SecurityAgent", "com.apple.SecurityAgent")
    listener._capture_focused_context = lambda **kwargs: (_ for _ in ()).throw(
        AssertionError("ignored app must not read Accessibility")
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyUp,
        SimpleNamespace(keycode=12, text="x"),
        None,
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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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


def test_text_entry_enter_saves_english_ax_value_under_chinese_ime(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: "mixed English input"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
    )
    monkeypatch.setattr(keyboard_listener, "context_to_dict", lambda context: {})

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert len(events) == 1
    assert events[0].character == "mixed English input"
    assert events[0].modifiers["submit_snapshot"] is True
    assert "fallback_source" not in events[0].modifiers


def test_enter_emits_count_only_fallback_by_default_when_ax_value_is_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Codex", "com.openai.codex")
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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
        ("Codex", "com.openai.codex"): ("你好", time.monotonic(), "id::prompt")
    }
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt",
            focused_frame=None,
            window_title=None,
        ),
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
    listener._active_field_ids[("Codex", "com.openai.codex")] = "id::prompt"
    listener._recent_text_snapshots = {
        ("Codex", "com.openai.codex"): ("旧内容", time.monotonic())
    }
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt",
            focused_frame=None,
            window_title=None,
        ),
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
    listener._active_field_ids[("Codex", "com.openai.codex")] = "id::prompt"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt",
            focused_frame=None,
            window_title=None,
        ),
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
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt",
            focused_frame=None,
            window_title=None,
        ),
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
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt",
            focused_frame=None,
            window_title=None,
        ),
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


def test_enter_never_uses_generic_clipboard_when_ax_and_key_text_are_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Kim", "Kem")
    listener._get_focused_text_snapshot = lambda: ""
    copy_calls = []
    listener._copy_focused_submission_via_clipboard = (
        lambda app_name, bundle_id, fallback_count=0: copy_calls.append(
            (app_name, bundle_id, fallback_count)
        )
        or "今天记录中文"
    )
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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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
    assert copy_calls == []


def test_enter_without_recent_input_does_not_use_clipboard_copy_fallback(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    copy_calls = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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
    assert diagnostics[-1]["decision_action"] == "skip"
    assert diagnostics[-1]["decision_reason"] == "no_trusted_content"


def test_enter_in_non_text_context_does_not_save_ax_page_value(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: "whole conversation page text"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(focused_role="AXGroup", focused_subrole=None, capture_status="ok"),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {
            "focused_role": context.focused_role,
            "focused_subrole": context.focused_subrole,
            "capture_status": context.capture_status,
        },
    )

    listener._event_callback(
        None,
        keyboard_listener.kCGEventKeyDown,
        SimpleNamespace(keycode=keyboard_listener.ENTER_KEYCODE, text=""),
        None,
    )

    assert events == []
    assert diagnostics[-1]["decision_action"] == "skip"
    assert diagnostics[-1]["decision_reason"] == "focused_element_not_text_input"
    assert diagnostics[-1]["focused_role"] == "AXGroup"


def test_enter_in_non_text_context_does_not_use_clipboard_copy_fallback(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    copy_calls = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
    listener._get_event_target_app = lambda event: ("Claude", "com.anthropic.claudefordesktop")
    listener._get_focused_text_snapshot = lambda: ""
    listener._can_use_clipboard_copy_fallback = lambda: True
    listener._copy_focused_submission_via_clipboard = (
        lambda app_name, bundle_id, fallback_count=0: copy_calls.append((app_name, bundle_id, fallback_count))
        or "whole conversation copied"
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(focused_role="AXWebArea", focused_subrole=None, capture_status="ok"),
    )
    monkeypatch.setattr(
        keyboard_listener,
        "context_to_dict",
        lambda context: {
            "focused_role": context.focused_role,
            "focused_subrole": context.focused_subrole,
            "capture_status": context.capture_status,
        },
    )

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
    assert copy_calls == []
    assert diagnostics[-1]["decision_action"] == "skip"
    assert diagnostics[-1]["decision_reason"] == "focused_element_not_text_input"
    assert diagnostics[-1]["focused_role"] == "AXWebArea"


def test_count_only_fallback_does_not_invoke_generic_clipboard(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(events.append)
    listener._get_event_target_app = lambda event: ("Kim", "Kem")
    listener._get_focused_text_snapshot = lambda: ""
    copy_calls = []
    listener._copy_focused_submission_via_clipboard = (
        lambda app_name, bundle_id, fallback_count=0: copy_calls.append(
            (app_name, bundle_id, fallback_count)
        )
        or "输入框原文"
    )
    listener._can_use_clipboard_copy_fallback = lambda: True
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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
    assert events[0].character == keyboard_listener.UNREADABLE_SUBMISSION_PLACEHOLDER
    assert events[0].modifiers["fallback_source"] == "count_unreadable"
    assert events[0].modifiers["redacted_content"] is True
    assert events[0].modifiers["char_count_override"] == 1
    assert copy_calls == []


def test_generic_clipboard_is_skipped_and_count_only_fallback_is_used(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    diagnostics = []
    copy_calls = []
    listener = keyboard_listener.KeyboardListener(events.append, diagnostics_callback=diagnostics.append)
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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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
    assert events[0].modifiers["fallback_source"] == "count_unreadable"
    assert copy_calls == []
    assert diagnostics == []


def test_latin_ime_empty_ax_never_enables_later_clipboard_capture(monkeypatch):
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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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

    assert events == []
    assert copy_calls == []


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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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
    listener._active_field_ids[("Codex", "com.openai.codex")] = "id::prompt"
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt",
            focused_frame=None,
            window_title=None,
        ),
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
    listener._active_field_ids[("Codex", "com.openai.codex")] = "id::prompt"
    monkeypatch.setattr(
        keyboard_listener.config,
        "capture_key_event_text_fallback",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        keyboard_listener,
        "capture_accessibility_context",
        lambda: SimpleNamespace(
            focused_role="AXTextArea",
            focused_subrole=None,
            focused_identifier="prompt",
            focused_frame=None,
            window_title=None,
        ),
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
        lambda: SimpleNamespace(focused_role="AXTextArea", focused_subrole=None),
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


class FakeDoubaoCandidateReader:
    def __init__(self, snapshots=()):
        self.snapshots = list(snapshots)
        self.calls = []
        self.last_failure_reason = None

    def read(self, *, target_pid, target_bundle_id):
        self.calls.append((target_pid, target_bundle_id))
        if self.snapshots:
            snapshot = self.snapshots.pop(0)
            self.last_failure_reason = (
                None if snapshot is not None else "candidate_ax_unavailable"
            )
            return snapshot
        self.last_failure_reason = "candidate_ax_unavailable"
        return None


def doubao_raw_event(
    keyboard_listener,
    event_type,
    keycode,
    text="",
    target_pid=123,
    pre_submit_frame=None,
    pre_submit_capture_failure=None,
):
    return keyboard_listener.RawKeyboardEvent(
        event_type=event_type,
        keycode=keycode,
        text=text,
        app_name="Kim",
        bundle_id="Kem",
        modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
        target_pid=target_pid,
        pre_submit_frame=pre_submit_frame,
        pre_submit_capture_failure=pre_submit_capture_failure,
    )


def test_doubao_keyup_reads_candidates_after_printable_input(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试", "策士"), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot])
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    listener._process_raw_event(
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c")
    )
    listener._process_raw_event(
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c")
    )

    assert reader.calls == [(123, "Kem")]
    assert listener._doubao_states[("Kim", "Kem")].has_active_candidate


def test_doubao_reader_is_not_called_for_unsupported_app(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    reader = FakeDoubaoCandidateReader()
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("Codex", "com.openai.codex"),
    )
    raw_event = keyboard_listener.RawKeyboardEvent(
        event_type=keyboard_listener.kCGEventKeyUp,
        keycode=8,
        text="c",
        app_name="Codex",
        bundle_id="com.openai.codex",
        modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
        target_pid=123,
    )

    listener._process_raw_event(raw_event)

    assert reader.calls == []


def test_doubao_enter_commits_candidate_without_submitting_chat(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试", "策士"), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, snapshot])
    events = []
    diagnostics = []
    submission_calls = []
    listener = keyboard_listener.KeyboardListener(
        events.append,
        diagnostics_callback=diagnostics.append,
        candidate_reader=reader,
    )
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    listener._emit_submission_snapshot = lambda *args, **kwargs: submission_calls.append(kwargs)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
        ),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyUp,
            keyboard_listener.ENTER_KEYCODE,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert events == []
    assert submission_calls == []
    assert diagnostics[-1]["decision_reason"] == "ime_candidate_commit"
    assert diagnostics[-1]["selected_source"] == "doubao_candidate_ax"

    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
        )
    )

    assert len(submission_calls) == 1


def test_doubao_space_and_number_commit_do_not_submit_chat(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshots = [
        keyboard_listener.CandidateSnapshot(("测试", "策士"), 123, time.monotonic()),
        keyboard_listener.CandidateSnapshot(("测试", "策士"), 123, time.monotonic()),
        keyboard_listener.CandidateSnapshot(("你好", "拟好"), 123, time.monotonic()),
        keyboard_listener.CandidateSnapshot(("你好", "拟好"), 123, time.monotonic()),
    ]
    reader = FakeDoubaoCandidateReader(snapshots)
    submission_calls = []
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    listener._emit_submission_snapshot = lambda *args, **kwargs: submission_calls.append(kwargs)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for keycode, text, commit_keycode, commit_text in (
        (8, "c", 49, " "),
        (45, "n", 19, "2"),
    ):
        listener._process_raw_event(
            doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, keycode, text)
        )
        listener._process_raw_event(
            doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, keycode, text)
        )
        listener._process_raw_event(
            doubao_raw_event(
                keyboard_listener,
                keyboard_listener.kCGEventKeyDown,
                commit_keycode,
                commit_text,
            )
        )

    assert submission_calls == []
    assert listener._doubao_states[("Kim", "Kem")].confirmed_text == "测试拟好"


def test_doubao_pid_change_discards_old_composition(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, snapshot])
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            7,
            "x",
            target_pid=456,
        ),
    ):
        listener._process_raw_event(raw_event)

    state = listener._doubao_states[("Kim", "Kem")]
    assert state.pop_submission(target_pid=456) == ""


def configure_listener_context(listener, *, status="degraded", secure=False):
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    listener._capture_focused_context = lambda **kwargs: SimpleNamespace(
        focused_role="AXTextField" if secure else None,
        focused_subrole="AXSecureTextField" if secure else None,
        focused_protected=secure,
        capture_status=status,
        capture_error=None if secure else "focused element unavailable",
    )
    listener._context_to_dict_safe = lambda context: {
        "focused_role": context.focused_role,
        "focused_subrole": context.focused_subrole,
        "focused_protected": context.focused_protected,
        "capture_status": context.capture_status,
        "capture_error": context.capture_error,
    }


def test_kim_presubmit_ocr_persists_degraded_legacy_kim_content(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture = FakeKimComposerCapture(recognize_result=("测试成功", None))
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        kim_composer_capture=capture,
    )
    configure_listener_context(listener)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            8,
            "c",
        )
    )
    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
            pre_submit_frame="kim-frame",
        )
    )

    assert capture.recognize_calls == ["kim-frame"]
    assert len(events) == 1
    assert events[0].character == "测试成功"
    assert events[0].modifiers["fallback_source"] == "kim_presubmit_ocr"
    assert events[0].modifiers["redacted_content"] is False


def test_kim_presubmit_ocr_failure_keeps_count_only_without_text_in_diagnostics(
    monkeypatch,
):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture = FakeKimComposerCapture(
        recognize_result=("", "kim_ocr_uncommitted_text")
    )
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        kim_composer_capture=capture,
    )
    configure_listener_context(listener)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            8,
            "c",
        )
    )
    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
            pre_submit_frame="kim-frame",
        )
    )

    assert len(events) == 1
    assert events[0].character == keyboard_listener.UNREADABLE_SUBMISSION_PLACEHOLDER
    assert events[0].modifiers["fallback_source"] == "degraded_count_unreadable"
    assert events[0].modifiers["capture_diagnostics"] == {
        "doubao_candidate_failure": "candidate_ax_unavailable",
        "kim_ocr_failure": "kim_ocr_uncommitted_text",
    }
    assert "ocr_text" not in events[0].modifiers["capture_diagnostics"]


def test_wechat_presubmit_ocr_persists_degraded_content(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture = FakeKimComposerCapture(
        frame="wechat-frame",
        recognize_result=("微信验收", None),
    )
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        wechat_composer_capture=capture,
    )
    configure_listener_context(listener)
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("微信", "com.tencent.xinWeChat"),
    )

    for event in (
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=8,
            text="c",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
        ),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=13,
            text="w",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
        ),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
            pre_submit_frame="wechat-frame",
        ),
    ):
        listener._process_raw_event(event)

    assert capture.recognize_calls == ["wechat-frame"]
    assert len(events) == 1
    assert events[0].character == "微信验收"
    assert events[0].modifiers["fallback_source"] == "wechat_presubmit_ocr"
    assert events[0].modifiers["redacted_content"] is False


def test_wechat_presubmit_ocr_runs_when_ax_context_is_ok_but_empty(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture = FakeKimComposerCapture(
        frame="wechat-frame",
        recognize_result=("微信空值回退", None),
    )
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        wechat_composer_capture=capture,
    )
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    listener._capture_focused_context = lambda **kwargs: SimpleNamespace(
        focused_role="AXTextArea",
        focused_subrole=None,
        focused_protected=False,
        focused_value="",
        capture_status="ok",
    )
    listener._context_to_dict_safe = lambda context: {
        "focused_role": "AXTextArea",
        "capture_status": "ok",
    }
    listener._get_focused_text_snapshot = lambda: ""
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("微信", "com.tencent.xinWeChat"),
    )

    for event in (
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=8,
            text="c",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
        ),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=13,
            text="w",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
        ),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
            pre_submit_frame="wechat-frame",
        ),
    ):
        listener._process_raw_event(event)

    assert events[0].character == "微信空值回退"
    assert events[0].modifiers["fallback_source"] == "wechat_presubmit_ocr"
    assert capture.recognize_calls == ["wechat-frame"]


def test_wechat_ax_content_wins_without_running_ocr(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture = FakeKimComposerCapture(
        frame="wechat-frame",
        recognize_result=("不应读取", None),
    )
    listener = keyboard_listener.KeyboardListener(
        events.append,
        wechat_composer_capture=capture,
    )
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    listener._capture_focused_context = lambda **kwargs: SimpleNamespace(
        focused_role="AXTextArea",
        focused_subrole=None,
        focused_protected=False,
        focused_value="辅助功能正文",
        capture_status="ok",
    )
    listener._context_to_dict_safe = lambda context: {
        "focused_role": "AXTextArea",
        "capture_status": "ok",
    }
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("微信", "com.tencent.xinWeChat"),
    )

    listener._process_raw_event(
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
            pre_submit_frame="wechat-frame",
        )
    )

    assert events[0].character == "辅助功能正文"
    assert "fallback_source" not in events[0].modifiers
    assert capture.recognize_calls == []


def test_wechat_presubmit_ocr_failure_keeps_count_only(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture = FakeKimComposerCapture(
        frame="wechat-frame",
        recognize_result=("", "wechat_ocr_uncommitted_text"),
    )
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        wechat_composer_capture=capture,
    )
    configure_listener_context(listener)
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("微信", "com.tencent.xinWeChat"),
    )

    for event in (
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=8,
            text="c",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
        ),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            app_name="微信",
            bundle_id="com.tencent.xinWeChat",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=4318,
            pre_submit_frame="wechat-frame",
        ),
    ):
        listener._process_raw_event(event)

    assert events[0].modifiers["fallback_source"] == "degraded_count_unreadable"
    assert events[0].modifiers["capture_diagnostics"] == {
        "doubao_candidate_failure": "candidate_ax_unavailable",
        "wechat_ocr_failure": "wechat_ocr_uncommitted_text",
    }


def test_kim_presubmit_missing_frame_failure_is_saved_without_content(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        kim_composer_capture=FakeKimComposerCapture(),
    )
    configure_listener_context(listener)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            8,
            "c",
        )
    )
    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
            pre_submit_capture_failure="kim_ocr_frame_unavailable",
        )
    )

    assert events[0].modifiers["capture_diagnostics"]["kim_ocr_failure"] == (
        "kim_ocr_frame_unavailable"
    )


def test_kim_presubmit_rejects_partial_text_for_large_key_count(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    capture = FakeKimComposerCapture(recognize_result=("测试", None))
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        kim_composer_capture=capture,
    )
    configure_listener_context(listener)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))
    key = ("Kim", "Kem")
    listener._fallback_buffers[key] = ["x"] * 100
    listener._fallback_buffer_updated_at[key] = time.monotonic()

    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
            pre_submit_frame="kim-frame",
        )
    )

    assert events[0].modifiers["fallback_source"] == "degraded_count_unreadable"
    assert events[0].modifiers["char_count_override"] == 100
    assert events[0].modifiers["capture_diagnostics"]["kim_ocr_failure"] == (
        "kim_ocr_key_count_mismatch"
    )


@pytest.mark.parametrize(
    ("app_name", "bundle_id", "secure"),
    (
        ("Kima", "Kim", False),
        ("微信", "com.tencent.xinWeChat", False),
        ("Kim", "Kem", True),
    ),
)
def test_kim_presubmit_ocr_is_not_read_for_other_or_secure_contexts(
    monkeypatch,
    app_name,
    bundle_id,
    secure,
):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    capture = FakeKimComposerCapture(recognize_result=("不应读取", None))
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        candidate_reader=FakeDoubaoCandidateReader([None]),
        kim_composer_capture=capture,
    )
    configure_listener_context(listener, status="ok" if secure else "degraded", secure=secure)
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: (app_name, bundle_id),
    )

    listener._process_raw_event(
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=keyboard_listener.ENTER_KEYCODE,
            text="",
            app_name=app_name,
            bundle_id=bundle_id,
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=123,
            pre_submit_frame="kim-frame",
        )
    )

    assert capture.recognize_calls == []


@pytest.mark.parametrize(
    ("app_name", "bundle_id"),
    (("Kim", "Kem"), ("微信", "com.tencent.xinWeChat")),
)
def test_doubao_persists_confirmed_candidate_on_real_chat_enter(
    monkeypatch,
    app_name,
    bundle_id,
):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试", "策士"), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, snapshot])
    capture = FakeKimComposerCapture(recognize_result=("不应覆盖候选", None))
    events = []
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=reader,
        kim_composer_capture=capture,
    )
    configure_listener_context(listener)
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: (app_name, bundle_id),
    )

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
            pre_submit_frame="kim-frame",
        ),
    ):
        listener._process_raw_event(raw_event)

    assert len(events) == 1
    assert events[0].character == "测试"
    assert events[0].modifiers["fallback_source"] == "doubao_candidate_text"
    assert events[0].modifiers["redacted_content"] is False
    assert events[0].modifiers["physical_key_count"] == 2
    assert capture.recognize_calls == []

    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
        )
    )
    assert len(events) == 1


def test_doubao_secure_context_discards_confirmed_candidate(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("秘密",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, snapshot])
    events = []
    diagnostics = []
    listener = keyboard_listener.KeyboardListener(
        events.append,
        diagnostics_callback=diagnostics.append,
        candidate_reader=reader,
    )
    configure_listener_context(listener, status="ok", secure=True)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "m"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "m"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert events == []
    assert diagnostics[-1]["decision_reason"] == "secure_text_input"
    assert ("Kim", "Kem") not in listener._doubao_states


def test_doubao_missing_candidate_keeps_count_only_fallback(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    events = []
    listener = keyboard_listener.KeyboardListener(
        events.append,
        candidate_reader=FakeDoubaoCandidateReader([None]),
    )
    configure_listener_context(listener)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 0, "a"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 0, "a"),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert len(events) == 1
    assert events[0].character == keyboard_listener.UNREADABLE_SUBMISSION_PLACEHOLDER
    assert events[0].modifiers["fallback_source"] == "degraded_count_unreadable"
    assert events[0].modifiers["redacted_content"] is True
    assert events[0].modifiers["capture_diagnostics"] == {
        "doubao_candidate_failure": "candidate_ax_unavailable"
    }


def test_doubao_enter_revalidates_candidate_before_commit(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, None])
    diagnostics = []
    submission_calls = []
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        diagnostics_callback=diagnostics.append,
        candidate_reader=reader,
    )
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    listener._emit_submission_snapshot = lambda *args, **kwargs: submission_calls.append(kwargs)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert reader.calls == [(123, "Kem"), (123, "Kem")]
    assert submission_calls
    assert not any(item["decision_reason"] == "ime_candidate_commit" for item in diagnostics)


def test_doubao_commit_key_recovers_when_keyup_candidate_was_early(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([None, snapshot])
    diagnostics = []
    submission_calls = []
    listener = keyboard_listener.KeyboardListener(
        lambda event: None,
        diagnostics_callback=diagnostics.append,
        candidate_reader=reader,
    )
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    listener._emit_submission_snapshot = lambda *args, **kwargs: submission_calls.append(kwargs)
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keyboard_listener.ENTER_KEYCODE,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert reader.calls == [(123, "Kem"), (123, "Kem")]
    assert submission_calls == []
    assert diagnostics[-1]["decision_reason"] == "ime_candidate_commit"


def test_doubao_later_keyup_miss_preserves_confirmed_prefix_after_recovery(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    first = keyboard_listener.CandidateSnapshot(("测试",), 123, time.monotonic())
    second = keyboard_listener.CandidateSnapshot(("你好",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([first, first, None, second])
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 45, "n"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 45, "n"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
    ):
        listener._process_raw_event(raw_event)

    assert reader.calls == [(123, "Kem")] * 4
    assert listener._doubao_states[("Kim", "Kem")].confirmed_text == "测试你好"


def test_doubao_app_switch_discards_confirmed_composition(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, snapshot])
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(
        keyboard_listener,
        "get_app_by_pid",
        lambda pid: ("Kim", "Kem") if pid == 123 else ("Codex", "com.openai.codex"),
    )

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=0,
            text="a",
            app_name="Codex",
            bundle_id="com.openai.codex",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=999,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert listener._doubao_states == {}


def test_doubao_unmodelled_shortcut_discards_confirmed_composition(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, snapshot])
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventKeyDown,
            keycode=9,
            text="v",
            app_name="Kim",
            bundle_id="Kem",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": True},
            target_pid=123,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert listener._doubao_states == {}


def test_doubao_mouse_click_discards_confirmed_composition(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    snapshot = keyboard_listener.CandidateSnapshot(("测试",), 123, time.monotonic())
    reader = FakeDoubaoCandidateReader([snapshot, snapshot])
    listener = keyboard_listener.KeyboardListener(lambda event: None, candidate_reader=reader)
    listener._record_recent_text_snapshot = lambda *args, **kwargs: None
    monkeypatch.setattr(keyboard_listener, "get_app_by_pid", lambda pid: ("Kim", "Kem"))

    for raw_event in (
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyUp, 8, "c"),
        doubao_raw_event(keyboard_listener, keyboard_listener.kCGEventKeyDown, 49, " "),
        keyboard_listener.RawKeyboardEvent(
            event_type=keyboard_listener.kCGEventLeftMouseDown,
            keycode=0,
            text="",
            app_name="Kim",
            bundle_id="Kem",
            modifiers={"shift": False, "ctrl": False, "alt": False, "cmd": False},
            target_pid=123,
        ),
    ):
        listener._process_raw_event(raw_event)

    assert listener._doubao_states == {}
