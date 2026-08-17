# Chat Source Feasibility Gate

Pipeline entry: [DSH Personal Context dossier](../dossiers/2026-08-17-dsh-personal-context.md).

## Decision

G2 is **BLOCKED** overall. WeChat and Kim are each **BLOCKED** because the
approved safe probe cannot obtain an atomic, read-only source snapshot. The
reports therefore do not prove any of the required source capabilities.

This is a safety and evidence decision, not a claim that either application's
business data is incapable of providing these capabilities. Without an atomic
directory-descriptor/`openat` path helper or a source-owned read-only structured
interface, the current adapters cannot safely evaluate or use the live stores.

## Evidence and reproduction

- WeChat: [redacted feasibility report](./wechat-source-feasibility.md), proof
  commit `3b1ccec65889157a08cb0ab19a509b5d755044c6`.
- Kim: [redacted feasibility report](./kim-source-feasibility.md), proof commit
  `3df3eb78f3ba76ad2abf45f093aecdd2df44ce3a`.
- Source-neutral contract: commit
  `a9b82b319d9fd62550542dfff4b597d6fbf0f892`.

From the repository root, with an arm64 Node version accepted by the plugin's
`engines` field and the locked dependencies installed, reproduce the synthetic
contract and safe-failure checks with:

```sh
pnpm --dir dsh-plugin exec vitest run tests/connector-contract.spec.ts tests/wechat-paths.spec.ts tests/wechat-probe.spec.ts tests/kim-paths.spec.ts tests/kim-probe.spec.ts
```

From a clean checkout, reproduce the live redacted result with the fail-closed
script below. It verifies the locked package-manager version, installs only the
locked dependency graph, checks Node compatibility, and builds the ignored
probe artifacts before execution.

```sh
(
  set -eu
  cd dsh-plugin

  test "$(pnpm --version)" = "11.7.0"
  pnpm install --frozen-lockfile
  pnpm run check:node
  pnpm build

  # Run both probes before evaluating either expected BLOCK status.
  set +e
  wechat_report="$(node lib/probe-wechat.js --redact)"
  wechat_status=$?
  kim_report="$(node lib/probe-kim.js --redact)"
  kim_status=$?
  set -e

  test "$wechat_status" -eq 2
  test "$kim_status" -eq 2

  WECHAT_REPORT="$wechat_report" KIM_REPORT="$kim_report" \
    node --input-type=module <<'NODE'
const expectedShape = [
  'adapterVersion',
  'capabilities',
  'failureCodes',
  'fieldMappings',
]
const expectedCapabilities = [
  'authoritativeDirectionOrSender',
  'conversationAndParticipantIdentity',
  'finalMessageText',
  'incrementalChangeDetection',
  'sourceAccountIdentity',
  'stableMessageIdentity',
  'timestampOrOrdering',
]
const expectedMappings = [
  'authoritativeDirectionOrSender',
  'conversationIdentity',
  'finalMessageText',
  'incrementalChangeDetection',
  'participantIdentity',
  'sourceAccountIdentity',
  'stableMessageIdentity',
  'timestampOrOrdering',
]

for (const [environmentName, failureCode, adapterVersion] of [
  ['WECHAT_REPORT', 'WECHAT_ATOMIC_OPEN_UNAVAILABLE', 'wechat-macos-xwechat-v4-v1'],
  ['KIM_REPORT', 'KIM_ATOMIC_OPEN_UNAVAILABLE', 'kim-macos-structured-v1'],
]) {
  const report = JSON.parse(process.env[environmentName])
  const shape = Object.keys(report).sort()
  if (JSON.stringify(shape) !== JSON.stringify(expectedShape)) process.exit(1)
  if (typeof report.adapterVersion !== 'string') process.exit(1)
  if (report.adapterVersion !== adapterVersion) process.exit(1)
  if (JSON.stringify(report.failureCodes) !== JSON.stringify([failureCode])) process.exit(1)

  const capabilities = Object.entries(report.capabilities)
  const mappings = Object.entries(report.fieldMappings)
  if (JSON.stringify(capabilities.map(([name]) => name).sort()) !==
      JSON.stringify(expectedCapabilities)) process.exit(1)
  if (JSON.stringify(mappings.map(([name]) => name).sort()) !==
      JSON.stringify(expectedMappings)) process.exit(1)
  if (!capabilities.every(([, available]) => available === false)) process.exit(1)
  if (!mappings.every(([, mapping]) => mapping === null)) process.exit(1)
}
NODE
)
```

