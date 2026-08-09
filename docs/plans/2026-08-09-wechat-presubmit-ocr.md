# WeChat Pre-Submit OCR Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Save the exact text sent with Enter in WeChat when Accessibility, Doubao candidate, and committed key-event text are unavailable.

**Architecture:** Reuse the proven legacy Kim pre-submit window capture, but make its ROI and failure prefix application-specific. The EventTap callback freezes only a prepared window; the serialized worker preserves the existing source priority and runs local Vision OCR only as the last content fallback.

**Tech Stack:** Python 3.14, PyObjC Quartz/Vision, pytest, SQLite diagnostics.

---

### Task 1: Add an application-specific WeChat composer recognizer

**Files:**
- Modify: `src/ominime/kim_composer_capture.py`
- Create: `src/ominime/wechat_composer_capture.py`
- Create: `tests/test_wechat_composer_capture.py`

**Step 1: Write the failing tests**

Add tests that instantiate `WeChatPreSubmitCapture` and assert:

```python
assert WECHAT_COMPOSER_ROI.x == 0.35
assert capture.recognize(frame) == ("微信验收", None)
assert empty.recognize(frame) == ("", "wechat_ocr_empty")
assert clipped.recognize(frame) == ("", "wechat_ocr_edge_clipped")
assert multiline.recognize(frame) == ("", "wechat_ocr_multiline_untrusted")
```

Also keep all existing Kim expectations unchanged.

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH="$PWD/src" /Users/liqiuhua/work/ominime/venv/bin/pytest tests/test_wechat_composer_capture.py tests/test_kim_composer_capture.py -q
```

Expected: FAIL because `wechat_composer_capture` does not exist.

**Step 3: Implement the minimal recognizer**

- Give `KimPreSubmitCapture` overridable `composer_roi` and `failure_prefix` class attributes.
- Build failure codes through one helper so existing `kim_ocr_*` codes remain unchanged.
- Use `self.composer_roi` for Vision and edge checks.
- Add `WeChatPreSubmitCapture` as a small subclass with:

```python
WECHAT_COMPOSER_ROI = NormalizedRect(0.35, 0.01, 0.63, 0.21)

class WeChatPreSubmitCapture(KimPreSubmitCapture):
    composer_roi = WECHAT_COMPOSER_ROI
    failure_prefix = "wechat_ocr"
```

**Step 4: Run tests to verify they pass**

Run the command from Step 2.

Expected: all WeChat and Kim component tests pass.

**Step 5: Commit**

```bash
git add src/ominime/kim_composer_capture.py src/ominime/wechat_composer_capture.py tests/test_wechat_composer_capture.py
git commit -m "feat: recognize WeChat composer locally"
```

### Task 2: Freeze WeChat text before Enter and preserve source priority

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Write the failing listener tests**

Add tests proving:

- ordinary WeChat keydown prepares the WeChat capture off the EventTap callback;
- unmodified Enter freezes a prepared WeChat frame;
- AX content still wins without invoking OCR;
- degraded WeChat uses Doubao candidate, then committed key-event text, then `wechat_presubmit_ocr`;
- trusted WeChat OCR emits exact content and source `wechat_presubmit_ocr`;
- OCR failure continues to `degraded_count_unreadable` with only `wechat_ocr_failure` diagnostics;
- Kim still emits `kim_presubmit_ocr`.

**Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONPATH="$PWD/src" /Users/liqiuhua/work/ominime/venv/bin/pytest tests/test_keyboard_listener_capture.py -q
```

Expected: new WeChat assertions fail because only bundle `Kem` is wired to pre-submit capture.

**Step 3: Implement the minimal listener mapping**

- Add constructor injection for `wechat_composer_capture`.
- Store captures by bundle ID rather than adding a second parallel conditional tree.
- In the worker, call `prepare(pid)` for either supported capture on non-Enter keydown.
- In the EventTap callback, call only the matching prepared capture’s `freeze(pid)`.
- In degraded submission processing, preserve current priority and call matching OCR only after all text sources fail.
- Emit application-specific source and diagnostic keys without logging OCR text or image data.

**Step 4: Run listener and related tests**

Run:

```bash
PYTHONPATH="$PWD/src" /Users/liqiuhua/work/ominime/venv/bin/pytest tests/test_keyboard_listener_capture.py tests/test_wechat_composer_capture.py tests/test_kim_composer_capture.py tests/test_submission_diagnostics.py -q
```

Expected: all related tests pass.

**Step 5: Commit**

```bash
git add src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py
git commit -m "feat: capture WeChat text before Enter"
```

### Task 3: Document, review, deploy, and perform live acceptance

**Files:**
- Modify: `README.md`

**Step 1: Update the user-facing privacy description**

State that legacy Kim and WeChat may use a local, in-memory view of only the composer when ordinary text APIs fail, and that images are neither saved nor uploaded.

**Step 2: Run the full verification suite**

Run:

```bash
PYTHONPATH="$PWD/src" /Users/liqiuhua/work/ominime/venv/bin/pytest -q
git diff --check
```

Expected: all tests pass with only the two existing warnings.

**Step 3: Request independent review**

Review for EventTap latency, ROI leakage into chat history, source-priority regressions, incomplete-text acceptance, and privacy-safe diagnostics. Resolve every Critical or Important finding with a failing test first.

**Step 4: Commit documentation**

```bash
git add README.md
git commit -m "docs: explain WeChat local text recovery"
```

**Step 5: Merge and deploy**

- Fast-forward the reviewed branch into clean `main` without staging unrelated user files.
- Re-run the full test suite on `main`.
- Restart `com.ominime.app` and verify `/api/health` reports recording.

**Step 6: Perform real WeChat acceptance**

Ask the user to send a unique short, single-line message with Enter. Verify the newest WeChat diagnostic is `persist_text`, source is `wechat_presubmit_ocr`, and the stored database content exactly matches the sent message.
