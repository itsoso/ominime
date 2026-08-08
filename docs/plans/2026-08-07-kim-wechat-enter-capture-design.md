# Kim and WeChat Enter Capture Compatibility Design

## Problem

OmniMe receives typing and Enter events from Kim (`Kem`) and WeChat
(`com.tencent.xinWeChat`), but macOS often returns no system-wide focused
accessibility element for their chat composers. The strict submission safety
gate therefore marks every attempt as `degraded_context`, clears the buffered
input, and skips persistence.

The accessibility incompatibility predates the strict gate. The current gate
made the behavior deterministic: unsafe candidates are no longer occasionally
accepted, but these two chat applications now record nothing.

## Goals

- Recover a real focused text element whenever the target application exposes
  one through its process-scoped accessibility tree.
- Preserve the secure-field, editor-newline, whole-document, and field-identity
  safety checks whenever accessibility data is available.
- When both global and process-scoped accessibility remain unavailable, allow
  only a narrowly scoped CJK key-event fallback for Kim and WeChat.
- Keep Latin/unreadable degraded submissions content-redacted and record only
  their character count.
- Keep clipboard selection/copy fallback removed.
- Record the concrete accessibility failure in capture diagnostics.

## Considered Approaches

### 1. Process-scoped accessibility retry plus restricted chat fallback

This is the selected approach. The keyboard event already contains the target
PID, so context capture can retry `AXFocusedUIElement` on that application's AX
object when the system-wide query fails. If the application still exposes no
focused element, Kim and WeChat may use the existing bounded, expiring CJK
key-event buffer for a normal unmodified Enter. Latin text remains redacted and
is stored as count-only.

This preserves the highest-fidelity and safest source first, while providing a
useful compatibility path for the two confirmed applications.

### 2. Restore select-all/copy clipboard capture

Rejected. It changes application selection, mutates the clipboard, can capture
the wrong view, and can copy unrelated private content when focus information
is already unreliable.

### 3. Accept all printable key events for every degraded application

Rejected. Without a readable focused field, OmniMe cannot prove that typing is
inside a chat composer rather than a password, search, or document field. A
global blind fallback would turn the application into a general keylogger.

## Data Flow

1. EventTap samples the target PID, application identity, modifiers, key code,
   and committed Unicode text.
2. The worker passes the target PID into submission context capture.
3. Context capture tries the system-wide focused element, then the exact target
   application's focused element.
4. A valid text context follows the existing AX value and safety pipeline.
5. A still-degraded context is skipped for every application except Kim and
   WeChat.
6. For those two applications, recent CJK key-event text may be persisted as a
   degraded compatibility submission. If no trusted CJK text is available,
   only a redacted placeholder and physical character count are persisted.
7. Secure contexts are always rejected before any fallback is considered.

## Safety Boundaries

- Compatibility bundles are exact identifiers, not name or substring matches.
- Only an unmodified, non-autorepeated Enter can submit a fallback.
- CJK fallback content remains bounded by the existing maximum size and session
  timeout.
- The fallback buffer is consumed once and cleared on submission.
- No clipboard reads or synthetic key presses are introduced.
- Any context that is readable and marked secure remains an unconditional skip.
- Diagnostics identify the selected source and retain the underlying AX error.

## Tests

- Process-scoped AX focus is used only when system-wide focus is unavailable.
- The event target PID reaches context capture.
- Kim and WeChat persist bounded CJK fallback text under degraded context.
- Other degraded applications continue to skip.
- Kim and WeChat with no CJK content persist count-only, not plaintext.
- Secure fields continue to skip even for compatibility applications.
- Capture diagnostics retain the accessibility error.
- The complete existing test suite passes before deployment.

## Deployment and Validation

Commit only the design, implementation plan, source, and tests created for this
fix. Restart the OmniMe launch agents, verify their runtime health, then confirm
new Kim and WeChat Enter diagnostics no longer end exclusively in
`degraded_context` skips.
