# Source-Owned Chat Interface Investigation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Determine whether Kim's organization-authorized open platform and a WeChat-owned loopback service can safely provide a structured path toward the seven required chat capabilities without OCR, UI automation, private-protocol guessing, or real-user data.

**Architecture:** Add non-production, repository-local investigation tools that emit one shared redacted evidence format. Kim begins with a human-reviewed API-catalog gate; WeChat begins with signed-process listener inventory and a bounded standard-protocol classifier inside an isolated macOS user. Any positive candidate requires a new API-specific design before message retrieval, and the original G2 remains blocked until both sources prove all seven capabilities.

**Tech Stack:** Node.js 24+, ECMAScript modules, Vitest, macOS `pgrep`/`ps`/`lsof`/`codesign`, Node `net`/`tls`, macOS Keychain for any later credential, Markdown verification artifacts.

---

## Non-negotiable execution boundary

- Use @test-driven-development for every code change.
- Use @systematic-debugging for any unexpected failure.
- Use @verification-before-completion before every commit and Gate claim.
- Run live WeChat work only in a dedicated macOS user with a dedicated test
  account. Never run it against the current user's WeChat session.
- Kim catalog inspection uses normal enterprise SSO and administrator-approved
  access. Do not automate login or copy internal documentation into the repo.
- Do not query messages in this plan. A self-describing candidate interface
  earns only a follow-up API-specific design, not G2 PASS.
- Do not use Chatlog, user containers, local chat databases, OCR, Accessibility,
  packet interception, process injection, or private protocol reverse
  engineering.
- Do not start the original implementation plan's Task 7 or later tasks.
- Do not stop, reconfigure, or inspect the existing Chatlog service. Its
  remediation remains a separate user-authorized security task.

### Required capability names

Every report uses these exact capability keys:

```js
const requiredCapabilities = [
  'selfAccountIdentity',
  'conversationIdentity',
  'stableMessageIdentity',
  'finalMessageText',
  'authoritativeDirection',
  'timestampOrOrder',
  'incrementalChanges',
]
```

Candidate discovery alone leaves every key `false`.

### Human checkpoints

This plan has two mandatory STOP points:

1. Kim catalog inspection requires the user to complete normal SSO and any
   administrator approval.
2. WeChat classification requires the user to create and enter a dedicated
   macOS user and sign in with a dedicated test account.

No agent may substitute current production identities for either checkpoint.

### Branch and worktree

Run all commands from the isolated repository worktree root. Before each task,
verify the branch without recording a machine-specific path:

```bash
test "$(git branch --show-current)" = "codex/dsh-personal-context"
test -z "$(git status --short)"
```

## Task 1: Add the source-owned redacted evidence contract

**Files:**

- Create: `dsh-plugin/scripts/source-owned/evidence.mjs`
- Create: `dsh-plugin/tests/source-owned-evidence.spec.ts`
- Create: `dsh-plugin/tests/fixtures/source-owned/README.md`

**Step 1: Write the failing evidence tests**

Create behavior tests that require an exact, deep-frozen report shape and
reject unknown keys, raw errors, paths, URLs, messages, identifiers, tokens,
cookies, counts, and hashes.

```ts
import { describe, expect, it } from 'vitest'
import {
  createBlockedEvidence,
  sanitizeSourceOwnedEvidence,
} from '../scripts/source-owned/evidence.mjs'

describe('source-owned redacted evidence', () => {
  it('creates a fail-closed report with every capability false', () => {
    const report = createBlockedEvidence({
      source: 'wechat',
      interfaceClass: 'app_loopback',
      failureCode: 'WECHAT_STANDARD_PROTOCOL_NOT_PROVEN',
    })
    expect(Object.values(report.capabilities)).toEqual(Array(7).fill(false))
    expect(Object.isFrozen(report.capabilities)).toBe(true)
    expect(Object.isFrozen(report)).toBe(true)
  })

  it('does not serialize raw diagnostic values', () => {
    const privateValue = 'synthetic private message body'
    expect(() => sanitizeSourceOwnedEvidence({
      source: 'wechat',
      status: 'block',
      rawError: privateValue,
    })).toThrowError(/EVIDENCE_SHAPE_INVALID/)
  })
})
```

