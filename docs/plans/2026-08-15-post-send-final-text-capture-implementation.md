# Post-Send Final Text Capture Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Capture the final text sent from Kim and WeChat after the message appears, without suppressing Enter or persisting chat context or images.

**Architecture:** Convert a verified chat Enter into an immutable `SendIntent`, then let a dedicated bounded coordinator query trusted local sources and fall back to stabilized local Vision OCR of the newly added outgoing bubble. Keep EventTap fail-open, reuse the existing `KeyEvent` persistence path, and preserve the historical database without adding context writes.

**Tech Stack:** Python 3.10+, PyObjC Quartz/ApplicationServices/Vision, dataclasses/protocols, pytest, macOS LaunchAgents.

---

### Task 1: Define the post-send capture contract

**Files:**
- Create: `src/ominime/post_send_capture.py`
- Create: `tests/test_post_send_capture.py`

**Step 1: Write the failing value-object and source-chain tests**

Add tests that define the immutable request/result contract and prove that the first trusted source wins while unavailable sources fall through:

```python
def test_source_chain_returns_first_trusted_result():
    intent = SendIntent(
        intent_id="send-1",
        submitted_at=10.0,
        timestamp=datetime(2026, 8, 15, 12, 0),
        app_name="Kim",
        bundle_id="Kem",
        target_pid=123,
        modifiers={},
        physical_key_count=4,
        validation_text="测试",
        baseline=None,
    )
    chain = MessageSourceChain(
        [FakeSource(SourceResult.unavailable("ax_unavailable")),
         FakeSource(SourceResult.success("测试", "kim_postsend_ocr", "bubble-1"))]
    )

    assert chain.read(intent).content == "测试"
```

Also test empty text, overlong text, mismatched PID, stale observations and a source exception. Exceptions must become a named failure and allow the next source to run.

**Step 2: Run the focused test and verify RED**

Run:

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_post_send_capture.py -q
```

Expected: FAIL because `ominime.post_send_capture` does not exist.

**Step 3: Implement the minimal contract**

Create immutable types and a protocol:

```python
@dataclass(frozen=True)
class SendIntent:
    intent_id: str
    submitted_at: float
    timestamp: datetime
    app_name: str
    bundle_id: str
    target_pid: int
    modifiers: dict
    physical_key_count: int
    validation_text: str
    baseline: object | None

@dataclass(frozen=True)
class SourceResult:
    content: str = ""
    source: str | None = None
    message_identity: str | None = None
    confidence: float | None = None
    observed_at: float | None = None
    failure_reason: str | None = None

class MessageSource(Protocol):
    def read(self, intent: SendIntent) -> SourceResult: ...
```

Add named constructors for success/unavailable and a `MessageSourceChain` that normalizes text, enforces `MAX_TRUSTED_SUBMISSION_CHARS`, catches each source exception into diagnostics, and never treats empty content as success.

**Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2.

Expected: all tests in `tests/test_post_send_capture.py` pass.

**Step 5: Commit**

```bash
git add src/ominime/post_send_capture.py tests/test_post_send_capture.py
git commit -m "feat: define post-send capture contract"
```

### Task 2: Build a bounded asynchronous coordinator

**Files:**
- Modify: `src/ominime/post_send_capture.py`
- Modify: `tests/test_post_send_capture.py`

**Step 1: Write failing retry, stability, ordering, and shutdown tests**

Use injected `clock`, `wait` and fake sources. Cover:

- retries occur at `0.15, 0.35, 0.65, 1.0, 1.5, 2.0` seconds relative to Enter;
- a structured result with a unique message ID completes immediately;
- OCR requires two identical stable results before completion;
- tasks for one PID finish in Enter order;
- queue full reports `post_send_queue_full` without waiting;
- `stop()` rejects new tasks and releases each task baseline;
- source exceptions do not terminate the worker.

Example assertion:

```python
assert completed == [
    CaptureOutcome(
        intent_id="send-1",
        content="最终文本",
        source="kim_postsend_ocr",
        message_identity="bubble:123:42",
        failure_reason=None,
    )
]
```

**Step 2: Run the new tests and verify RED**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_post_send_capture.py -k 'coordinator or queue or shutdown' -q
```

