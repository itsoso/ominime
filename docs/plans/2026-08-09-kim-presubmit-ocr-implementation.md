# Old Kim Pre-submit OCR Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist visible Chinese message text from the legacy Kim (`Kem`) composer when Accessibility and Doubao candidate APIs expose no content.

**Architecture:** Add an isolated macOS component that freezes the exact legacy Kim window on Enter key-down and performs local Vision OCR later on the serialized event worker. Carry the in-memory frame on the queued raw event, prefer existing AX and confirmed-candidate sources, and use OCR only before the current count-only fallback.

**Tech Stack:** Python 3, PyObjC Quartz/ApplicationServices, macOS Vision framework, pytest, existing keyboard event worker and SQLite diagnostics

---

### Task 1: Pure Kim OCR trust and line assembly

**Files:**
- Create: `src/ominime/kim_composer_capture.py`
- Create: `tests/test_kim_composer_capture.py`

**Step 1: Write the failing line-assembly tests**

Define an immutable `RecognizedLine(text, x, y, width, height)` and tests that
prove `assemble_recognized_text()`:

- strips empty lines;
- orders Vision observations top-to-bottom and left-to-right;
- joins separate visual rows with newlines;
- rejects known legacy Kim chrome-only labels such as the send hint;
- bounds output to 4,000 characters.

Use an API shaped as:

```python
lines = (
    RecognizedLine("第二行", 0.1, 0.2, 0.3, 0.1),
    RecognizedLine("第一行", 0.1, 0.8, 0.3, 0.1),
)
assert assemble_recognized_text(lines) == "第一行\n第二行"
```

**Step 2: Run the test and verify RED**

Run: `venv/bin/pytest tests/test_kim_composer_capture.py -q`

Expected: FAIL because `ominime.kim_composer_capture` does not exist.

**Step 3: Implement the minimal pure values and functions**

Add `RecognizedLine`, a 4,000-character bound, stable row grouping based on
observation height, and a small exact chrome-label denylist. Do not add image or
native framework code yet.

**Step 4: Add failing trust tests**

Add tests for `ocr_text_is_trusted(text, input_source_bundle_id)`:

- Simplified Chinese text is trusted under Doubao;
- Latin pinyin and apostrophes are rejected under Doubao so candidate Enter is
  not mistaken for message submission;
- normalized non-empty Latin text remains allowed under non-Doubao sources;
- empty text is always rejected.

**Step 5: Run the trust tests and verify RED**

Run: `venv/bin/pytest tests/test_kim_composer_capture.py -q`

Expected: FAIL because the trust function is missing.

**Step 6: Implement the minimal trust function**

Require at least one CJK Unified Ideograph when the exact input source is
`com.bytedance.inputmethod.doubaoime`. Keep the function pure and do not persist
or log rejected text.

**Step 7: Run the module tests and verify GREEN**

Run: `venv/bin/pytest tests/test_kim_composer_capture.py -q`

Expected: PASS.

**Step 8: Commit the pure OCR rules**

```bash
git add src/ominime/kim_composer_capture.py tests/test_kim_composer_capture.py
git commit -m "feat: define trusted Kim OCR text"
```

### Task 2: Freeze the legacy Kim frame and run local Vision OCR

**Files:**
- Modify: `src/ominime/kim_composer_capture.py`
- Modify: `tests/test_kim_composer_capture.py`

**Step 1: Write failing window-selection and capture tests**

Inject fake window and image providers into `KimPreSubmitCapture` and verify:

- only visible layer-zero windows owned by the exact target PID are eligible;
- the largest eligible window is selected instead of Electron utility windows;
- invalid PIDs, missing windows, and image-provider failures return `None`;
- a successful `freeze()` returns an immutable in-memory frame with the target
  PID, image handle, dimensions, and capture timestamp.

**Step 2: Run the focused tests and verify RED**

Run: `venv/bin/pytest tests/test_kim_composer_capture.py -q -k 'freeze or window'`

Expected: FAIL because `KimPreSubmitCapture` is missing.

**Step 3: Implement Quartz freezing with lazy imports**

Use `CGWindowListCopyWindowInfo` with on-screen and desktop-exclusion options.
Filter by PID, layer, and a minimum normal-window size, then use
`CGWindowListCreateImageFromArray` to copy the selected window. Keep all Quartz
access lazy and catch native failures by returning `None`.

**Step 4: Write failing recognition tests**

Inject an OCR provider that returns `RecognizedLine` values and verify
`recognize(frame)`:

- applies only the fixed lower-center legacy Kim composer region;
- assembles and validates text using Task 1 rules;
- returns `(text, None)` for trusted content;
- returns an empty string plus a non-content failure code for empty OCR,
  uncommitted Doubao Latin text, or native OCR failure.

**Step 5: Run the recognition tests and verify RED**

Run: `venv/bin/pytest tests/test_kim_composer_capture.py -q -k recognize`

Expected: FAIL because recognition is missing.

**Step 6: Implement local Vision recognition**

Load `/System/Library/Frameworks/Vision.framework` through PyObjC at runtime.
Create `VNRecognizeTextRequest` with accurate recognition, Simplified Chinese
and English languages, and a Kim-specific region of interest that excludes the
formatting toolbar and bottom send hint. Use
`VNImageRequestHandler.initWithCGImage_options_`; never serialize the image.

