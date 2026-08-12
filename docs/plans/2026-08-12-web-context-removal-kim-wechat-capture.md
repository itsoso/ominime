# Web Context Removal and Kim/WeChat Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the Web context surface and future context persistence while restoring trusted, local-only Kim and WeChat composer text capture.

**Architecture:** Keep target-PID Accessibility reads as the primary text and secure-field signal. For a verified Kim/WeChat plain Enter, the EventTap callback copies and suppresses the physical event, starts a bounded fail-open watchdog, and the worker performs the security check, copies one in-memory window frame, immediately replays a marked keyDown/keyUp pair to the target PID, and runs OCR only as the final fallback. Preserve the historical SQLite context table but stop writing to and exposing it.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, PyObjC Quartz/Vision, vanilla HTML/CSS/JavaScript, pytest.

---

### Task 1: Remove the Web context surface

**Files:**
- Modify: `tests/test_dashboard_template.py`
- Modify: `tests/test_web_health.py`
- Modify: `src/ominime/web/templates/index.html`
- Modify: `src/ominime/web/api.py`

**Step 1: Write failing template tests**

Add a test that reads the dashboard template and asserts all of these are absent:

```python
def test_dashboard_has_no_submission_context_surface():
    html = TEMPLATE.read_text(encoding="utf-8")

    assert "🧠 上下文" not in html
    assert 'id="tab-context"' not in html
    assert "loadSubmissionContexts" not in html
    assert "renderSubmissionContext" not in html
    assert "/api/submissions" not in html
    assert ".context-card" not in html
```

Add an API test that `/api/submissions` is absent and the health payload does not expose the context switch:

```python
def test_context_api_and_health_flag_are_not_exposed(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    install_test_api_state(monkeypatch, db, tmp_path)
    client = TestClient(web_api.app)

    assert client.get("/api/submissions").status_code == 404
    assert "capture_context_on_enter" not in client.get("/api/health").json()
```

**Step 2: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_dashboard_template.py::test_dashboard_has_no_submission_context_surface tests/test_web_health.py::test_context_api_and_health_flag_are_not_exposed -q
```

Expected: both tests fail because the tab, JavaScript, route, and health field still exist.

**Step 3: Implement the minimal Web removal**

- Delete context-specific CSS, tab button, tab body, `switchTab`/`loadData` context branches, and the submission context load/render functions from `index.html`.
- Delete the `/api/submissions` route from `api.py`.
- Delete `capture_context_on_enter` from `_build_health_payload()`.
- Keep unrelated content, analysis, and capture-diagnostics surfaces intact.

**Step 4: Run focused Web tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_dashboard_template.py tests/test_web_health.py tests/test_web_security.py -q
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add tests/test_dashboard_template.py tests/test_web_health.py src/ominime/web/templates/index.html src/ominime/web/api.py
git commit -m "refactor: remove web context surface"
```

### Task 2: Stop future context persistence

**Files:**
- Modify: `tests/test_database_submission_context.py`
- Modify: `tests/test_submission_privacy.py`
- Modify: `src/ominime/submission_processor.py`

**Step 1: Write a failing submission behavior test**

Keep the existing database compatibility tests for historical rows. Add a runtime test that saves a normal submission, verifies the input record exists, and verifies no context record was added:

```python
def test_new_submission_does_not_persist_context(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    event = make_submission_event(
        modifiers={
            "submission_id": "no-new-context",
            "context": {
                "window_title": "Private chat",
                "focused_role": "AXTextArea",
            },
        }
    )

    submission_processor.save_submission_event(db, event)

    assert db.get_latest_input_record().content == event.character
    assert db.get_submission_context("no-new-context") is None
```

Adjust the helper signature to accept modifier overrides without weakening existing privacy assertions.

**Step 2: Run the test and verify RED**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_submission_privacy.py::test_new_submission_does_not_persist_context -q
```

Expected: FAIL because `save_submission_event()` still inserts a `submission_contexts` row.

**Step 3: Implement the minimal persistence change**

- Remove the `SubmissionContextRecord` import from `submission_processor.py`.
- Remove the `db.save_submission_context(...)` call from `save_submission_event()`.
- Keep `Database.save_submission_context()` and query methods unchanged so historical data remains readable internally and migrations remain compatible.
- Continue writing capture diagnostics, but do not add window titles, frames, hierarchy, or AX labels to new input records.

**Step 4: Run persistence and privacy tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_submission_privacy.py tests/test_submission_diagnostics.py tests/test_database_submission_context.py -q
```

Expected: all selected tests pass; compatibility tests can still manually create/read historical context rows.

**Step 5: Commit**

```bash
git add tests/test_submission_privacy.py src/ominime/submission_processor.py
git commit -m "refactor: stop persisting submission context"
```

### Task 3: Restore local Kim and WeChat composer capture in the worker

**Files:**
- Modify: `tests/test_keyboard_listener_capture.py`
- Modify: `tests/test_maintenance_surface.py`
- Modify: `src/ominime/keyboard_listener.py`

**Step 1: Write failing production-construction tests**