Expected: FAIL because the coordinator is absent.

**Step 3: Implement `PostSendCaptureCoordinator`**

Use `queue.Queue(maxsize=64)` and one daemon worker. `submit()` must use `put_nowait()` and return a boolean. The worker computes remaining delay from `intent.submitted_at`, never sleeps past task expiry, and calls separate success/diagnostic callbacks. Keep the OCR stability state inside the task, not globally.

Do not spawn one thread or timer per Enter. Do not retry forever. Clear references to `baseline` in `finally`.

**Step 4: Run the focused tests and verify GREEN**

Run the command from Step 2.

Expected: all selected coordinator tests pass.

**Step 5: Commit**

```bash
git add src/ominime/post_send_capture.py tests/test_post_send_capture.py
git commit -m "feat: coordinate bounded post-send reads"
```

### Task 3: Add an in-memory chat-window baseline sampler

**Files:**
- Create: `src/ominime/chat_window_capture.py`
- Create: `tests/test_chat_window_capture.py`

**Step 1: Write failing sampler tests**

Test with injected window/image providers:

- the frontmost eligible layer-zero window for the verified PID is selected;
- ordinary typing schedules at most one capture per 250ms;
- capture runs on the sampler worker, never the caller/EventTap thread;
- only the newest frame for the active PID remains referenced;
- `take_baseline(pid)` transfers and removes the cached frame;
- PID/window changes invalidate the baseline;
- provider failure returns `baseline_unavailable` and the worker survives;
- no image is serialized or passed to diagnostics.

**Step 2: Run tests and verify RED**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_chat_window_capture.py -q
```

Expected: FAIL because the module does not exist.

**Step 3: Implement the minimal sampler**

Move or reuse only the generic native pieces currently embedded in `kim_composer_capture.py`: `WindowInfo`, target-window selection and `CGWindowListCreateImageFromArray`. Add:

```python
@dataclass(frozen=True)
class WindowFrame:
    image: object
    window_id: int
    target_pid: int
    width: float
    height: float
    captured_at: float

class ChatWindowBaselineSampler:
    def schedule(self, target_pid: int) -> bool: ...
    def take_baseline(self, target_pid: int) -> WindowFrame | None: ...
    def stop(self) -> None: ...
```

Use one bounded/coalescing worker and a 250ms minimum interval. Keep at most one frame total, not one per historical PID.

**Step 4: Run tests and verify GREEN**

Run the command from Step 2.

Expected: all sampler tests pass.

**Step 5: Commit**

```bash
git add src/ominime/chat_window_capture.py tests/test_chat_window_capture.py
git commit -m "feat: cache in-memory chat window baselines"
```

### Task 4: Recognize a newly added outgoing message bubble

**Files:**
- Create: `src/ominime/chat_bubble_capture.py`
- Create: `tests/test_chat_bubble_capture.py`
- Modify: `src/ominime/kim_composer_capture.py`
- Modify: `src/ominime/wechat_composer_capture.py`

**Step 1: Write failing geometry and trust tests**

Build tests from synthetic `RecognizedLine` and image-difference fixtures. Require:

- Kim and WeChat profiles derive search bounds from actual frame dimensions;
- header, sidebar and composer chrome are excluded;
- wrapped lines in one outgoing bubble retain visual order;
- incoming/left-aligned and old unchanged bubbles are rejected;
- a new right-side bubble is accepted only when it overlaps the changed region;
- two identical messages sent consecutively receive different geometry/time identities;
- edge-clipped, repeated watermark, empty and overlong results are rejected;
- Doubao pinyin pre-edit rules are not applied to post-send bubbles, because rendered bubbles contain committed text;
- OCR never returns raw candidate text in a failure diagnostic.

**Step 2: Run tests and verify RED**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_chat_bubble_capture.py -q
```

Expected: FAIL because the recognizer does not exist.

**Step 3: Implement app profiles and `VisualBubbleSource`**