The allowed top-level keys are exactly:

```text
source
interfaceClass
status
protocolClass
authorizationClass
versionClass
capabilities
fieldMappings
failureCodes
```

Values must be enums or fixed safe identifiers. No arbitrary metadata field is
allowed.

**Step 2: Verify RED**

Run:

```bash
pnpm --dir dsh-plugin exec vitest run tests/source-owned-evidence.spec.ts
```

Expected: FAIL because `scripts/source-owned/evidence.mjs` does not exist.

**Step 3: Implement the smallest strict evidence module**

Implement only constructors and validators needed by the investigation:

```js
export const requiredCapabilityKeys = Object.freeze([
  'selfAccountIdentity',
  'conversationIdentity',
  'stableMessageIdentity',
  'finalMessageText',
  'authoritativeDirection',
  'timestampOrOrder',
  'incrementalChanges',
])

const safeIdentifier = /^[A-Z][A-Z0-9_]{0,63}$/

export function createBlockedEvidence({ source, interfaceClass, failureCode }) {
  if (!safeIdentifier.test(failureCode)) throw new Error('EVIDENCE_CODE_INVALID')
  const capabilities = Object.freeze(Object.fromEntries(
    requiredCapabilityKeys.map(key => [key, false]),
  ))
  return Object.freeze({
    source,
    interfaceClass,
    status: 'block',
    protocolClass: null,
    authorizationClass: null,
    versionClass: null,
    capabilities,
    fieldMappings: Object.freeze({}),
    failureCodes: Object.freeze([failureCode]),
  })
}
```

The final validator must reconstruct a new allowlisted object rather than
returning caller-owned input.

**Step 4: Verify GREEN and the current suite**

Run:

```bash
pnpm --dir dsh-plugin exec vitest run tests/source-owned-evidence.spec.ts
pnpm --dir dsh-plugin test
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/scripts/source-owned/evidence.mjs \
  dsh-plugin/tests/source-owned-evidence.spec.ts \
  dsh-plugin/tests/fixtures/source-owned/README.md
git commit -m "test: define source-owned evidence contract"
```

## Task 2: Add passive WeChat listener inventory

**Files:**

- Create: `dsh-plugin/scripts/source-owned/wechat-listeners.mjs`
- Create: `dsh-plugin/tests/wechat-owned-listeners.spec.ts`
- Modify: `dsh-plugin/tests/fixtures/source-owned/README.md`

**Step 1: Write failing parser and safety tests**

Use invented command output only. Tests must prove:

- only the main `WeChat` process is accepted;
- executable ownership must resolve inside the signed `WeChat.app` bundle;
- bundle identifier and team identifier must match the public app signature;
- only `127.0.0.1` and `::1` listeners are accepted;
- wildcard, LAN, public, malformed, duplicate, and out-of-range listeners fail;
- raw `ps`, `lsof`, or `codesign` output is never returned or logged;
- abort, timeout, oversized output, and command failure produce fixed codes.

```ts
it('rejects a wildcard listener without echoing the endpoint', async () => {
  await expect(collectWechatListeners({ runner: inventedRunner({
    lsof: 'p123\\ncWeChat\\nn*:4567\\n',
  }) })).rejects.toMatchObject({ code: 'WECHAT_NON_LOOPBACK_LISTENER' })
})
```

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-owned-listeners.spec.ts
```

Expected: FAIL on the missing listener module.

**Step 3: Implement bounded command adapters**

Use absolute system binaries and argument arrays:

```js
const tools = Object.freeze({
  pgrep: '/usr/bin/pgrep',
  ps: '/bin/ps',
  lsof: '/usr/sbin/lsof',
  codesign: '/usr/bin/codesign',
})

