# Chat Capture Stall Recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore reliable Kim and WeChat text capture after idle periods and for trusted visually wrapped OCR text without weakening Enter fail-open or privacy protections.

**Architecture:** Keep the EventTap callback limited to copying, marking, queuing, and suppressing a verified Enter pair. Give the worker a 750ms bounded window to complete cold AX security lookup and freeze the in-memory pre-submit frame, then replay immediately and run Vision afterward. Accept ordered multiline OCR only after removing known watermarks/repeated artifacts and retaining the existing edge, input-source, length, and physical-key-count gates.

**Tech Stack:** Python 3.10+, PyObjC Quartz/ApplicationServices/Vision, pytest, macOS LaunchAgents.

---

### Task 1: Expand the cold-AX fail-open budget

**Files:**
- Modify: `tests/test_keyboard_listener_capture.py`
- Modify: `src/ominime/keyboard_listener.py`

**Step 1: Write the failing watchdog budget test**

Add a test beside `test_pending_enter_watchdog_replays_when_worker_is_blocked` that replaces `threading.Timer` with a recording fake, queues a verified Kim Enter, and asserts the production interval is 0.75 seconds:

```python
def test_enter_replay_watchdog_allows_cold_ax_budget(monkeypatch):
    keyboard_listener, _ = import_keyboard_listener(monkeypatch)
    intervals = []

    class RecordingTimer:
        def __init__(self, interval, callback, args):
            intervals.append(interval)
            self.daemon = False

        def start(self):
            return None

        def cancel(self):
            return None

    monkeypatch.setattr(keyboard_listener.threading, "Timer", RecordingTimer)
    # Construct a running, identity-verified Kim listener and call _event_callback.

    assert intervals == [0.75]
```

Keep the existing real-timer test proving the watchdog still releases a marked keyDown/keyUp pair when the worker does not run.

**Step 2: Run the new test and verify RED**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py::test_enter_replay_watchdog_allows_cold_ax_budget -q
```

Expected: FAIL because the current interval is `0.2`.

**Step 3: Implement the minimal timeout change**

Change only the bounded watchdog constant:

```python
ENTER_REPLAY_TIMEOUT_SECONDS = 0.75
```

Do not move AX, screenshot, or Vision work into `_event_callback()` and do not change replay idempotency.

**Step 4: Run watchdog tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py -k 'watchdog or replay or full_worker_queue or secure_kim or count_only' -q
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add tests/test_keyboard_listener_capture.py src/ominime/keyboard_listener.py
git commit -m "fix: allow cold accessibility capture before replay"
```

### Task 2: Accept trusted multiline OCR while rejecting artifacts

**Files:**
- Modify: `tests/test_kim_composer_capture.py`
- Modify: `tests/test_wechat_composer_capture.py`
- Modify: `src/ominime/kim_composer_capture.py`

**Step 1: Write failing multiline acceptance tests**

Change the Kim and WeChat multiline fixtures to require ordered text instead of `multiline_untrusted`:

```python
assert multiline.recognize(frame) == ("第一行\n第二行", None)
assert multiline_wechat.recognize(_frame()) == ("第一行\n第二行", None)
```

Split the edge assertions into their own tests so bottom/top/left clipping still returns the existing `*_edge_clipped` codes.

Add a repeated-row safety test:

```python
assert repeated.recognize(frame) == (
    "",
    "kim_ocr_repeated_text_untrusted",
)
```

Update the horizontal prefix watermark fixture to expect only the non-watermark text after close variants of an observed tiled watermark are removed:

```python
assert capture.recognize(frame) == ("提交", None)
```

**Step 2: Run the tests and verify RED**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py -q
```

Expected: multiline acceptance and horizontal-prefix expectations fail against the current unconditional newline rejection/filtering.

**Step 3: Implement minimal multiline trust logic**

In `recognized_content_lines()`, when a tiled slanted watermark has been identified, remove close prefix variants even when a single variant is horizontal. Continue requiring an observed tiled watermark before applying this broader variant removal.

Add a small helper that rejects three or more identical normalized content lines:

```python
def repeated_ocr_text_is_untrusted(lines: tuple[RecognizedLine, ...]) -> bool:
    counts: dict[str, int] = defaultdict(int)
    for line in lines:
        counts[line.text.strip().casefold()] += 1
    return any(count >= 3 for count in counts.values())
```

In `recognize()`:

- retain edge clipping before assembling text;
- return `*_repeated_text_untrusted` for repeated artifacts;
- remove the unconditional `"\n" in text` rejection;
- retain empty, uncommitted input-source, native-error, and max-length behavior unchanged.

**Step 4: Run composer tests and verify GREEN**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py -q
```

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py src/ominime/kim_composer_capture.py
git commit -m "fix: accept trusted multiline chat OCR"
```

### Task 3: Verify multiline text reaches persistence gates

**Files:**
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Write the failing worker integration test**

Add a WeChat worker test modeled on the existing successful OCR fallback test. Configure the fake capture to return `"第一行\n第二行"`, record enough physical keys for `ocr_text_matches_physical_count()`, and assert:

```python
assert events[0].character == "第一行\n第二行"
assert events[0].modifiers["fallback_source"] == "wechat_presubmit_ocr"
assert events[0].modifiers["redacted_content"] is False
```

The test must exercise `_process_raw_event()` with a pending replay/frame path, not call the persistence helper directly.

**Step 2: Run the test and confirm behavior**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py -k 'wechat and multiline' -q
```

If it passes immediately, it documents the existing downstream gate now made reachable by Task 2. If it fails because normalization or count validation rejects the text, make only the smallest related production change and first add a focused failing assertion for that exact rejection.

**Step 3: Run the complete capture suite**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py tests/test_submission_privacy.py tests/test_submission_diagnostics.py -q
```

Expected: all selected tests pass; secure/ignored/count-only assertions remain green.

**Step 4: Commit test coverage**

```bash
git add tests/test_keyboard_listener_capture.py
git commit -m "test: cover multiline chat persistence"
```

### Task 4: Verify, review, integrate, and deploy

**Files:**
- Modify only if verification exposes a directly related defect.

**Step 1: Run static and dependency checks**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m compileall -q src tests
bash -n scripts/*.sh src/ominime/scripts/*.sh
/Users/liqiuhua/work/ominime/venv/bin/python -m pip check
git diff --check main...HEAD
```

Expected: all commands exit 0.

**Step 2: Run the full suite**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest -q
```

Expected: all tests pass; the known Starlette deprecation warning may remain.

**Step 3: Request independent review**

Use `superpowers:requesting-code-review`. Require no unresolved Critical or Important findings concerning callback safety, duplicate/missing Enter, secure/ignored/count-only screenshots, multiline artifact acceptance, or watchdog behavior.

**Step 4: Merge and push**

From the primary worktree, fetch `origin`, fast-forward the verified feature branch into `main`, rerun the full suite on main, and push `main`. Stage only explicit task files; preserve all unrelated untracked user files.

**Step 5: Restart and smoke test**

Restart:

```bash
launchctl kickstart -k "gui/$(id -u)/com.ominime.app"
launchctl kickstart -k "gui/$(id -u)/com.ominime.web"
```

Verify stable new PIDs, live heartbeat, `last_runtime_error: null`, and `127.0.0.1:8001` only.

**Step 6: Run real Kim/WeChat acceptance**

Ask the user to send one unique, longer-than-one-visual-line test from Kim and one from WeChat. Query the live diagnostics API and SQLite database. Require exact non-empty stored content with `kim_presubmit_ocr` and `wechat_presubmit_ocr`, no duplicate send, no new crash report, and no new `submission_contexts` row.
