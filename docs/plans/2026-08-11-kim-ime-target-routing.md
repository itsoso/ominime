# Kim IME Event Target Routing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve directly typed Kim and WeChat input when macOS routes character events through an input-method process while keeping existing app-switch and OCR trust boundaries.

**Architecture:** Carry both the native event target PID and the verified frontmost application PID in each queued keyboard event. Resolve supported Kim/WeChat input against the verified frontmost PID only when its cached identity matches the sampled application; otherwise retain the existing native-target resolution. Use the resolved application PID consistently for counters, Doubao candidates, composer preparation, and Enter context capture, and persist existing OCR/candidate failure details when a submission is skipped.

**Tech Stack:** Python 3.14, dataclasses, Quartz EventTap, pytest, SQLite diagnostics, macOS LaunchAgents.

---

### Task 1: Preserve the frontmost PID in queued events

**Files:**
- Modify: `src/ominime/keyboard_listener.py:101-114`
- Modify: `src/ominime/keyboard_listener.py:1843-1907`
- Test: `tests/test_keyboard_listener_capture.py:197-227`

**Step 1: Write the failing test**

Extend the existing Kim pre-submit callback test so the native event targets an input-method PID while `get_current_app_target()` returns the verified Kim PID. Assert that the queued value keeps both identities:

```python
assert queued.target_pid == 1020
assert queued.frontmost_pid == 5937
assert queued.app_name == "Kim"
assert queued.bundle_id == "Kem"
```

Use a non-Enter character for this assertion so frame-freeze requirements remain independent.

**Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPATH="$PWD/src" venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'queued_event_keeps_native_and_frontmost_pids'
```

Expected: FAIL because `RawKeyboardEvent` does not expose `frontmost_pid`.

**Step 3: Write the minimal implementation**

Add a backward-compatible field:

```python
frontmost_pid: int = 0
```

Populate it from the already sampled `frontmost_pid` in `_event_callback`. Do not change the strict Enter frame-freeze predicate.

**Step 4: Run the test to verify it passes**

Run the same pytest command. Expected: PASS.

### Task 2: Resolve supported input through the verified frontmost application

**Files:**
- Modify: `src/ominime/keyboard_listener.py:1653-1804`
- Test: `tests/test_keyboard_listener_capture.py:407-430`
- Test: `tests/test_keyboard_listener_capture.py:2280-2302`

**Step 1: Write failing routing tests**

Add three focused tests:

1. A Kim character event has `target_pid=1020`, `frontmost_pid=5937`, sampled identity `("Kim", "Kem")`, and cached identity `5937 -> ("Kim", "Kem")`. `get_app_by_pid(1020)` returns the Doubao input-method bundle. Assert the Kim fallback buffer receives the character and candidate/composer calls use PID 5937.
2. The same event has no matching cached identity for PID 5937. Assert it is not attributed to Kim and no Kim buffer is created.
3. An unsupported application event retains native target PID resolution, preserving current behavior.

**Step 2: Run the routing tests to verify they fail**

Run:

```bash
PYTHONPATH="$PWD/src" venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'input_method_target or unverified_frontmost or unsupported_app_uses_native_target'
```

Expected: the verified-frontmost case FAILS because `_process_raw_event` unconditionally overwrites the sampled Kim identity from native PID 1020.

**Step 3: Implement one target resolver**

Add a small listener helper returning `(app_name, bundle_id, application_pid)`:

```python
def _resolve_raw_event_target(self, raw_event):
    sampled_identity = (raw_event.app_name, raw_event.bundle_id)
    if (
        raw_event.bundle_id in SUPPORTED_TARGET_BUNDLE_IDS
        and raw_event.frontmost_pid > 0
        and self._target_app_identities.get(raw_event.frontmost_pid)
        == sampled_identity
    ):
        return (*sampled_identity, raw_event.frontmost_pid)
    if raw_event.target_pid > 0:
        app_name, bundle_id = get_app_by_pid(raw_event.target_pid)
        return app_name, bundle_id, raw_event.target_pid
    return raw_event.app_name, raw_event.bundle_id, 0