const expectedSignature = Object.freeze({
  bundleIdentifier: 'com.tencent.xinWeChat',
  teamIdentifier: '5A4RE8SF68',
})
```

Use async `execFile` with `AbortSignal`, a hard timeout, and a small
`maxBuffer`. Resolve only `pgrep -x WeChat`; use `ps -p <pid> -o comm=` rather
than process arguments. Capture raw output in memory, parse an allowlisted
result, then discard it.

Return only an in-memory frozen list of `{ host, port }`. Do not print it and do
not commit ports to evidence.

**Step 4: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-owned-listeners.spec.ts
pnpm --dir dsh-plugin test
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/scripts/source-owned/wechat-listeners.mjs \
  dsh-plugin/tests/wechat-owned-listeners.spec.ts \
  dsh-plugin/tests/fixtures/source-owned/README.md
git commit -m "spike: inventory signed WeChat loopback listeners"
```

## Task 3: Add the bounded standard-protocol classifier

**Files:**

- Create: `dsh-plugin/scripts/source-owned/loopback-classifier.mjs`
- Create: `dsh-plugin/tests/loopback-classifier.spec.ts`
- Create: `dsh-plugin/tests/fixtures/source-owned/generate-test-cert.mjs`

**Step 1: Write failing real-socket tests**

Create temporary loopback servers and verify:

- server-first banner classification reads only a bounded prefix;
- TLS classification records only `tls` and an ALPN class, never certificate
  names or bytes;
- plain HTTP receives exactly `OPTIONS *` and no business path or body;
- only status class and presence booleans for `Allow`, `Link`, and
  `WWW-Authenticate` survive redaction;
- binary, silent, oversized, non-loopback, timeout, cancellation, and multiple
  response attempts fail with fixed codes;
- every socket is destroyed on success, error, timeout, and abort;
- the classifier makes no retries.

```ts
it('sends only OPTIONS star to a synthetic HTTP listener', async () => {
  const received: Buffer[] = []
  const result = await classifyLoopback({ host: '127.0.0.1', port, budgets })
  expect(Buffer.concat(received).toString('ascii')).toMatch(/^OPTIONS \* HTTP\/1\.1\r\n/)
  expect(Buffer.concat(received).includes(Buffer.from('/api/'))).toBe(false)
  expect(result.protocolClass).toBe('http')
})
```

Generate an ephemeral self-signed certificate inside a task-owned temporary
directory. Never commit a test private key.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/loopback-classifier.spec.ts
```

Expected: FAIL on the missing classifier.

**Step 3: Implement the classifier state machine**

The state machine gets fresh sockets for each allowed standard probe:

```text
server-first banner -> TLS ClientHello -> HTTP OPTIONS * -> stop
```

Each stage runs at most once. Use fixed byte, time, and connection budgets.
Never return raw frames, bodies, header values, certificate fields, endpoints,
or thrown system errors.

If TLS identifies ALPN HTTP, send `OPTIONS *` over that same TLS connection. If
no standard protocol self-identifies, return
`WECHAT_STANDARD_PROTOCOL_NOT_PROVEN`.

**Step 4: Verify GREEN and leak checks**

```bash
pnpm --dir dsh-plugin exec vitest run tests/loopback-classifier.spec.ts
pnpm --dir dsh-plugin test
```

Expected: PASS with no open handles.

**Step 5: Commit**

```bash
git add dsh-plugin/scripts/source-owned/loopback-classifier.mjs \
  dsh-plugin/tests/loopback-classifier.spec.ts \
  dsh-plugin/tests/fixtures/source-owned/generate-test-cert.mjs
