# Doubao Candidate Capture for Kim and WeChat

## Problem

Kim (`Kem`) and WeChat (`com.tencent.xinWeChat`) receive keyboard events, but
their chat composers do not expose a focused accessibility text element on the
tested versions. OmniMe can therefore count physical input attempts but cannot
read the submitted text. The web view correctly shows those attempts as
`（无内容）`.

The current compatibility fallback cannot recover Chinese text from keyboard
events when Doubao Input Method (`com.bytedance.inputmethod.doubaoime`) is in
use. The key events contain pinyin or no committed Unicode, not the Chinese
candidate selected by the user.

## Evidence

- System-wide and process-scoped accessibility queries expose the Kim and
  WeChat windows, but no focused chat text control.
- Electron manual accessibility does not make Kim's composer available.
- HID, session, and annotated event taps do not carry the committed Chinese
  text produced by Doubao.
- Selecting all and copying in Kim returns the whole conversation, not only the
  draft, so clipboard capture is unsafe.
- Screen OCR can read a carefully cropped Kim composer, but is display- and
  layout-dependent and cannot reliably capture the current WeChat window.
- Doubao's candidate window exposes its candidate words as accessibility
  `AXStaticText` values. Its on-screen bounds can be compared with the target
  application's window to determine whether it is anchored near the lower chat
  composer rather than a top search field.

## Goals

- Record confirmed Chinese candidate selections in Kim and WeChat when Doubao
  is the active input method.
- Treat Enter used to commit an active input-method candidate as composition,
  not as message submission.
- Persist content only after a later, real chat Enter.
- Avoid screenshots, OCR, clipboard reads, and synthetic key presses in the
  production capture path.
- Keep the existing count-only result whenever the candidate source or composer
  location cannot be trusted.

## Scope

The adapter is enabled only when all of the following match exactly:

- target bundle: `Kem` or `com.tencent.xinWeChat`;
- input method bundle: `com.bytedance.inputmethod.doubaoime`;
- the Doubao candidate window is positioned inside the target main window and
  in its lower composer region.

Other applications and input methods retain the existing accessibility and
count-only behavior. This first version intentionally does not persist raw
Latin/pinyin text from the adapter. Pure-English messages therefore remain
count-only unless the application exposes them through the normal trusted
accessibility path.

## Selected Design

Add a small Doubao-specific candidate reader and an in-memory composition state
machine. The accessibility reader first verifies that Doubao is the currently
selected macOS input source, then discovers the exact Doubao process through
`NSWorkspace`, traverses its candidate windows, and extracts non-empty,
deduplicated `AXStaticText` values. The same AX window supplies both candidate
text and its position/size; Quartz supplies only the target Kim or WeChat
window bounds. This binds text and geometry to one candidate window.

The keyboard listener keeps a separate, expiring state for each exact target
application. It combines confirmed candidate selections with supported editing
operations. No candidate or draft text is written to the database until a real
message submission occurs.

## Data Flow

1. A printable key is observed for Kim or WeChat. Its raw Latin value is held
   as pending pre-edit text rather than immediately accepted as message text.
2. After key-up, when Doubao has updated its UI, the listener reads the candidate
   window and validates its bounds against the lower composer region.
3. A trusted candidate snapshot activates the composition session. Pending
   pinyin remains pre-edit data and is not appended as literal English.
4. Space or Enter commits the currently selected candidate. Number keys select
   candidates 1–9, and arrow keys adjust the current selection when supported.
5. An Enter that commits a candidate is consumed as `ime_candidate_commit`; it
   does not run the message-submission path and does not clear composed text.
6. Backspace edits active pre-edit text first and otherwise removes the last
   committed character. Raw pre-edit text is never promoted to submitted text
   when the candidate window disappears.
7. A later Enter with no active candidate window is treated as message
   submission. The confirmed composed buffer is persisted with source
   `doubao_candidate_text`.
8. If the source, position, selection, timing, or text is ambiguous, content is
   discarded and the existing redacted count-only submission is used.

## Candidate and Window Validation

The candidate reader will be isolated in
`src/ominime/ime_candidate_capture.py` so that accessibility traversal and pure
state transitions can be tested separately.

- Identify the Doubao process by exact bundle identifier.
- Enumerate accessibility windows and collect visible non-empty candidate text.
- Deduplicate repeated accessibility nodes while retaining visual order.
- Resolve candidate bounds from the same AX window that contains its text, and
  resolve target-window bounds through Quartz.
- Require exactly one candidate-bearing AX window and exactly one matching
  visible Doubao candidate window; reject cross-window ambiguity.
- Accept a snapshot only when its horizontal center lies inside the target
  window and its vertical center lies in approximately the lower 45 percent of
  that window.
- Bind each snapshot to the target PID, expire it after five seconds, and
  revalidate the candidate window immediately before Space, number, or Enter
  commits it. A commit key performs this read even if the preceding key-up ran
  before the candidate window became visible.

## Input State

Each `(app_name, bundle_id)` session holds:

- target PID and last-updated time;
- the latest validated candidates and selected index (default zero);
- pending raw pre-edit keys;
- confirmed composed message text;
- whether the lower composer region has ever been trusted in this session.

Space and Enter choose the current/default candidate; digits 1–9 choose the
corresponding visible candidate; arrow keys move the selected index. When an
active candidate is committed, pending pinyin is discarded and only the chosen
candidate is appended. State is cleared on expiry, target PID/application
change, mouse click, or an editing operation the adapter cannot replay safely
(including paste, cut, undo, select-all, Delete, Tab, and Escape).
The five-second lifetime applies only to an uncommitted candidate snapshot;
confirmed message content retains the normal application session timeout.
If a later key-up misses its candidate window, the confirmed prefix is retained
in memory but the submission is marked ambiguous. A successful commit-key
revalidation restores the full prefix-plus-candidate message; otherwise the
whole submission falls back to count-only rather than saving a partial suffix.

## Privacy and Failure Behavior

- Exact bundle identifiers prevent the adapter from becoming a global input
  recorder.
- Candidate text remains in memory until a real submission.
- No screenshots, OCR, clipboard access, or synthetic selection are used.
- Candidate windows outside the lower composer region are ignored, preventing
  capture from Kim or WeChat search boxes.
- Secure, readable accessibility fields remain unconditional skips.
- Ambiguous or unavailable candidates fall back to the current
  `[unreadable input]` count-only record.
- Candidate failure reasons are diagnostic codes only; discarded candidate and
  pre-edit strings are never written to diagnostics.
- Diagnostics distinguish candidate commit, candidate-text persistence,
  untrusted candidate position, expiry, and count-only fallback without storing
  discarded pre-edit content.

## Tests

- Candidate AX values are collected, ordered, and deduplicated.
- Exact input-method and target bundle matching is required.
- Candidate bounds must be inside the lower target-window region.
- Space, Enter, digit, arrow, and backspace transitions produce the expected
  confirmed text.
- Enter with an active candidate never emits a chat submission.
- The next inactive Enter persists the composed buffer once.
- Pure raw pinyin is never persisted as message content.
- App/PID changes and timeouts clear sensitive in-memory state.
- Untrusted or missing candidates retain count-only behavior.
- Existing secure-field and non-compatible-application tests remain green.

## Deployment and Validation

After focused and full automated tests pass, commit only the planned source,
tests, and documentation. Restart the OmniMe application and web launch agents,
verify their health and fresh heartbeat, then validate a newly sent Kim and
WeChat message. Success requires a new record with non-empty content and source
`doubao_candidate_text`; service health alone is not sufficient proof of
content capture.
