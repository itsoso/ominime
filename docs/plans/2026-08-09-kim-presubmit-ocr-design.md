# Old Kim Pre-submit OCR Capture

## Problem

The legacy Kim desktop client (`Kem`) accepts and sends chat text but does not
expose its web composer through macOS Accessibility. System-wide and
process-scoped focused-element reads both return no element. Enabling Electron
manual accessibility still exposes only the native window shell.

The Doubao compatibility path cannot recover the text on the installed system
either. While composition is active, the Doubao process exposes no AX windows,
AX children, candidate text, or Quartz candidate window. As a result, a real
Kim submission reaches OmniMe with the physical key count but no trusted text
and is persisted as count-only.

The newer Kima client (`Kim`) does expose an `AXTextArea` and already persists
content through the normal `ax_value` source. This design therefore targets
only the legacy `Kem` bundle.

## Evidence

- A real legacy Kim submission produced diagnostic
  `doubao_candidate_failure=candidate_ax_unavailable` and an empty-content
  input record.
- During an active legacy Kim composition, the `Kem` process had no focused AX
  element and the Doubao process had zero AX windows and zero AX children.
- The same machine recorded a Kima (`Kim`) submission with source `ax_value`
  and non-empty content.
- Capturing the legacy Kim window before submission takes approximately
  20 milliseconds after warm-up. macOS Vision can recognize text from a
  bounded lower-composer crop without sending data to an external service.

## Considered Approaches

### 1. Pre-submit local OCR (selected)

Freeze the visible legacy Kim window on unmodified Enter key-down, before the
event is returned to the application. Perform OCR later on the existing worker
thread and accept text only from the fixed composer crop.

This works with the installed client without relaunch flags, clipboard access,
or synthetic selection. Its limitation is that only visible composer text can
be recovered; unusually long, internally scrolled drafts must fall back to
count-only rather than save a partial message.

### 2. Relaunch Kim with accessibility or remote-debugging flags

This can expose the renderer on some Electron builds but did not make the
installed Kim composer available through AX. It also changes how a separate
chat application is launched and is not durable when Kim starts normally.

### 3. Require migration to Kima

Kima already records correctly and is the simplest operational workaround,
but it does not meet the requirement that the currently used legacy Kim client
also save content.

## Selected Design

Add a small legacy-Kim pre-submit capture component with two phases:

1. `freeze(target_pid)` runs only for an unmodified Enter key-down whose exact
   target bundle is `Kem`. It finds the largest visible layer-zero window owned
   by the target PID and copies that window image. No OCR, disk write, or
   database work occurs in the event-tap callback.
2. `recognize(frame)` runs when the queued keyboard event is processed. It uses
   the system Vision framework with Simplified Chinese and English recognition
   on a Kim-specific lower-center region of interest. The image object is then
   released with the event and is never persisted.

The recognized text enters the existing submission decision only after normal
AX capture and the Doubao candidate buffer have failed. It is normalized by
the same submission-text rules and is persisted with source
`kim_presubmit_ocr`.

## Data Flow

1. The event tap observes Enter key-down and resolves the target PID and bundle.
2. For exact bundle `Kem`, with no Command, Control, Option, or Shift modifier,
   the listener freezes the current main-window image before returning Enter
   to Kim.
3. The immutable queued event carries only the in-memory image handle.
4. The event worker first applies existing candidate-commit and normal AX rules.
5. If those sources produce no trusted content, the worker performs local OCR
   on the Kim composer crop.
6. Non-empty normalized OCR text is persisted once. Empty, ambiguous, or
   rejected OCR output uses the existing count-only fallback.

## Trust and Privacy Rules

- Exact target bundle must be `Kem`; Kima, WeChat, browsers, editors, and other
  applications never invoke this path.
- Only unmodified Enter key-down can freeze a frame. Candidate/newline shortcut
  variants keep their existing behavior.
- Capture selects one largest visible normal window for the exact event PID.
- Vision recognition is entirely local. No screenshot is written to disk,
  logged, uploaded, added to diagnostics, or stored in SQLite.
- OCR is restricted to the legacy Kim composer region. Toolbar and send-hint
  bands are excluded from the accepted region.
- Recognition text is bounded by the existing 4,000-character submission
  limit and passes through current normalization.
- If the visible OCR result appears partial or contains only interface chrome,
  content is rejected and the count-only record is retained.
- Diagnostics contain only a source/failure code and character count, never the
  discarded image or OCR text.

## Performance and Failure Behavior

The event-tap phase performs only a single window lookup and image copy for
legacy Kim Enter. A capture exception or missing window returns no frame and
never blocks the key. OCR runs off the callback thread. All failures are
fail-closed: the message still sends normally and OmniMe falls back to the
existing unreadable count.

## Tests

- Window selection chooses the largest visible normal window owned by the
  target PID and rejects missing targets.
- OCR observation filtering orders lines visually, excludes toolbar/footer
  chrome, normalizes whitespace, and rejects empty/partial output.
- Only exact legacy Kim unmodified Enter key-down freezes a frame.
- The event callback returns the original event even if capture fails.
- Degraded legacy Kim persists accepted OCR content with source
  `kim_presubmit_ocr`.
- Existing AX, secure-field, candidate-commit, count-only, Kima, and WeChat
  tests remain unchanged and green.

## Deployment and Live Validation

After focused and full tests pass, restart the OmniMe listener and web service.
Send a fresh short message from legacy Kim, then verify a new `Kem` input record
has non-empty content and the matching diagnostic uses
`selected_source=kim_presubmit_ocr`. A healthy process alone is not sufficient;
the new database row is the acceptance criterion.
