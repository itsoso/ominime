# Doubao Candidate Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist confirmed Doubao Chinese candidate selections for Kim and WeChat while preserving count-only behavior whenever the composer cannot be trusted.

**Architecture:** Add an isolated runtime reader that extracts Doubao candidate accessibility text and validates the candidate window against the lower region of the target app window. Keep all editing behavior in a small pure in-memory state machine, then connect it to the existing serialized keyboard-event worker so candidate Enter and message Enter have distinct outcomes.

**Tech Stack:** Python 3, PyObjC AppKit/ApplicationServices/Quartz, pytest, existing SQLite diagnostics

---

## Review Hardening Applied

The implementation adds stricter safety gates discovered during independent
review:

- verify the active macOS input-source bundle, not merely a running Doubao
  process;
- bind candidate text and geometry to the same AX window;
- never promote raw Latin/pinyin pre-edit text to submitted content;
- expire uncommitted candidate snapshots after five seconds while retaining
  confirmed content for the normal session timeout, and revalidate before every
  Space, number, or Enter candidate commit even after an early key-up miss;
- clear in-memory candidate content on target-app/PID changes, mouse clicks,
  and editing commands that cannot be reconstructed safely;
- attach a non-content failure code to count-only capture diagnostics.

These gates deliberately prefer a count-only record over partial or ambiguous
text.

### Task 1: Pure candidate geometry and composition state

**Files:**
- Create: `src/ominime/ime_candidate_capture.py`
- Create: `tests/test_ime_candidate_capture.py`

**Step 1: Write the failing geometry tests**

Define tests for these public values and functions:

```python
from ominime.ime_candidate_capture import Rect, candidate_is_in_composer


def test_candidate_inside_lower_target_region_is_trusted():
    target = Rect(x=2000, y=100, width=1200, height=800)
    candidate = Rect(x=2500, y=760, width=400, height=64)
    assert candidate_is_in_composer(candidate, target)


def test_candidate_near_top_search_field_is_rejected():
    target = Rect(x=2000, y=100, width=1200, height=800)
    candidate = Rect(x=2500, y=180, width=400, height=64)
    assert not candidate_is_in_composer(candidate, target)
```

Also reject candidates whose center is outside the target horizontally or
below/above the target bounds.

**Step 2: Run the geometry tests to verify they fail**

Run: `venv/bin/pytest tests/test_ime_candidate_capture.py -q`

Expected: FAIL because the module does not exist.

**Step 3: Implement immutable runtime values and geometry**

Add:

```python
DOUBAO_BUNDLE_ID = "com.bytedance.inputmethod.doubaoime"
SUPPORTED_TARGET_BUNDLE_IDS = frozenset({"Kem", "com.tencent.xinWeChat"})

@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

@dataclass(frozen=True)
class CandidateSnapshot:
    candidates: tuple[str, ...]
    target_pid: int
    captured_at: float
```

`candidate_is_in_composer()` must require the candidate center to be inside the
target horizontally and vertically and at or below `target.y +
target.height * 0.55`.

**Step 4: Write failing state-machine tests**

Cover independent transitions:

- pending pinyin plus snapshot plus Space commits candidate zero;
- number keys 1–9 commit the corresponding visible candidate;
- left/right arrow keys clamp and move the selected index;
- Enter with an active snapshot returns `candidate_committed=True` and never a
  submission;
- the next Enter with no active snapshot returns the composed submission once;
- backspace edits pending pre-edit first, then confirmed composed text;
- raw pinyin is never returned as submitted content;
- trusted Latin text is accepted only after a validated candidate session;
- target PID change and timeout erase pending and confirmed content.

Use a pure API shaped as:

```python
state = DoubaoCompositionState(timeout_seconds=30, clock=fake_clock)
state.record_printable("c", target_pid=123)
state.update_candidates(CandidateSnapshot(("测试", "策士"), 123, fake_clock()))
result = state.handle_key(keycode=49, text=" ", target_pid=123)
assert result.candidate_committed
assert state.pop_submission(target_pid=123) == "测试"
```

**Step 5: Run the state tests to verify they fail**

Run: `venv/bin/pytest tests/test_ime_candidate_capture.py -q -k composition`