Define relative search bounds and direction thresholds per application, but calculate the final region from each `WindowFrame`. Reuse Vision line extraction and existing watermark/chrome filtering; do not reuse the fixed `KIM_COMPOSER_ROI` or `WECHAT_COMPOSER_ROI`.

Represent a candidate explicitly:

```python
@dataclass(frozen=True)
class BubbleCandidate:
    text: str
    bounds: NormalizedRect
    changed_fraction: float
    outgoing_score: float
```

Return success only when the candidate intersects the baseline-to-current changed region and satisfies the outgoing threshold. Build `message_identity` from intent ID, window ID, quantized bounds and observation time, not text alone.

**Step 4: Run bubble and legacy OCR tests**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_chat_bubble_capture.py tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py -q
```

Expected: all selected tests pass. Legacy tests remain green until the old production path is removed.

**Step 5: Commit**

```bash
git add src/ominime/chat_bubble_capture.py tests/test_chat_bubble_capture.py src/ominime/kim_composer_capture.py src/ominime/wechat_composer_capture.py
git commit -m "feat: recognize new outgoing chat bubbles"
```

### Task 5: Add the supported structured-source tier

**Files:**
- Create: `src/ominime/chat_message_sources.py`
- Create: `tests/test_chat_message_sources.py`
- Modify: `src/ominime/post_send_capture.py`

**Step 1: Write failing Accessibility source tests**

Use fake AX nodes and require all of the following before success: target PID matches, element is static text, it is newly observed after Enter, it is on the outgoing/right side, and it has a stable element/message identity. Test unavailable AX trees, stale nodes, incoming nodes, secure elements, empty text and native exceptions.

Also assert that the default source list contains no HTTP request and never probes port 5030.

**Step 2: Run tests and verify RED**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_chat_message_sources.py -q
```

Expected: FAIL because the source module does not exist.

**Step 3: Implement `AccessibilityBubbleSource`**

Perform bounded AX traversal against the target PID on the capture worker. Return an unavailable result when the app does not expose enough identity/direction evidence; never guess from text alone. Configure the default chain as AX then Vision.

Do not implement Chatlog, direct WeChat database reads, Electron injection or remote HTTP sources in this task.

**Step 4: Run source and privacy tests**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_chat_message_sources.py tests/test_submission_privacy.py -q
```

Expected: all selected tests pass and no context/image content reaches persistence.

**Step 5: Commit**

```bash
git add src/ominime/chat_message_sources.py tests/test_chat_message_sources.py src/ominime/post_send_capture.py
git commit -m "feat: prefer supported local chat message sources"
```

### Task 6: Route Kim and WeChat Enter into the post-send pipeline

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `tests/test_keyboard_listener_capture.py`

**Step 1: Replace pre-submit expectations with failing post-send tests**

Add/modify tests proving:

- a verified plain Kim/WeChat Enter returns the original event immediately;
- no `CGEventCreateCopy`, replay marker, watchdog, AX read, screenshot or OCR runs in `_event_callback()`;
- the worker creates exactly one `SendIntent` after secure/ignored/count-only gates;
- modifier Enter and autorepeat do not create an intent;
- queue full records a diagnostic but leaves Enter untouched;
- successful capture emits one existing `KeyEvent` with `submit_snapshot=True` and `fallback_source=kim_postsend_ocr` or `wechat_postsend_ocr`;
- failed capture emits no content event and clears submission buffers;
- completion after the user switches apps retains the original verified app/PID but rejects a mismatched window identity.

**Step 2: Run focused tests and verify RED**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py -k 'kim or wechat or postsend or replay' -q
```

Expected: current pre-submit interception assertions fail.

**Step 3: Inject and start the new services**

Add optional `post_send_coordinator` and `baseline_sampler` constructor arguments. Start/stop them with the listener. On ordinary Kim/微信 text activity, call the sampler's non-blocking `schedule(target_pid)` after the event is queued.

For a verified plain chat Enter:

```python
raw_event = RawKeyboardEvent(...)
try:
    self._event_queue.put_nowait(raw_event)
except queue.Full:
    self._record_dropped_event(...)
return event
```

Do not call `_create_pending_replay()` and do not register a suppressed keyUp token.