```

In `_process_raw_event`, use `application_pid` consistently for:

- `_target_app_identities` updates;
- composer `prepare()`;
- `_update_doubao_target()`;
- candidate refresh and key handling;
- `_emit_submission_snapshot(target_pid=...)`.

Keep `raw_event.target_pid` as the immutable native target for diagnostics and callback-time frame safety; do not globally replace it.

**Step 4: Run the routing tests to verify they pass**

Run the command from Step 2. Expected: PASS.

### Task 3: Reproduce direct Kim typing across an input-method PID

**Files:**
- Modify: `tests/test_keyboard_listener_capture.py:2239-2258`
- Test: `tests/test_keyboard_listener_capture.py:2750-2866`

**Step 1: Extend the event test helper**

Allow `doubao_raw_event()` to accept `frontmost_pid` while keeping its current defaults so existing tests remain unchanged.

**Step 2: Write the failing end-to-end listener test**

Construct this sequence without invoking native APIs:

```python
# Printable pinyin keys are natively targeted at the input-method PID.
for keycode, text in ((45, "n"), (34, "i"), (1, "s"), (0, "a"), (8, "c"), (5, "g")):
    listener._process_raw_event(
        doubao_raw_event(
            keyboard_listener,
            keyboard_listener.kCGEventKeyDown,
            keycode,
            text,
            target_pid=1020,
            frontmost_pid=5937,
        )
    )

# Enter is natively targeted at Kim and carries the pre-submit frame.
listener._process_raw_event(
    doubao_raw_event(
        keyboard_listener,
        keyboard_listener.kCGEventKeyDown,
        keyboard_listener.ENTER_KEYCODE,
        target_pid=5937,
        frontmost_pid=5937,
        pre_submit_frame="kim-frame",
    )
)
```

Seed the verified identity for PID 5937, make PID 1020 resolve to the input-method bundle, and make OCR return `"测试成功"`. Assert one event is emitted with:

```python
assert events[0].character == "测试成功"
assert events[0].modifiers["fallback_source"] == "kim_presubmit_ocr"
assert events[0].modifiers["physical_key_count"] == 6
```

Also retain the existing assertion that zero physical keys do not make arbitrary OCR trusted.

**Step 3: Run the test to verify it fails before the Task 2 implementation, then passes after it**

Run:

```bash
PYTHONPATH="$PWD/src" venv/bin/pytest tests/test_keyboard_listener_capture.py tests/test_kim_composer_capture.py -q -k 'direct_kim_typing_through_input_method or plausible_for_physical_key_count'
```

Expected after Task 2: PASS.

### Task 4: Preserve OCR failure evidence on skipped submissions

**Files:**
- Modify: `src/ominime/keyboard_listener.py:1406-1429`
- Test: `tests/test_keyboard_listener_capture.py:2805-2835`

**Step 1: Write the failing diagnostic test**

Create a degraded Kim Enter with no physical keys and:

```python
pre_submit_capture_failure="kim_ocr_frame_unavailable"
```

Use `diagnostics_callback` and assert the final `no_trusted_content` diagnostic contains:

```python
assert diagnostics[-1]["diagnostics"]["kim_ocr_failure"] == (
    "kim_ocr_frame_unavailable"
)
```

**Step 2: Run the test to verify it fails**

Run:

```bash
PYTHONPATH="$PWD/src" venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'skipped_kim_submission_keeps_frame_failure'
```

Expected: FAIL because the final degraded skip call drops `candidate_diagnostics`.

**Step 3: Implement the minimal diagnostic fix**

Pass the already redacted `candidate_diagnostics` mapping to the final `_emit_capture_diagnostic(..., diagnostics=...)` call. Do not add OCR text, image data, or clipboard content.

**Step 4: Run the test to verify it passes**

Run the same pytest command. Expected: PASS.

### Task 5: Regression verification and deployment

**Files:**
- Verify: `src/ominime/keyboard_listener.py`
- Verify: `tests/test_keyboard_listener_capture.py`

**Step 1: Run focused Kim/WeChat capture tests**

```bash
PYTHONPATH="$PWD/src" venv/bin/pytest tests/test_keyboard_listener_capture.py tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py tests/test_submission_diagnostics.py -q
```

Expected: PASS with no errors or warnings caused by this change.

**Step 2: Run the full suite**

```bash
PYTHONPATH="$PWD/src" venv/bin/pytest -q
```

Expected: all tests PASS. Do not pipe test output through `tail`.

**Step 3: Inspect only intended changes**

```bash
git diff --check
git status --short
git diff -- src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py
```

Expected: only the planned implementation/test files are modified; existing unrelated untracked files remain untouched.

**Step 4: Commit the implementation**

```bash
git add src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py
git commit -m "fix: attribute Kim typing through input methods"
```

**Step 5: Restart the running app**

```bash
launchctl kickstart -k "gui/$(id -u)/com.ominime.app"
```

Expected: the LaunchAgent returns successfully with a new PID.

**Step 6: Verify service health without claiming live content acceptance**

```bash
launchctl print "gui/$(id -u)/com.ominime.app"
curl --fail --silent --show-error http://127.0.0.1:8001/api/health
```

Expected: app state is `running`; health reports recording active and a fresh heartbeat. A real Kim message remains the final content-level acceptance check because tests cannot synthesize or send user text.

