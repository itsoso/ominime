# Kim App-Switch Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Preserve the verified `Kem` main-process identity across unrelated app activations so an immediate first Enter after returning to Kim can freeze the prepared composer.

**Architecture:** Keep verified identities keyed by PID instead of replacing the whole map on every activation. Update or remove only the activated supported PID, while the EventTap callback continues to require an exact frontmost PID, event PID, app name, and Bundle ID match; Bundle ID `Kim` remains unsupported.

**Tech Stack:** Python 3.14, PyObjC AppKit/Quartz, pytest, SQLite diagnostics.

---

### Task 1: Preserve supported composer identities across app switches

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Write the failing tests**

Add a test that prepares `("Kim", "Kem", 29805)`, activates ChatGPT, then simulates an immediate plain Enter after returning to Kim without another prepare. Assert that the Kim frame is frozen. Add a second assertion that activating `("Kima", "Kim", pid)` never creates a verified composer identity.

**Step 2: Run the focused tests and verify failure**

Run:

```bash
PYTHONPATH="$PWD/src" /Users/liqiuhua/work/ominime/venv/bin/pytest tests/test_keyboard_listener_capture.py -k "preserves_kem or ignores_kima" -q
```

Expected: the Kem preservation test fails because unsupported app activation currently replaces `_target_app_identities` with an empty dictionary.

**Step 3: Implement the minimal cache update**

In `_prepare_activated_composer`, return without changing verified identities for unsupported bundles. For supported bundles, set only `self._target_app_identities[target_pid]` after successful `prepare`; on failure remove only that PID. Do not change the EventTap matching conditions.

**Step 4: Run focused, related, and full tests**

Run:

```bash
PYTHONPATH="$PWD/src" /Users/liqiuhua/work/ominime/venv/bin/pytest tests/test_keyboard_listener_capture.py -q
PYTHONPATH="$PWD/src" /Users/liqiuhua/work/ominime/venv/bin/pytest -q
git diff --check
```

Expected: all tests pass with only the two pre-existing warnings.

**Step 5: Commit, review, deploy, and accept**

Stage only the two implementation files, commit, request independent Critical/Important review, fast-forward `main`, rerun the full suite, and restart `com.ominime.app`. Ask the user to send `Kim短句验收0810` from `/Applications/Kim.app` and verify exact stored text with source `kim_presubmit_ocr`; then resume the pending WeChat acceptance.

### Task 2: Exclude known tiled watermarks before edge checks

**Files:**
- Modify: `src/ominime/kim_composer_capture.py`
- Modify: `tests/test_kim_composer_capture.py`

**Step 1:** Add a failing regression with the observed `Kim缓存验收0810` coordinates and tiled `panbaokun` variants touching the ROI edges.

**Step 2:** Extract the existing chrome/watermark observation filter and reuse it before both edge validation and text assembly. Do not alter the ROI or edge thresholds.

**Step 3:** Run Kim component, listener, and full test suites; verify the retained live draft locally in memory before deployment.