In the worker, run the existing secure check, pop validation/count buffers, take the baseline and submit `SendIntent`. Map coordinator completion back through `_emit_submission_event()` so database behavior remains centralized.

**Step 4: Run the complete keyboard capture tests**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py -q
```

Expected: all tests pass with post-send behavior replacing chat pre-submit replay assertions.

**Step 5: Commit**

```bash
git add src/ominime/keyboard_listener.py tests/test_keyboard_listener_capture.py
git commit -m "feat: capture Kim and WeChat after send"
```

### Task 7: Preserve persistence, diagnostics, and Web statistics semantics

**Files:**
- Modify: `tests/test_submission_diagnostics.py`
- Modify: `tests/test_submission_privacy.py`
- Modify: `tests/test_web_api.py`
- Modify only if a failing test requires it: `src/ominime/submission_processor.py`
- Modify only if a failing test requires it: `src/ominime/web/api.py`

**Step 1: Add failing integration assertions**

Require that a successful post-send outcome stores exact content/char count once, while a timeout stores only a capture diagnostic. Assert no new `submission_contexts` row, no image/blob/path field, no OCR candidate text in diagnostics, and no failed capture in successful-text Web totals.

**Step 2: Run the tests and verify RED or document already-green contracts**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_submission_diagnostics.py tests/test_submission_privacy.py tests/test_web_api.py -q
```

Expected: new post-send assertions initially fail; existing context-removal assertions remain green.

**Step 3: Make the smallest persistence changes**

Continue using `fallback_source` and `capture_diagnostics` in `KeyEvent.modifiers`. Do not add a new database table or revive `save_submission_context()`. Add only the source/failure mappings required for correct Web aggregation.

**Step 4: Re-run and verify GREEN**

Run the command from Step 2.

Expected: all selected tests pass.

**Step 5: Commit**

```bash
git add tests/test_submission_diagnostics.py tests/test_submission_privacy.py tests/test_web_api.py
git add src/ominime/submission_processor.py src/ominime/web/api.py
git commit -m "test: preserve post-send privacy and statistics"
```

Before staging, omit either production file if it was not changed.

### Task 8: Remove the Kim/WeChat pre-submit interception path

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `src/ominime/kim_composer_capture.py`
- Modify: `src/ominime/wechat_composer_capture.py`
- Modify: `tests/test_keyboard_listener_capture.py`
- Modify: `tests/test_kim_composer_capture.py`
- Modify: `tests/test_wechat_composer_capture.py`

**Step 1: Add a source-level regression test**

Assert that Kim/WeChat production routing no longer references `PendingReplay`, `ENTER_REPLAY_TIMEOUT_SECONDS`, `_freeze_presubmit_composer`, `KIM_COMPOSER_ROI` or `WECHAT_COMPOSER_ROI`. Keep any replay machinery only if another non-chat feature still has a verified caller.

**Step 2: Run the regression test and verify RED**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py -k 'no_chat_presubmit_interception' -q
```

Expected: FAIL while the old path remains.

**Step 3: Delete dead production branches and migrate shared utilities**

Remove only the now-unreachable Kim/WeChat pre-submit freeze/replay code and fixed composer ROI logic. Preserve generic Vision helpers in the new chat-window/bubble modules. Delete obsolete tests instead of weakening them into assertions about dead code.

**Step 4: Run all capture tests**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest tests/test_keyboard_listener_capture.py tests/test_post_send_capture.py tests/test_chat_window_capture.py tests/test_chat_bubble_capture.py tests/test_chat_message_sources.py tests/test_submission_privacy.py tests/test_submission_diagnostics.py -q
```

Expected: all selected tests pass; no chat Enter suppression remains.

**Step 5: Commit**

```bash
git add src/ominime/keyboard_listener.py src/ominime/kim_composer_capture.py src/ominime/wechat_composer_capture.py
git add tests/test_keyboard_listener_capture.py tests/test_kim_composer_capture.py tests/test_wechat_composer_capture.py
git commit -m "refactor: remove chat pre-submit interception"
```

### Task 9: Document behavior and complete automated verification

