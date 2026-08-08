# Kim and WeChat Enter Capture Compatibility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Record Kim and WeChat chat submissions when system-wide accessibility focus is unavailable without reopening generic clipboard or keystroke-capture risks.

**Architecture:** Pass the keyboard event's target PID into accessibility context capture and retry against that process before declaring capture degraded. For exact Kim and WeChat bundle IDs only, consume the existing bounded CJK key-event buffer or persist a redacted character count when AX remains degraded; retain strict skipping for all other applications.

**Tech Stack:** Python 3, PyObjC ApplicationServices/Quartz, pytest, SQLite diagnostics

---

### Task 1: Process-scoped accessibility retry

**Files:**
- Modify: `src/ominime/context_capture.py`
- Test: `tests/test_context_capture.py`

**Step 1: Write the failing tests**

Add tests proving that `capture_accessibility_context(target_pid=123)`:

- uses the system-wide focused element when available;
- retries `AXFocusedUIElement` on `AXUIElementCreateApplication(123)` when the
  system-wide element is unavailable;
- returns a degraded context containing the final AX error when neither query
  returns an element.

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_context_capture.py -q`

Expected: FAIL because `capture_accessibility_context` does not accept
`target_pid` and has no process-scoped fallback.

**Step 3: Write the minimal implementation**

- Add an optional `target_pid` argument.
- Keep the system-wide query first.
- If it returns no element and `target_pid > 0`, create the application AX
  element and read its `AXFocusedUIElement`.
- Preserve a concise `capture_error` describing both unavailable sources.

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_context_capture.py -q`

Expected: PASS.

### Task 2: Route target PID through Enter capture

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Test: `tests/test_keyboard_listener_capture.py`

**Step 1: Write the failing test**

Add a test that processes a `RawKeyboardEvent` with `target_pid=123` and
asserts that submission context capture receives `target_pid=123`.

**Step 2: Run the test to verify it fails**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k target_pid`

Expected: FAIL because `_emit_submission_snapshot` currently discards the PID.

**Step 3: Write the minimal implementation**

- Allow `_capture_focused_context` and `_emit_submission_snapshot` to receive an
  optional target PID.
- Pass `raw_event.target_pid` from `_process_raw_event`.
- Retain compatibility with existing zero-argument test doubles.

**Step 4: Run the test to verify it passes**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k target_pid`

Expected: PASS.

### Task 3: Restricted degraded-context compatibility

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Test: `tests/test_keyboard_listener_capture.py`

**Step 1: Write failing behavior tests**

Add independent tests proving:

- degraded Kim context persists recent CJK key-event text;
- degraded WeChat context persists recent CJK key-event text;
- degraded Kim/WeChat context without trusted CJK text persists only
  `[unreadable input]` with a physical character-count override;
- a different degraded application still skips;
- a readable secure Kim/WeChat field still skips.

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'degraded or secure'`

Expected: new compatibility tests FAIL at the current early
`degraded_context` return.

**Step 3: Write the minimal implementation**

- Add an exact bundle-ID set containing `Kem` and
  `com.tencent.xinWeChat`.
- For a degraded compatibility app, consume only the existing CJK text buffer;
  permit missing field identity only in this exact path.
- If no CJK text exists, use the existing count-only redacted placeholder.
- Emit `persist_text`/`persist_count_only` diagnostics with an explicit degraded
  compatibility source.
- Preserve the current skip path for all other degraded applications.

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'degraded or secure'`

Expected: PASS.

### Task 4: Preserve AX failure diagnostics

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Test: `tests/test_keyboard_listener_capture.py`
- Test: `tests/test_database_capture_diagnostics.py`

**Step 1: Write the failing test**

Assert that `capture_error` is nested in the persisted diagnostics payload when
context capture is degraded.

**Step 2: Run tests to verify they fail**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py tests/test_database_capture_diagnostics.py -q -k capture_error`

Expected: FAIL because `_emit_capture_diagnostic` currently drops the field.

**Step 3: Write the minimal implementation**

Copy non-empty `context_data["capture_error"]` into the diagnostic metadata;
do not put free-form errors into indexed database columns.

**Step 4: Run tests to verify they pass**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py tests/test_database_capture_diagnostics.py -q -k capture_error`

Expected: PASS.

### Task 5: Full verification, commit, and deployment

**Files:**
- Verify all files modified above.

**Step 1: Run focused tests**

Run: `venv/bin/pytest tests/test_context_capture.py tests/test_keyboard_listener_capture.py tests/test_database_capture_diagnostics.py -q`

Expected: PASS with zero failures.

**Step 2: Run the complete suite**

Run: `venv/bin/pytest -q`

Expected: PASS with zero failures.

**Step 3: Review the exact diff**

Run: `git diff --check && git status --short && git diff -- src/ominime/context_capture.py src/ominime/keyboard_listener.py tests/test_context_capture.py tests/test_keyboard_listener_capture.py tests/test_database_capture_diagnostics.py`

Expected: only planned files changed and no whitespace errors.

**Step 4: Commit only this fix**

```bash
git add src/ominime/context_capture.py src/ominime/keyboard_listener.py \
  tests/test_context_capture.py tests/test_keyboard_listener_capture.py \
  tests/test_database_capture_diagnostics.py \
  docs/plans/2026-08-07-kim-wechat-enter-capture-implementation.md
git commit -m "fix: capture Kim and WeChat submissions"
```

**Step 5: Restart and validate**

Restart the project's configured OmniMe application and web launch agents.
Verify both services are running, the health endpoint reports recording active,
and the runtime heartbeat is fresh.
