# User-Focused README Refresh Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the stale implementation-heavy README with an accurate, concise guide for ordinary OmniMe users.

**Architecture:** Treat the current working-tree code and tests as the source of truth. Organize README content by the user's journey—understand, install, authorize, use, protect data, troubleshoot—while linking detailed AI documents instead of duplicating them.

**Tech Stack:** Markdown, Python CLI (`argparse`), macOS Accessibility, FastAPI, SQLite

---

### Task 1: Build the README fact checklist

**Files:**

- Read: `src/ominime/main.py`
- Read: `src/ominime/config.py`
- Read: `src/ominime/keyboard_listener.py`
- Read: `src/ominime/submission_processor.py`
- Read: `src/ominime/web/api.py`
- Read: `src/ominime/database.py`
- Read: `scripts/install_app.sh`
- Read: `scripts/uninstall_app.sh`
- Read: `tests/test_keyboard_listener_capture.py`
- Read: `tests/test_web_health.py`

**Step 1: Confirm public commands and defaults**

Run:

```bash
PYTHONPATH=src python -m ominime.main --help
PYTHONPATH=src python -m ominime.main web --help
PYTHONPATH=src python -m ominime.main obsidian --help
```

Expected: commands include `app`, `web`, `monitor`, `report`, `stats`, `export`, and `obsidian`; Web defaults to port `8001`.

**Step 2: Confirm user-facing configuration**

Run:

```bash
rg -n 'input_capture_mode|day_timezone|storage_timezone|count_unreadable_submissions|capture_context_on_enter|ignored_apps' src/ominime/config.py
```

Expected: every README configuration key is present in `AppConfig`, persisted by `save`, and restored by `load`.

**Step 3: Confirm capture and privacy behavior**

Run:

```bash
rg -n 'focused_element_not_text_input|persist_count|persist_text|unsafe_clipboard_rejected|count-only|submit_snapshot' src/ominime tests
```

Expected: README claims map to implementation or tests.

### Task 2: Rewrite README for ordinary users

**Files:**

- Modify: `README.md`

**Step 1: Replace the opening and feature list**

Describe OmniMe as a local-first macOS activity review tool that records text at Enter submission boundaries, not a raw key stream. Highlight menu bar status, Web review, reports, Obsidian export, privacy modes, and optional AI.

**Step 2: Replace installation and first-run instructions**

Document the recommended install script, Accessibility permission, default `ominime`/`ominime app` launch, and how to confirm recording.

**Step 3: Correct usage documentation**

Use the current CLI commands and the `http://127.0.0.1:8001` Web address. Include `ominime obsidian` and useful date/output flags.

**Step 4: Explain capture behavior without internal implementation detail**

Explain Enter-only capture, trusted text-input focus, CJK/IME handling, count-only fallback, ignored apps, and reasons a submission may be skipped. Do not mention Rime.

**Step 5: Document data and privacy controls**

Document `~/.ominime/ominime.db`, logs, local-first storage, `enter-text` and `count-only`, ignored apps, context metadata, optional cloud AI, business-day timezone, and storage timezone.

**Step 6: Add user troubleshooting**

Include permission checks, recording status, `/api/health`, `/api/capture/diagnostics`, and the expected behavior for non-text focus or inaccessible fields.

**Step 7: Remove stale low-value sections**

Remove the synthetic report example, SQL schema, old module tree, stale changelog, old port, raw-key claims, and duplicated AI setup detail. Link the existing LLM guides.

### Task 3: Verify README against the current code

**Files:**

- Verify: `README.md`

**Step 1: Check stale terms and values**

Run:

```bash
if rg -n '鼠须管|Rime|rime_input|127\.0\.0\.1:8080|每一次输入|所有键盘输入' README.md; then exit 1; fi
```

Expected: exit `0` with no matches.

**Step 2: Check documented paths and links**

Run:

```bash
test -f scripts/install_app.sh
test -f scripts/uninstall_app.sh
test -f docs/LLM_BACKENDS.md
test -f docs/LOCAL_LLM_GUIDE.md
```

Expected: exit `0`.

**Step 3: Check Markdown and final diff**

Run:

```bash
git diff --check -- README.md
git diff -- README.md
```

Expected: no whitespace errors; diff contains only the approved user-focused rewrite plus the earlier Rime removal.

**Step 4: Run focused behavior tests supporting README claims**

Run:

```bash
venv/bin/python -m pytest -q tests/test_context_capture.py tests/test_keyboard_listener_capture.py tests/test_submission_privacy.py tests/test_web_health.py
```

Expected: all selected tests pass.