Both probe commands execute before either status is checked. Exit status `2`
with the exact redacted JSON above is the expected G2 `BLOCK`; any other status,
shape, failure code, capability value, or mapping value makes reproduction fail.
Captured probe output is validated without being printed.

The synthetic tests prove the source-neutral contract, parser behavior, path
containment, redaction, cleanup, and safe failure behavior. They do **not** prove
the real WeChat or Kim schema, field meanings, source stability, or any of the
business capabilities below.

## WeChat capability decision

The redacted report exposes the single public failure code
`WECHAT_ATOMIC_OPEN_UNAVAILABLE`. Its capability booleans are `false` and its
field mappings are `null`, so every requirement remains unproven.

| Required capability | Decision | Public failure code |
|---|---|---|
| Source account identity | `NOT PROVEN / BLOCK` | `WECHAT_ATOMIC_OPEN_UNAVAILABLE` |
| Conversation and participant identity | `NOT PROVEN / BLOCK` | `WECHAT_ATOMIC_OPEN_UNAVAILABLE` |
| Stable message identity | `NOT PROVEN / BLOCK` | `WECHAT_ATOMIC_OPEN_UNAVAILABLE` |
| Final message text | `NOT PROVEN / BLOCK` | `WECHAT_ATOMIC_OPEN_UNAVAILABLE` |
| Authoritative direction or sender | `NOT PROVEN / BLOCK` | `WECHAT_ATOMIC_OPEN_UNAVAILABLE` |
| Timestamp or ordering key | `NOT PROVEN / BLOCK` | `WECHAT_ATOMIC_OPEN_UNAVAILABLE` |
| Incremental change detection | `NOT PROVEN / BLOCK` | `WECHAT_ATOMIC_OPEN_UNAVAILABLE` |

WeChat source decision: **BLOCK**. Its production connector remains disabled.

## Kim capability decision

The redacted report exposes the single public failure code
`KIM_ATOMIC_OPEN_UNAVAILABLE`. Its capability booleans are `false` and its
field mappings are `null`, so every requirement remains unproven.

| Required capability | Decision | Public failure code |
|---|---|---|
| Source account identity | `NOT PROVEN / BLOCK` | `KIM_ATOMIC_OPEN_UNAVAILABLE` |
| Conversation and participant identity | `NOT PROVEN / BLOCK` | `KIM_ATOMIC_OPEN_UNAVAILABLE` |
| Stable message identity | `NOT PROVEN / BLOCK` | `KIM_ATOMIC_OPEN_UNAVAILABLE` |
| Final message text | `NOT PROVEN / BLOCK` | `KIM_ATOMIC_OPEN_UNAVAILABLE` |
| Authoritative direction or sender | `NOT PROVEN / BLOCK` | `KIM_ATOMIC_OPEN_UNAVAILABLE` |
| Timestamp or ordering key | `NOT PROVEN / BLOCK` | `KIM_ATOMIC_OPEN_UNAVAILABLE` |
| Incremental change detection | `NOT PROVEN / BLOCK` | `KIM_ATOMIC_OPEN_UNAVAILABLE` |

Kim source decision: **BLOCK**. Its production connector remains disabled.

## Risk disposition and unblock conditions

Continuing would require guessing source paths or schemas, accepting a
time-of-check/time-of-use race, or using a prohibited fallback. Any of those
would violate the read-only safety boundary and could misattribute identities,
direction, revisions, or conversation participation.

To re-open this gate for either source:

1. Provide a reviewed atomic directory-FD/`openat` helper, or a source-owned
   read-only structured interface. This is a prerequisite, not proof that the
   source will pass.
2. Re-run that source's live redacted probe through the reviewed path.
3. Produce authoritative and stable live evidence for every capability in its
   table. All requirements must pass; partial evidence remains `BLOCK`.

The local pinned DSH RC5 G1 result and this source G2 result are independent:
G1 is `PASS` for the pinned local runtime, while portable npm RC5 distribution
is separately `BLOCKED`. Neither result supplies missing live source evidence.

No downstream implementation was executed. Storage, migration, and production
connectors were not added; real services were not changed; and the existing
legacy keyboard/OCR capture remains active and unchanged.