**Files:**
- Modify: `README.md`
- Modify: `docs/plans/2026-08-15-post-send-final-text-capture-design.md`
- Modify: `docs/plans/2026-08-15-post-send-final-text-capture-implementation.md`

**Step 1: Update user-facing documentation**

Document that Kim/微信 are recorded from confirmed post-send messages, Enter is never intercepted for capture, images are memory-only, no remote model is used, and unsupported Chatlog/database extraction is not a dependency. Include observable failure codes and the manual acceptance procedure.

**Step 2: Run formatting and static checks**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m compileall -q src tests
bash -n scripts/*.sh src/ominime/scripts/*.sh
/Users/liqiuhua/work/ominime/venv/bin/python -m pip check
git diff --check
```

Expected: every command exits 0.

**Step 3: Run the full suite**

```bash
PYTHONPATH=src /Users/liqiuhua/work/ominime/venv/bin/python -m pytest -q
```

Expected: all tests pass; the existing known Starlette deprecation warning may remain.

**Step 4: Run the 100-send deterministic stress test**

Add or invoke a test that feeds 100 ordered Kim/WeChat send intents through fake AX/OCR sources with injected latency and failures. Require 100 unique outcomes in order, bounded queue recovery, no duplicate persistence and a live coordinator worker at the end.

**Step 5: Request independent review**

Use `superpowers:requesting-code-review`. Require no unresolved Critical or Important finding concerning EventTap latency, duplicate/missing Enter, secure/ignored/count-only capture, source identity, old/incoming bubble false positives, image lifetime, thread shutdown or diagnostics privacy.

**Step 6: Commit documentation and final test adjustments**

```bash
git add README.md docs/plans/2026-08-15-post-send-final-text-capture-design.md docs/plans/2026-08-15-post-send-final-text-capture-implementation.md
git commit -m "docs: describe post-send final text capture"
```

**Implementation note:** Tasks 1–8 were completed in the isolated feature worktree with strict local TDD and batch review. The final implementation requires non-empty validation for every Visual success, binds AX/Visual results to PID + window + session anchors, uses bounded structured identity deduplication, waits only on the non-EventTap worker for a pending baseline, and has removed the Kim/微信 pre-submit freeze/replay/fixed-ROI production path. Task 10 remains gated on automated verification, independent review and real Kim/微信 smoke tests; no merge, push or deployment is authorized before all three pass.

### Task 10: Run real acceptance, then integrate and deploy

**Files:**
- Modify only if deployment verification exposes a directly related defect.

**Step 1: Verify a clean task diff**

Confirm only this feature's explicit files are staged/committed. Preserve the user's existing untracked root documents, plans and `reports/`; never use `git add -A`.

**Step 2: Run the verified candidate without deploying it**

From the isolated feature worktree, run the verified candidate in the foreground for acceptance. If an installed listener would conflict, pause that listener for the duration of the test and restore it afterward; do not install files, change LaunchAgent definitions, merge, push or deploy.

**Step 3: Run real Kim and WeChat acceptance**

Send unique tests covering short Chinese, English/numbers, multiline, paste, Doubao candidate commit, two identical consecutive messages and a rapid burst. For every message verify exact database content, correct `*_postsend_ax` or `*_postsend_ocr` source, one record only, no context row, no screenshot artifact and no new crash report.

**Step 4: Verify pre-integration failure behavior**

Repeat with the target window minimized or switched immediately after Enter. Require a named failure diagnostic, no wrong/old text record, and no effect on message delivery or listener health.

Only after automated verification, independent review, and Steps 3–4 all pass may the work proceed to integration, push or deployment.

**Step 5: Integrate from a clean main worktree**

Fetch `origin`, fast-forward the verified feature branch into `main`, rerun the full test suite on `main`, then push. Do not deploy from a dirty or unverified branch.

**Step 6: Restart local services and verify deployment**

```bash
launchctl kickstart -k "gui/$(id -u)/com.ominime.app"
launchctl kickstart -k "gui/$(id -u)/com.ominime.web"
```

Verify new stable PIDs, current heartbeat, `last_runtime_error: null`, and the Web service bound only to loopback.