Expected: FAIL because `DoubaoCompositionState` is not implemented.

**Step 6: Implement the minimal state machine**

Keep only these fields in memory: target PID, updated time, candidates, selected
index, pending raw pre-edit, confirmed content, and `composer_trusted`. Bound
all text by the existing 4,000-character submission limit. `handle_key()` must
return a small immutable result indicating whether a candidate was committed;
it must never persist data itself.

**Step 7: Run the candidate module tests**

Run: `venv/bin/pytest tests/test_ime_candidate_capture.py -q`

Expected: PASS.

**Step 8: Commit the pure candidate component**

```bash
git add src/ominime/ime_candidate_capture.py tests/test_ime_candidate_capture.py
git commit -m "feat: model Doubao candidate composition"
```

### Task 2: Runtime Doubao accessibility reader

**Files:**
- Modify: `src/ominime/ime_candidate_capture.py`
- Modify: `tests/test_ime_candidate_capture.py`

**Step 1: Write failing accessibility extraction tests**

Use fake AX nodes and injected attribute/window providers to prove:

- only non-empty `AXStaticText` values are returned;
- duplicate accessibility nodes/values are deduplicated in traversal order;
- traversal is bounded and ignores other roles;
- no result is returned unless the exact target bundle is supported;
- no result is returned unless the exact running process bundle is Doubao;
- no result is returned when no Doubao window is anchored in the lower target
  composer region;
- a valid reader result includes candidates, target PID, and capture time.

**Step 2: Run the reader tests to verify they fail**

Run: `venv/bin/pytest tests/test_ime_candidate_capture.py -q -k reader`

Expected: FAIL because `DoubaoCandidateReader` is not implemented.

**Step 3: Implement the runtime reader with lazy native imports**

`DoubaoCandidateReader.read(target_pid, target_bundle_id)` must:

1. reject unsupported bundle IDs and invalid PIDs immediately;
2. find a running application whose bundle ID exactly equals
   `com.bytedance.inputmethod.doubaoime`;
3. create that process's AX application element and traverse its `AXWindows`
   and children for bounded `AXStaticText` values;
4. enumerate on-screen Quartz windows and parse their bounds into `Rect`;
5. accept only when a visible Doubao window is inside the lower region of a
   visible window owned by `target_pid`;
6. return a `CandidateSnapshot`, or `None` on AX errors/ambiguity.

Keep AppKit, ApplicationServices, and Quartz imports inside the runtime methods
so unit tests and non-macOS imports do not require live native services. Do not
log or persist candidate strings on failure.

**Step 4: Run all reader tests**

Run: `venv/bin/pytest tests/test_ime_candidate_capture.py -q`

Expected: PASS.

**Step 5: Commit the native reader**

```bash
git add src/ominime/ime_candidate_capture.py tests/test_ime_candidate_capture.py
git commit -m "feat: read trusted Doubao candidates"
```

### Task 3: Connect candidate composition to keyboard events

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Write failing listener transition tests**

Inject a fake candidate reader into `KeyboardListener` and add tests proving:

- key-down records pending printable input and key-up refreshes the candidate
  snapshot after the application has processed the key;
- unsupported apps never call the candidate reader;
- Space and number candidate commits do not enter the chat submission path;
- Enter with an active candidate emits only an `ime_candidate_commit`
  diagnostic and consumes its matching key-up;
- the next Enter without candidates proceeds to normal chat submission;
- arrow and backspace events update candidate state without leaking pre-edit
  text;
- PID changes expire the old in-memory candidate state.

Construct `RawKeyboardEvent` values directly so the tests exercise the existing
single-threaded `_process_raw_event()` ordering.