git commit -m "spike: classify bounded loopback protocols"
```

## Task 4: Add a non-packaged WeChat source-owned probe CLI

**Files:**

- Create: `dsh-plugin/scripts/source-owned/probe-wechat-owned.mjs`
- Create: `dsh-plugin/tests/wechat-owned-cli.spec.ts`
- Modify: `dsh-plugin/package.json`
- Modify: `dsh-plugin/tests/bundle.spec.ts`

**Step 1: Write failing CLI boundary tests**

Tests must prove the CLI:

- requires both `--redact` and `--isolated-test-user-confirmed`;
- requires `--test-account-confirmed`;
- requires exactly one mode: `--inventory-only` or `--classify`;
- refuses unknown arguments;
- refuses execution when the current environment has not been manually
  confirmed as a dedicated test account;
- inventories only signed WeChat listeners;
- classifies each candidate once and emits one redacted aggregate report;
- emits no ports, PIDs, paths, command output, response bytes, header values, or
  raw errors;
- exits `0` only for a self-describing standard candidate and `2` for
  `NOT PROVEN` or `BLOCK`;
- is not included in `package.json.files`, the npm tarball, Host bundle, client
  bundle, or installed smoke artifacts.

```ts
expect(packageManifest.files).not.toContain('scripts/source-owned')
expect(packageManifest.scripts['probe:wechat-owned']).toBe(
  'node scripts/source-owned/probe-wechat-owned.mjs',
)
```

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-owned-cli.spec.ts tests/bundle.spec.ts
```

Expected: FAIL on the missing CLI and script contract.

**Step 3: Implement the minimal orchestration**

The CLI composes Task 1 through Task 3 only. It does not accept an arbitrary
host, port, executable, path, request, header, or payload from command-line
arguments.

```js
const allowedArguments = new Set([
  '--redact',
  '--isolated-test-user-confirmed',
  '--test-account-confirmed',
  '--inventory-only',
  '--classify',
])
```

Add the development-only package script, but do not add the script directory to
`files` or to `tsdown.config.ts`.

`--inventory-only` must perform signed listener inventory without opening a
socket and return a fixed `NOT PROVEN` report. `--classify` may run the bounded
Task 3 classifier. The two modes are mutually exclusive.

**Step 4: Verify GREEN, build, and pack isolation**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-owned-cli.spec.ts tests/bundle.spec.ts
pnpm --dir dsh-plugin test
pnpm --dir dsh-plugin pack --dry-run
```

Expected: PASS; the tarball listing has no source-owned investigation script.

**Step 5: Commit**

```bash
git add dsh-plugin/scripts/source-owned/probe-wechat-owned.mjs \
  dsh-plugin/tests/wechat-owned-cli.spec.ts \
  dsh-plugin/package.json dsh-plugin/tests/bundle.spec.ts