Replace the obsolete assertion that production does not construct OCR capture with behavior assertions:

```python
def test_production_listener_constructs_local_chat_captures():
    source = (ROOT / "src/ominime/keyboard_listener.py").read_text(encoding="utf-8")

    assert "KimPreSubmitCapture()" in source
    assert "WeChatPreSubmitCapture()" in source
```

Add a default-constructor test using monkeypatched capture classes if source inspection is avoidable with the module import harness.

**Step 2: Write failing worker-freeze tests**

Create a Kim test and a WeChat test that inject `FakeKimComposerCapture`, process ordinary keydown events to prepare the PID, then process Enter without setting `RawKeyboardEvent.pre_submit_frame`. Assert:

```python
assert capture.prepare_calls == [target_pid]
assert capture.freeze_calls == [target_pid]
assert capture.recognize_calls == [expected_frame]
assert events[0].character == expected_text
assert events[0].modifiers["fallback_source"] == expected_source
```

Add security/control tests asserting `freeze_calls == []` for secure input, ignored apps, modifier Enter, and EventTap callback-only execution.

**Step 3: Run tests and verify RED**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py -q
```

Expected: new worker tests fail because default captures are absent and Enter forwards no worker-created frame.

**Step 4: Implement default local adapters**

In `KeyboardListener.__init__`, use explicit `None` defaults to construct one adapter per supported app:

```python
self._presubmit_composer_captures = {
    LEGACY_KIM_BUNDLE_ID: kim_composer_capture or KimPreSubmitCapture(),
    WECHAT_BUNDLE_ID: wechat_composer_capture or WeChatPreSubmitCapture(),
}
```

If tests need to express an intentionally disabled adapter, use a private sentinel so dependency injection can distinguish “not provided” from an explicit test override. Do not add a user-facing feature switch.

**Step 5: Defer capture by suppressing and replaying verified Enter**

In `_event_callback()`, suppress only when all of these hold: keydown, Enter, no modifier, no autorepeat, `enter-text` mode, non-ignored supported bundle, target PID equals frontmost PID, and the prepared identity matches. Copy and mark a keyDown/keyUp replay pair, attach it to `RawKeyboardEvent`, start a bounded watchdog, and return `None` only after the request is successfully queued. Consume the matching physical keyUp so the target receives exactly one ordered pair.

```python
def _freeze_presubmit_composer(self, bundle_id: str, target_pid: int):
    capture = self._presubmit_composer_captures.get(bundle_id)
    if capture is None or target_pid <= 0:
        return None, None
    try:
        frame = capture.freeze(target_pid)
    except Exception:
        frame = None
    failure_prefix, _ = PRESUBMIT_OCR_METADATA[bundle_id]
    return frame, None if frame is not None else f"{failure_prefix}_frame_unavailable"
```

Do not enumerate windows, copy pixels, run OCR, or read AX/input-source APIs in `_event_callback()`. The worker checks secure input, copies the prepared window only when safe, immediately posts the marked Enter pair to its original target PID, then preserves source priority and calls `recognize()` only after AXValue, candidate text, and key-event text fail. A worker `finally` and a 200ms watchdog both call the same idempotent release path.

**Step 6: Run focused tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py tests/test_maintenance_surface.py -q
```

Expected: all selected tests pass; callback tests still assert no captured frame is attached by EventTap.

**Step 7: Commit**

```bash
git add tests/test_keyboard_listener_capture.py tests/test_maintenance_surface.py src/ominime/keyboard_listener.py
git commit -m "fix: restore local Kim and WeChat text capture"
```

### Task 4: Verify, integrate, restart, and smoke test

**Files:**
- Modify only if verification exposes a directly related defect.

**Step 1: Run static checks**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m compileall -q src tests
bash -n scripts/*.sh src/ominime/scripts/*.sh
git diff --check main...HEAD
```

Expected: all commands exit 0.

**Step 2: Run the full test suite**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest -q
```

Expected: all tests pass; the known Starlette deprecation warning may remain.

**Step 3: Review scope and preserve user files**

```bash
git status --short
git diff --stat main...HEAD
git log --oneline main..HEAD
```

Expected: only planned tracked files and plan documents differ; root workspace untracked files remain untouched.

**Step 4: Merge into main and push**

From the primary worktree, fast-forward or merge the verified branch into `main`, then push `main` to GitHub. Stage only explicit planned paths if any final commit is required.

**Step 5: Restart LaunchAgents**

Restart `com.ominime.app` and `com.ominime.web` using the repository's existing launchctl workflow. Confirm both jobs have stable PIDs and the Web process listens only on `127.0.0.1:8001`.

**Step 6: Run post-deploy smoke tests**

Verify:

```bash
curl -fsS http://127.0.0.1:8001/api/health
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/api/submissions
curl -fsS http://127.0.0.1:8001/
```

Expected: health is running/recording without `capture_context_on_enter`; submissions returns 404; dashboard HTML contains no context tab or request. Ask the user for one Kim and one WeChat send action if live-content validation cannot be safely automated, then inspect capture diagnostics for `kim_presubmit_ocr` and `wechat_presubmit_ocr`.
