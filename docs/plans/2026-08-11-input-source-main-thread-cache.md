# Input Source Main-Thread Cache Implementation Plan

> **For Codex:** Execute task-by-task with test-driven development. Do not call the Carbon TIS API from any worker or EventTap thread.

**Goal:** Prevent macOS native `SIGTRAP` crashes by moving all active-input-source reads to a main-thread timer and serving background consumers from a short-lived cache.

**Architecture:** `ime_candidate_capture` owns a timestamped, thread-safe snapshot. A guarded refresh function is the only path to the native TIS API; a cache reader returns an empty bundle ID when the snapshot is absent or stale. `OmniMeMenuBarApp` refreshes on the main AppKit thread every 250ms, while candidate capture and Kim OCR use only the cache.

**Tech Stack:** Python 3, ctypes/Carbon HIToolbox, rumps/AppKit timer, pytest, launchd.

---

### Task 1: Add the guarded input-source cache

**Files:**
- Modify: `src/ominime/ime_candidate_capture.py`
- Test: `tests/test_ime_candidate_capture.py`

**Step 1: Write failing cache tests**

Add tests proving:

- an uninitialized or expired cache returns `""`;
- a main-thread refresh publishes the native provider result;
- a failed native refresh publishes an empty value instead of retaining an older identity;
- a worker-thread refresh raises before invoking the native provider;
- direct `current_input_source_bundle_id()` calls from a worker thread are rejected before loading the native API.

**Step 2: Run the focused test file and confirm failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_ime_candidate_capture.py`

Expected: FAIL because cache APIs and main-thread guards do not exist.

**Step 3: Implement the minimum cache API**

In `ime_candidate_capture.py`:

- define a short cache TTL greater than the 250ms refresh interval;
- store bundle ID and `time.monotonic()` timestamp in a lock-protected module snapshot;
- add `cached_input_source_bundle_id()`;
- add `refresh_input_source_cache()` with an injectable native provider and clock;
- assert the Python main thread before native access in both the refresh entrypoint and `current_input_source_bundle_id()`;
- on provider failure, publish `""` with a fresh timestamp and return `""`.

**Step 4: Run the focused tests and confirm pass**

Run: `PYTHONPATH=src python -m pytest -q tests/test_ime_candidate_capture.py`

Expected: PASS.

### Task 2: Route background consumers through the cache

**Files:**
- Modify: `src/ominime/ime_candidate_capture.py`
- Modify: `src/ominime/kim_composer_capture.py`
- Test: `tests/test_ime_candidate_capture.py`
- Test: `tests/test_kim_composer_capture.py`

**Step 1: Write failing consumer tests**

Add tests proving the default `DoubaoCandidateReader` provider and the default `KimPreSubmitCapture` provider are `cached_input_source_bundle_id`, while explicitly injected providers still work.

For Kim, prepare a fake window and freeze it with the module cache populated; make the native function fail if called. Confirm the captured frame receives only the cached bundle ID.

**Step 2: Run focused tests and confirm failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_ime_candidate_capture.py tests/test_kim_composer_capture.py`

Expected: FAIL because the defaults still call the native TIS function.

**Step 3: Replace default providers**

- Make `DoubaoCandidateReader` default to `cached_input_source_bundle_id`.
- Make `KimPreSubmitCapture` default to the same cache reader.
- Remove the Kim helper that dynamically calls the native TIS function.
- Preserve all explicit provider injection behavior.

**Step 4: Run focused tests and confirm pass**

Run: `PYTHONPATH=src python -m pytest -q tests/test_ime_candidate_capture.py tests/test_kim_composer_capture.py`

Expected: PASS.

### Task 3: Refresh the cache from the menu-bar main thread

**Files:**
- Modify: `src/ominime/menu_bar_app.py`
- Modify: `tests/test_menu_bar_daily_counter.py`

**Step 1: Write failing lifecycle tests**

Extend the rumps test stub so timer instances expose their callback, interval, started state, and stopped state. Add tests proving:

- app initialization performs one immediate input-source refresh;
- it creates and starts a 250ms timer for later refreshes;
- invoking the timer callback refreshes again;
- `_quit()` stops both the input-source timer and the existing stats timer.

Stub delayed background startup so the lifecycle test cannot create real services or listeners.

**Step 2: Run focused tests and confirm failure**

Run: `PYTHONPATH=src python -m pytest -q tests/test_menu_bar_daily_counter.py`

Expected: FAIL because the input-source timer is not implemented.

**Step 3: Implement the timer lifecycle**

In `OmniMeMenuBarApp`:

- import the cache refresh function;
- refresh once during main-thread initialization;
- create `rumps.Timer(self._refresh_input_source, 0.25)` and start it;
- implement the timer callback as a direct refresh call;
- stop the timer in `_quit()`.

Keep the timer alive while recording is paused so the cache is fresh on resume.

**Step 4: Run focused tests and confirm pass**

Run: `PYTHONPATH=src python -m pytest -q tests/test_menu_bar_daily_counter.py`

Expected: PASS.

### Task 4: Verify, integrate, deploy, and monitor

**Files:**
- Verify all changed source, tests, and plan files.

**Step 1: Run targeted regression tests**

Run: `PYTHONPATH=src python -m pytest -q tests/test_ime_candidate_capture.py tests/test_kim_composer_capture.py tests/test_menu_bar_daily_counter.py tests/test_keyboard_listener_capture.py`

Expected: PASS.

**Step 2: Run the full suite**

Run: `PYTHONPATH=src python -m pytest -q`

Expected: PASS with no failures.

**Step 3: Inspect the exact diff and commit only owned files**

Run: `git diff --check` and `git status --short`.

Commit the implementation and tests on `codex/input-source-main-thread-cache` without staging unrelated files.

**Step 4: Integrate to clean `main` and push GitHub**

- Confirm the primary worktree has no tracked local changes.
- Merge the feature branch into `main` without rewriting history.
- Push `main` to `origin`.

**Step 5: Deploy and validate runtime health**

- Record the latest existing Python crash-report timestamp and current launchd crash counters.
- Restart `gui/$(id -u)/com.ominime.app` through launchctl.
- Verify `/api/health`, PID stability, and launchd state over multiple refresh intervals.
- Confirm no new `Python-*.ips` report appears after deployment and `successive crashes` does not increase.

If any verification gate fails, stop deployment progression, preserve the logs, and fix or roll back before reporting success.