**Step 2: Run the listener transition tests to verify they fail**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k doubao`

Expected: FAIL because `KeyboardListener` does not own candidate state or read
candidate snapshots.

**Step 3: Add the minimal listener integration**

- Allow `KeyboardListener(..., candidate_reader=None)` and default to
  `DoubaoCandidateReader()`.
- Store one `DoubaoCompositionState` per supported `(app_name, bundle_id)`.
- On compatible unmodified key-down, update only the in-memory state.
- On compatible non-commit key-up, call the reader and update/clear the active
  candidate snapshot.
- Do not reread the window on Space, digit, arrow, or Enter key-up when doing so
  could resurrect a just-consumed stale snapshot.
- Before the normal Enter decision tree, consume active candidate Enter and
  emit a diagnostic with reason `ime_candidate_commit` and source
  `doubao_candidate_ax`.
- Clear candidate state when an ignored/secure context or target PID change is
  detected.

Do not add new threads or blocking waits; all transitions stay in the existing
serialized event worker.

**Step 4: Run focused listener tests**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'doubao or enter_keydown_and_keyup or secure_field'`

Expected: PASS.

**Step 5: Commit listener state integration**

```bash
git add src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py
git commit -m "feat: track Doubao composition events"
```

### Task 4: Persist candidate text on the real chat Enter

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Write failing persistence tests**

Add tests proving:

- degraded Kim persists confirmed candidate content with fallback source
  `doubao_candidate_text`;
- degraded WeChat does the same;
- confirmed text is consumed exactly once;
- candidate content is preferred over the old count-only degraded fallback;
- secure readable context discards candidate content and persists nothing;
- an untrusted/missing candidate still produces the existing redacted
  `degraded_count_unreadable` record;
- other applications retain the existing strict skip behavior.

**Step 2: Run persistence tests to verify they fail**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'doubao and (persist or secure or count)'`

Expected: FAIL because `_emit_submission_snapshot()` does not consume composed
candidate content.

**Step 3: Add candidate text to the degraded compatibility decision**

After secure-context rejection and before the old CJK/count fallback:

```python
candidate_content = self._pop_doubao_submission(app_name, bundle_id, target_pid)
if candidate_content:
    self._emit_submission_event(
        ...,
        content=candidate_content,
        fallback_source="doubao_candidate_text",
        physical_key_count=physical_key_count,
    )
    return
```

Normalize and length-check content with the existing submission helpers. Ensure
all success, skip, secure, and timeout paths clear the corresponding candidate
state without changing the generic capture policy.

**Step 4: Run focused capture tests**

Run: `venv/bin/pytest tests/test_ime_candidate_capture.py tests/test_keyboard_listener_capture.py -q`

Expected: PASS.

**Step 5: Commit candidate persistence**

```bash
git add src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py
git commit -m "fix: persist Doubao text in Kim and WeChat"
```

### Task 5: Regression verification and deployment

**Files:**
- Verify: `src/ominime/ime_candidate_capture.py`
- Verify: `src/ominime/keyboard_listener.py`
- Verify: `tests/test_ime_candidate_capture.py`
- Verify: `tests/test_keyboard_listener_capture.py`
- Verify: `docs/plans/2026-08-08-doubao-candidate-capture-design.md`
- Verify: `docs/plans/2026-08-08-doubao-candidate-capture-implementation.md`

**Step 1: Run focused tests**

Run: `venv/bin/pytest tests/test_ime_candidate_capture.py tests/test_keyboard_listener_capture.py tests/test_context_capture.py tests/test_database_capture_diagnostics.py -q`

Expected: PASS with zero failures.

**Step 2: Run the complete suite**

Run: `venv/bin/pytest -q`

Expected: PASS with zero failures. Read pytest's final exit status directly; do
not pipe it through `tail`.

**Step 3: Review the exact diff**

Run: `git diff --check && git status --short`

Expected: only the planned tracked files plus the user's pre-existing untracked
files. Review the complete diff for the planned source and tests.

**Step 4: Commit only remaining planned files**

Stage explicit paths only; never use `git add -A`.

**Step 5: Restart and validate services**

Restart the configured `com.ominime.app` and `com.ominime.web` launch agents.
Verify both processes are running, `http://127.0.0.1:8001/health` reports
recording active, and the runtime heartbeat is fresh.

**Step 6: Validate real content capture**

Send one new Doubao-composed message in Kim and one in WeChat. Confirm that each
creates a new non-empty input record whose diagnostics select
`doubao_candidate_text`. If no real message is sent during automated work,
report deployment as healthy but explicitly leave this final content check for
the user instead of claiming it passed.