**Step 7: Run the component tests and verify GREEN**

Run: `venv/bin/pytest tests/test_kim_composer_capture.py -q`

Expected: PASS.

**Step 8: Commit the native component**

```bash
git add src/ominime/kim_composer_capture.py tests/test_kim_composer_capture.py
git commit -m "feat: capture legacy Kim composer locally"
```

### Task 3: Freeze frames in the event callback without changing other apps

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Write failing callback-scope tests**

Inject a fake Kim capture object into `KeyboardListener` and test that:

- exact `Kem` unmodified Enter key-down calls `freeze(target_pid)` once and
  attaches the frame to `RawKeyboardEvent`;
- Kima (`Kim`), WeChat, normal character keys, key-up, and modified Enter do not
  freeze a frame;
- a capture exception attaches no frame and the callback still returns the
  original native event.

**Step 2: Run the callback tests and verify RED**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k kim_presubmit`

Expected: FAIL because the listener has no Kim capture dependency or raw-event
frame field.

**Step 3: Implement the minimal callback integration**

- Add optional `kim_composer_capture` injection and default it to
  `KimPreSubmitCapture()`.
- Add `pre_submit_frame: object | None = None` to `RawKeyboardEvent`.
- In `_event_callback`, call `freeze()` only after exact bundle, event type,
  keycode, and modifier checks pass.
- Keep OCR out of the callback and preserve the original event return value.

**Step 4: Run focused callback tests and verify GREEN**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k 'kim_presubmit or event_callback'`

Expected: PASS.

**Step 5: Commit event freezing**

```bash
git add src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py
git commit -m "feat: freeze legacy Kim text before Enter"
```

### Task 4: Persist trusted OCR content before count-only fallback

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `tests/test_keyboard_listener_capture.py`
- Modify: `README.md`

**Step 1: Write failing degraded-submission tests**

Construct `RawKeyboardEvent` values with fake in-memory frames and verify:

- degraded legacy Kim persists recognized Chinese text once with source
  `kim_presubmit_ocr`;
- existing confirmed Doubao candidate text still has higher priority;
- OCR is never called for Kima, WeChat, readable AX content, secure fields, or
  missing frames;
- OCR failure and untrusted pinyin retain the existing redacted count-only row;
- diagnostics contain only `kim_ocr_failure` and counts, not OCR text.

**Step 2: Run the persistence tests and verify RED**

Run: `venv/bin/pytest tests/test_keyboard_listener_capture.py -q -k kim_presubmit`

Expected: FAIL because the degraded submission path ignores the frame.

**Step 3: Implement the minimal fallback integration**

Pass `pre_submit_frame` from `_process_raw_event()` into
`_emit_submission_snapshot()`. After candidate and key-event-text sources fail,
call `recognize()` only for exact `Kem`. Normalize accepted text through
`normalize_submission_text()` and emit it with source `kim_presubmit_ocr`.
Attach only a failure code when falling back to count-only.

**Step 4: Update the user-facing README**

Replace the current claim that Kim/WeChat depends only on readable Doubao
candidates. Explain that legacy Kim can recover visible sent text locally and
that screenshots are neither saved nor uploaded; ambiguous content remains
count-only.

**Step 5: Run focused tests and verify GREEN**

Run:

```bash
venv/bin/pytest tests/test_kim_composer_capture.py tests/test_keyboard_listener_capture.py tests/test_submission_diagnostics.py -q
```

Expected: PASS.

**Step 6: Commit persistence and documentation**

```bash
git add src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py README.md
git commit -m "fix: persist legacy Kim text with local OCR"
```

### Task 5: Full verification, restart, and live Kim acceptance check

**Files:**
- No planned source changes

**Step 1: Run formatting and diff checks**

Run: `git diff --check`

Expected: no output and exit code 0.

**Step 2: Run the complete automated suite**

Run: `venv/bin/pytest -q`

Expected: all tests pass; do not hide the exit status through a pipe.

**Step 3: Review only the intended diff**

Run: `git status --short` and `git diff HEAD~4 --stat`

Expected: only the planned Kim source, tests, README, and plan documents are
tracked; unrelated user files remain untracked and unstaged.

**Step 4: Restart OmniMe services**

Use the repository's existing launch/restart scripts or launch-agent commands.
Verify both listener and web service PIDs are fresh, the runtime heartbeat is
current, recording status is active, and `/api/health` reports no runtime error.

**Step 5: Perform the live legacy Kim check**

Have the user send a short, unique Chinese message from `/Applications/Kim.app`
(bundle `Kem`). Query the newest capture diagnostic and input record.

Expected:

- `app_bundle_id` is `Kem`;
- `decision_action` is `persist_text`;
- `selected_source` is `kim_presubmit_ocr`;
- `content` is non-empty and matches the visible sent text;
- no image path or OCR content appears in diagnostics.

**Step 6: Commit any verification-only documentation correction if needed**

Do not create a success commit merely for running tests. If live validation
reveals a code defect, return to a new failing test before changing production
code.