git commit -m "spike: add isolated WeChat interface probe"
```

## Task 5: Apply the Kim internal catalog gate

**Files:**

- Create: `docs/verification/kim-source-owned-catalog.md`
- Create: `dsh-plugin/tests/kim-source-owned-catalog.spec.ts`
- Modify: `docs/dossiers/2026-08-17-dsh-personal-context.md`

**Step 1: Write the failing document-contract test**

The test must require these generic fields and forbid internal names or URLs:

```text
Status
Authorization class
Historical participation scope
Self identity
Conversation identity
Stable message identity
Timestamp or order
Edit and retraction events
Incremental cursor or event stream
Failure codes
```

Allowed values are fixed enums such as `PROVEN`, `NOT PROVEN`, `BLOCK`,
`enterprise_sso`, `administrator_approval`, and `bot_only`.

```ts
expect(report).not.toMatch(/https?:\/\//)
expect(report).not.toMatch(/token|cookie|client_secret|organization_id/i)
```

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/kim-source-owned-catalog.spec.ts
```

Expected: FAIL because the catalog report is missing.

**Step 3: STOP for normal user login and approval**

Ask the user to:

1. sign in to Kim normally;
2. open the organization-approved internal open-platform catalog;
3. complete any normal application or administrator approval.

Do not request credentials in chat. Do not automate login. Do not call an API.

**Step 4: Inspect only the catalog contract**

Record generic capability results only. A bot-only, notification-only, or
post-install event API must be `NOT SUITABLE` for historical personal context.

If the catalog does not prove a plausible route to every required capability,
mark Kim `BLOCK` and do not create an adapter.

If it does, mark only the catalog candidate `PROVEN`, keep G2 blocked, and write
a new API-specific design before any request or credential implementation.

**Step 5: Verify GREEN and links**

```bash
pnpm --dir dsh-plugin exec vitest run tests/kim-source-owned-catalog.spec.ts
git diff --check
```

Expected: PASS without internal endpoint names or credentials.

**Step 6: Commit**

```bash
git add docs/verification/kim-source-owned-catalog.md \
  dsh-plugin/tests/kim-source-owned-catalog.spec.ts \
  docs/dossiers/2026-08-17-dsh-personal-context.md
git commit -m "docs: decide Kim source-owned catalog gate"
```

## Task 6: Run the isolated WeChat standard-protocol probe

**Files:**

- Create: `docs/verification/wechat-source-owned-loopback.md`
- Create: `dsh-plugin/tests/wechat-source-owned-report.spec.ts`
- Modify: `docs/dossiers/2026-08-17-dsh-personal-context.md`

**Step 1: Write the failing report-contract test**

Require a report containing only:

```text
Status
Interface class
Protocol class
Authorization class
Version stability
Capabilities
Failure codes
```

Forbid ports, PIDs, paths, bundle paths, raw frames, headers, certificate data,
test-account identifiers, messages, participant names, counts, and hashes.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-source-owned-report.spec.ts
```

Expected: FAIL because the report is missing.

**Step 3: STOP for the isolated environment**

Ask the user to enter the approved dedicated macOS user and sign in with the
dedicated WeChat test account. Verify verbally that the current production
account is not in use.

Do not create the account automatically and do not copy credentials between
users.

**Step 4: Run passive observation before traffic**

Run inventory-only mode, restart WeChat normally, and run inventory-only mode
again:

```bash
pnpm --dir dsh-plugin probe:wechat-owned -- \
  --redact \
  --isolated-test-user-confirmed \
  --test-account-confirmed \
  --inventory-only
```

Expected: a fixed redacted inventory result. Raw inventory and ports must not be
copied into the repository. If either run lacks a signed loopback candidate,
stop before classification.

**Step 5: Apply the WeChat candidate gate**

Only after both passive observations succeed, run classification mode. Repeat
the classification after one normal WeChat restart and compare only the
redacted protocol, authorization, and version classes:

```bash
pnpm --dir dsh-plugin probe:wechat-owned -- \
  --redact \
  --isolated-test-user-confirmed \
  --test-account-confirmed \
  --classify
```

Do not compare or persist ports, PIDs, raw frames, or response values.

- No signed loopback listener: `WECHAT_OWNED_LISTENER_NOT_FOUND`.
- Listener unstable across restart: `WECHAT_LISTENER_UNSTABLE`.
- No self-describing standard protocol: `WECHAT_STANDARD_PROTOCOL_NOT_PROVEN`.
- Standard protocol but no explicit auth/service description:
  `WECHAT_INTERFACE_CONTRACT_NOT_PROVEN`.
- Self-describing authenticated candidate: candidate `PROVEN`, but all seven
  chat capabilities remain false until a new protocol-specific design is
  approved.

Do not attempt a chat-history path or payload in this task.

**Step 6: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-source-owned-report.spec.ts
git diff --check
```

Expected: PASS with a redacted report matching the CLI result.

**Step 7: Commit**

```bash
git add docs/verification/wechat-source-owned-loopback.md \
  dsh-plugin/tests/wechat-source-owned-report.spec.ts \
  docs/dossiers/2026-08-17-dsh-personal-context.md
git commit -m "docs: record WeChat source-owned loopback evidence"
```

## Task 7: Apply the G2 reframe candidate gate

**Files:**

- Create: `docs/verification/source-owned-interface-gate.md`
- Create: `dsh-plugin/tests/source-owned-interface-gate.spec.ts`
- Modify: `docs/dossiers/2026-08-17-dsh-personal-context.md`
- Modify: `dsh-plugin/DSH_COMPATIBILITY.md`

**Step 1: Write the failing Gate-contract test**

The Gate must distinguish:

```text
Kim catalog candidate
WeChat standard-protocol candidate
Seven-capability G2 decision
Portable npm distribution constraint
```

The candidate gates may pass independently while the seven-capability G2
decision remains blocked.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/source-owned-interface-gate.spec.ts
```

Expected: FAIL because the Gate report is missing.

**Step 3: Write the smallest honest Gate decision**

Rules:

- If either candidate is unsuitable, remain `BLOCKED at G2` and record the
  fixed failure code.
- If both candidates are plausible, remain `BLOCKED at G2`, link both reports,
  and require source-specific API designs and seven-capability live evidence.
- Never convert a classifier or catalog result into chat-capability PASS.
- Keep production connectors disabled and legacy capture unchanged.
- Record Chatlog only as excluded and separately actionable; do not inspect or
  modify it.

**Step 4: Run the full verification set**

```bash
pnpm --dir dsh-plugin exec vitest run \
  tests/source-owned-evidence.spec.ts \
  tests/wechat-owned-listeners.spec.ts \
  tests/loopback-classifier.spec.ts \
  tests/wechat-owned-cli.spec.ts \
  tests/kim-source-owned-catalog.spec.ts \
  tests/wechat-source-owned-report.spec.ts \
  tests/source-owned-interface-gate.spec.ts
pnpm --dir dsh-plugin test
pnpm --dir dsh-plugin pack --dry-run
git diff --check
```

Expected: PASS; no investigation script is in the npm tarball.

**Step 5: Independent reviews**

Run specification review, then security/code-quality review. Reviewers must
verify:

- no production-account access;
- no credential or raw-response persistence;
- bounded standard probes only;
- no protocol guessing or auth bypass;
- candidate status is not overstated as seven-capability PASS;
- Dossier resumes at the correct Gate.

Any finding returns to the implementing task and repeats both reviews.

**Step 6: Commit**

```bash
git add docs/verification/source-owned-interface-gate.md \
  dsh-plugin/tests/source-owned-interface-gate.spec.ts \
  docs/dossiers/2026-08-17-dsh-personal-context.md \
  dsh-plugin/DSH_COMPATIBILITY.md
git commit -m "docs: decide source-owned interface gate"
```

## Task 8: Stop or create source-specific follow-up designs

**Files:**

- Conditional create: `docs/plans/YYYY-MM-DD-kim-authorized-api-design.md`
- Conditional create: `docs/plans/YYYY-MM-DD-wechat-owned-interface-design.md`
- Modify: `docs/dossiers/2026-08-17-dsh-personal-context.md`

**Step 1: Apply the candidate outcomes**

- Kim candidate `BLOCK`: stop Kim source work.
- WeChat candidate `BLOCK`: stop WeChat source work.
- Either source blocked: overall G2 remains blocked; do not continue the
  original Task 7.
- A candidate marked `PROVEN`: write a source-specific design for the exact
  authorized API or self-described protocol. Do not implement it from this
  generic plan.

**Step 2: Present the revised human Gate**

Give the user:

- candidate outcomes;
- exact fixed failure codes;
- what remains unproven;
- whether any one-time authorization is still required;
- the recommendation to stop or approve a source-specific design.

**Step 3: Update the Dossier only after the user decision**

Record the user's decision verbatim. Do not mark G2 PASS until both
source-specific probes prove all seven capabilities and independent review
passes.

**Step 4: Commit any approved follow-up design separately**

Use an exact path and a source-specific commit message. Do not combine Kim and
WeChat protocol implementations into one task or commit.
