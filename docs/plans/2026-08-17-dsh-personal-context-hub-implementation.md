# DSH Personal Context Hub Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace OmniMe's keyboard/OCR chat capture with a DSH-native, passive Personal Context bundle that synchronizes qualifying Kim and WeChat conversations, integrates ASR, stores encrypted local facts, and exposes retrieval plus a DSH Web GUI.

**Architecture:** Build one installable out-of-tree DSH bundle under `dsh-plugin/`. The bundle owns a `personalContext` Cordis service, source connectors, encrypted SQLite store, scheduler, tools, Remote API, and browser plugin. A single loopback-only DSH Web process runs continuously; DSH Session Log stores evidence references, while long-term personal data remains in the plugin database.

**Tech Stack:** TypeScript, Node.js 22.19+, DSH `0.1.0-rc.5` compatibility baseline, Cordis plugins, React 18, Vitest, `better-sqlite3-multiple-ciphers`, `@napi-rs/keyring`, SQLite FTS5, existing Python/pytest only for the legacy OmniMe cutover.

---

## Execution rules

- Use @test-driven-development for every production change.
- Use @systematic-debugging for every unexpected test or live-source failure.
- Use @verification-before-completion before each gate and before claiming a source works.
- Use @requesting-code-review before the shadow-sync and production-cutover gates.
- Execute in a dedicated `codex/dsh-personal-context` worktree, not directly on `main`.
- Never commit real Kim, WeChat, ASR, Keychain, database, or message data.
- Use only synthetic fixtures with invented participants and text.
- Do not proceed past a failed gate. A blocked source remains disabled; it does not fall back to OCR, Accessibility text scraping, synthetic keys, clipboard access, injection, or network interception.
- Pin DSH to the tested release and commit in `dsh-plugin/DSH_COMPATIBILITY.md`. Do not use floating `latest` ranges.

## Gate map

| Gate | Required evidence | Failure action |
|---|---|---|
| G1 DSH compatibility | Out-of-tree bundle installs, Host service boots, tool registers, client page renders | Stop and update the integration design for the actual DSH API |
| G2 source feasibility | Both Kim and WeChat expose stable ID, final text, authoritative direction, conversation/account identity, and incremental ordering through safe local reads | Stop that source; do not implement or claim it |
| G3 data/privacy | Encrypted store, participation filter, idempotency, revisions, exclusions, and no-body diagnostics pass | Return to data model or privacy implementation |
| G4 feature review | Tools, Remote API, GUI, ASR, and shadow synchronization pass review and focused tests | Fix findings before cutover |
| G5 deployment health | One launchd-managed DSH Web process is healthy, loopback-only, low-idle-load, and resumes cursors after restart | Roll back service install; keep legacy system active |
| G6 live acceptance | Real Kim and WeChat bidirectional samples synchronize accurately with zero visible app interaction | Disable failing connector and preserve legacy data |

### Task 1: Create the isolated implementation worktree and baseline report

**Files:**
- Create: `docs/verification/dsh-personal-context-baseline.md`

**Step 1: Create the worktree**

From the existing checkout, run:

```bash
git worktree add ../ominime-dsh-personal-context -b codex/dsh-personal-context main
```

Expected: a clean worktree at `../ominime-dsh-personal-context`.

**Step 2: Record immutable baselines**

In the new worktree, record:

```markdown
# DSH Personal Context Baseline

- OmniMe base commit: `<git rev-parse HEAD>`
- DSH release: `0.1.0-rc.5`
- DSH source commit: `47f943859bef60e4160492346772ded9b24f765a`
- Node minimum: `22.19`
- Legacy database: preserved, never migrated in place
- Legacy keyboard/OCR capture: remains active until G4 passes
```

**Step 3: Run the existing suite**

Run:

```bash
PYTHONPATH=src venv/bin/python -m pytest -q
```

Expected: all existing tests pass. Record the exact result without piping through `tail`.

**Step 4: Commit**

```bash
git add docs/verification/dsh-personal-context-baseline.md
git commit -m "docs: record personal context baseline"
```

### Task 2: Scaffold and prove the out-of-tree DSH bundle

**Files:**
- Create: `dsh-plugin/package.json`
- Create: `dsh-plugin/pnpm-workspace.yaml`
- Create: `dsh-plugin/tsconfig.json`
- Create: `dsh-plugin/tsconfig.client.json`
- Create: `dsh-plugin/tsdown.config.ts`
- Create: `dsh-plugin/vitest.config.ts`
- Create: `dsh-plugin/cordis.patch.yml`
- Create: `dsh-plugin/src/index.ts`
- Create: `dsh-plugin/src/client/index.tsx`
- Create: `dsh-plugin/tests/bundle.spec.ts`
- Create: `dsh-plugin/scripts/smoke-install.mjs`
- Create: `dsh-plugin/DSH_COMPATIBILITY.md`

**Step 1: Write the failing manifest test**

`dsh-plugin/tests/bundle.spec.ts`:

```ts
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = resolve(import.meta.dirname, '..')

describe('DSH bundle contract', () => {
  it('declares one installable bundle and one web client entry', () => {
    const manifest = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
    expect(manifest.dsh.bundle.patch).toBe('./cordis.patch.yml')
    expect(manifest.dsh.client.platform).toBe('web')
    expect(manifest.version).not.toMatch(/[x*]/)
  })

  it('pins the verified DSH compatibility baseline', () => {
    const text = readFileSync(resolve(root, 'DSH_COMPATIBILITY.md'), 'utf8')
    expect(text).toContain('0.1.0-rc.5')
    expect(text).toContain('47f943859bef60e4160492346772ded9b24f765a')
  })
})
```

**Step 2: Run the test and verify RED**

Run:

```bash
pnpm --dir dsh-plugin exec vitest run tests/bundle.spec.ts
```

Expected: FAIL because the plugin package does not exist yet.

**Step 3: Add the minimal bundle**

Use package name `@ominime/dsh-personal-context`, exact version `0.1.0`, ESM,
and exact DSH `0.1.0-rc.5` peer/dev dependency versions. The manifest must
declare:

```json
{
  "dsh": {
    "bundle": { "patch": "./cordis.patch.yml" },
    "client": {
      "inject": [
        "@deepseek-ai/dsh-client-runtime",
        "@deepseek-ai/dsh-api-remotes",
        "@deepseek-ai/dsh-client-ui-slots"
      ],
      "platform": "web"
    }
  }
}
```

The first Host plugin exports `name = 'personal-context'` and an `apply(ctx)`
that registers a read-only `personal_context_health` tool returning only:

```ts
{ status: 'scaffold', schemaVersion: 0, sources: [] }
```

The first client renders a `Personal Context` placeholder into the verified DSH
slot discovered from the pinned source. Do not guess a route or slot: encode the
chosen extension point and source reference in `DSH_COMPATIBILITY.md`.

**Step 4: Run unit and build checks**

```bash
pnpm --dir dsh-plugin install --frozen-lockfile=false
pnpm --dir dsh-plugin test
pnpm --dir dsh-plugin build
```

Expected: PASS and built Host/client artifacts exist under `dsh-plugin/lib/`.

**Step 5: Run the isolated DSH install smoke test**

The smoke script must create a temporary `DSH_HOME`, run:

```bash
dsh plugin --profile web add ./dsh-plugin
dsh --profile web --dump-config
```

and assert the config contains the Personal Context Host row and browser row.
It must not modify the user's real `~/.dsh`.

Run:

```bash
node dsh-plugin/scripts/smoke-install.mjs
```

Expected: PASS with the temporary directory removed in `finally`.

**Step 6: Manually verify the client placeholder**

Start the isolated profile on an unused loopback port, open it, and verify the
Personal Context entry renders without replacing the normal DSH conversation
surface. Stop the process after the check.

**Step 7: Apply G1**

G1 passes only when install, Host tool, Remote/client wiring feasibility, and GUI
render all work against the pinned DSH version. If any part fails, stop and amend
the design before adding storage or source code.

**Step 8: Commit**

```bash
git add dsh-plugin
git commit -m "feat: scaffold DSH personal context bundle"
```

### Task 3: Define the source-neutral connector contract

**Files:**
- Create: `dsh-plugin/src/domain/types.ts`
- Create: `dsh-plugin/src/connectors/contract.ts`
- Create: `dsh-plugin/src/connectors/registry.ts`
- Create: `dsh-plugin/tests/connector-contract.spec.ts`
- Create: `dsh-plugin/tests/fixtures/synthetic-chat.ts`

**Step 1: Write failing contract tests**

Test that a synthetic connector:

- discovers a self account;
- pages conversations without message bodies in health data;
- returns `self`, `other`, `system`, and `unknown` directions;
- exposes capability flags;
- resumes from an opaque cursor;
- throws `SourceIncompatibleError` instead of returning guessed data.

Core types must be:

```ts
export type MessageDirection = 'self' | 'other' | 'system' | 'unknown'
export type MessageChangeKind = 'create' | 'edit' | 'retract' | 'delete'

export interface SourceMessageChange {
  source: string
  accountId: string
  conversationId: string
  messageId: string
  authorId: string | null
  direction: MessageDirection
  kind: MessageChangeKind
  text: string | null
  replyToMessageId: string | null
  sourceOrder: string
  sourceTimestamp: string
  observedAt: string
}

export interface SourceConnector {
  readonly id: string
  discoverAccounts(signal: AbortSignal): Promise<SourceAccount[]>
  discoverConversations(cursor: string | null, signal: AbortSignal): Promise<ConversationPage>
  syncMessages(ref: ConversationRef, cursor: string | null, signal: AbortSignal): Promise<MessageChangePage>
  backfill(ref: ConversationRef, boundary: string | null, signal: AbortSignal): Promise<MessagePage>
  health(): SourceHealth
}
```

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/connector-contract.spec.ts
```

Expected: FAIL on missing contract and registry.

**Step 3: Implement the smallest contract and registry**

The registry rejects duplicate connector IDs, returns immutable snapshots, and
disposes all connector resources when its Cordis effect unloads.

**Step 4: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/connector-contract.spec.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/src/domain dsh-plugin/src/connectors dsh-plugin/tests
git commit -m "feat: define personal context connector contract"
```

### Task 4: Prove safe WeChat structured access

**Files:**
- Create: `dsh-plugin/src/connectors/wechat/paths.ts`
- Create: `dsh-plugin/src/connectors/wechat/snapshot.ts`
- Create: `dsh-plugin/src/connectors/wechat/probe.ts`
- Create: `dsh-plugin/src/connectors/wechat/index.ts`
- Create: `dsh-plugin/tests/wechat-paths.spec.ts`
- Create: `dsh-plugin/tests/wechat-probe.spec.ts`
- Create: `dsh-plugin/tests/fixtures/wechat/README.md`
- Create: `dsh-plugin/tests/fixtures/wechat/synthetic-manifest.json`
- Create: `docs/verification/wechat-source-feasibility.md`

**Step 1: Write path-containment tests**

Tests must reject:

- paths outside the configured WeChat container;
- symlink escapes;
- unresolved account directories;
- writable source opens;
- source file names not explicitly recognized by the adapter version.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-paths.spec.ts tests/wechat-probe.spec.ts
```

Expected: FAIL on missing probe.

**Step 3: Implement a read-only snapshot probe**

The probe copies only the explicitly validated database, WAL, and SHM files to a
task-owned temporary directory, then opens the copy. It never opens the live
database in writable mode. Cleanup runs in `finally`.

The probe emits schema and capability metadata only. It must never print or
write real message bodies, participant names, account IDs, or keys.

**Step 4: Run synthetic tests**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-paths.spec.ts tests/wechat-probe.spec.ts
```

Expected: PASS with invented fixtures.

**Step 5: Run the live read-only probe**

```bash
pnpm --dir dsh-plugin probe:wechat -- --redact
```

Expected: a redacted report proving or disproving:

- source account identity;
- conversation identity;
- stable message identity;
- final text availability;
- authoritative direction/sender;
- timestamp/order;
- incremental cursor/change detection.

Write only the boolean result, field mapping names, adapter version, and failure
codes to `docs/verification/wechat-source-feasibility.md`.

**Step 6: Commit the proof, not user data**

```bash
git add dsh-plugin/src/connectors/wechat dsh-plugin/tests/wechat-*.spec.ts dsh-plugin/tests/fixtures/wechat docs/verification/wechat-source-feasibility.md
git commit -m "spike: verify structured WeChat source"
```

### Task 5: Prove safe Kim structured access

**Files:**
- Create: `dsh-plugin/src/connectors/kim/paths.ts`
- Create: `dsh-plugin/src/connectors/kim/snapshot.ts`
- Create: `dsh-plugin/src/connectors/kim/probe.ts`
- Create: `dsh-plugin/src/connectors/kim/index.ts`
- Create: `dsh-plugin/tests/kim-paths.spec.ts`
- Create: `dsh-plugin/tests/kim-probe.spec.ts`
- Create: `dsh-plugin/tests/fixtures/kim/README.md`
- Create: `dsh-plugin/tests/fixtures/kim/synthetic-manifest.json`
- Create: `docs/verification/kim-source-feasibility.md`

**Step 1: Write the same containment and redaction tests as WeChat**

Add format detection tests for Kim's nonstandard or encrypted local store. An
unknown header or app version must produce `SourceIncompatibleError`.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/kim-paths.spec.ts tests/kim-probe.spec.ts
```

Expected: FAIL.

**Step 3: Implement the minimum read-only Kim probe**

Use a copied, validated snapshot. If the actual source is not SQLite, keep
format parsing behind `KimStoreReader`; do not leak format-specific logic into
the source-neutral contract.

**Step 4: Run synthetic and live redacted probes**

```bash
pnpm --dir dsh-plugin exec vitest run tests/kim-paths.spec.ts tests/kim-probe.spec.ts
pnpm --dir dsh-plugin probe:kim -- --redact
```

Expected: tests pass and the live report proves or disproves the same seven G2
capabilities as WeChat.

**Step 5: Commit the proof, not user data**

```bash
git add dsh-plugin/src/connectors/kim dsh-plugin/tests/kim-*.spec.ts dsh-plugin/tests/fixtures/kim docs/verification/kim-source-feasibility.md
git commit -m "spike: verify structured Kim source"
```

### Task 6: Apply the source feasibility gate

**Files:**
- Create: `docs/verification/chat-source-gate.md`
- Modify: `dsh-plugin/DSH_COMPATIBILITY.md`

**Step 1: Review both source reports**

For each required capability, link to reproducible redacted evidence. Mark the
source `PASS` only if every requirement is authoritative and stable.

**Step 2: Run all probe tests**

```bash
pnpm --dir dsh-plugin exec vitest run tests/connector-contract.spec.ts tests/wechat-paths.spec.ts tests/wechat-probe.spec.ts tests/kim-paths.spec.ts tests/kim-probe.spec.ts
```

Expected: PASS.

**Step 3: Apply G2**

- If both sources pass, continue.
- If either fails, stop implementation for that source and report the exact
  missing capability. Do not continue to migration or disable legacy capture.
- If the user still requires both sources, the feature gate is blocked until a
  safe, source-owned structured interface becomes available.

**Step 4: Commit**

```bash
git add docs/verification/chat-source-gate.md dsh-plugin/DSH_COMPATIBILITY.md
git commit -m "docs: decide chat source feasibility gate"
```

### Task 7: Add Keychain-backed encrypted SQLite storage

**Files:**
- Modify: `dsh-plugin/package.json`
- Modify: `dsh-plugin/pnpm-lock.yaml`
- Create: `dsh-plugin/src/security/key-provider.ts`
- Create: `dsh-plugin/src/security/macos-keychain.ts`
- Create: `dsh-plugin/src/store/database.ts`
- Create: `dsh-plugin/tests/key-provider.spec.ts`
- Create: `dsh-plugin/tests/encrypted-database.spec.ts`
- Create: `dsh-plugin/scripts/keychain-doctor.mjs`

**Step 1: Write failing encryption tests**

Tests must prove:

- a 32-byte key is created once and then reused;
- the key is never logged or returned by health APIs;
- an encrypted database reopens with the correct key;
- opening it without the key or with another key fails;
- database, WAL, SHM, and backup permissions are owner-only;
- a locked or denied Keychain fails startup loudly without creating a plaintext
  database.

Use an in-memory fake `KeyProvider` in ordinary tests.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/key-provider.spec.ts tests/encrypted-database.spec.ts
```

Expected: FAIL.

**Step 3: Pin native dependencies**

Use exact versions validated on the target Mac and Node runtime:

```json
{
  "dependencies": {
    "@napi-rs/keyring": "1.3.0",
    "better-sqlite3-multiple-ciphers": "12.11.1"
  }
}
```

Audit and explicitly approve only the required native build scripts. Commit the
lockfile.

**Step 4: Implement the providers**

`MacOSKeychainProvider` uses service `com.ominime.personal-context` and account
`database-key-v1`. It generates the key with `crypto.randomBytes(32)` and stores
it through the native Keychain binding. It never falls back to a plaintext file
or command-line argument.

`EncryptedDatabase.open()` obtains the key before creating/opening the file,
applies the cipher key, verifies a sentinel table, enables foreign keys, and
then applies owner-only permissions.

**Step 5: Verify GREEN and native doctor**

```bash
pnpm --dir dsh-plugin exec vitest run tests/key-provider.spec.ts tests/encrypted-database.spec.ts
node dsh-plugin/scripts/keychain-doctor.mjs --round-trip --cleanup
```

Expected: PASS; the doctor creates, reads, and removes only a dedicated test
entry.

**Step 6: Commit**

```bash
git add dsh-plugin/package.json dsh-plugin/pnpm-lock.yaml dsh-plugin/src/security dsh-plugin/src/store/database.ts dsh-plugin/tests dsh-plugin/scripts/keychain-doctor.mjs
git commit -m "feat: add encrypted personal context storage"
```

### Task 8: Add the append-only schema and local full-text index

**Files:**
- Create: `dsh-plugin/src/store/migrations/001_initial.sql`
- Create: `dsh-plugin/src/store/migrate.ts`
- Create: `dsh-plugin/src/store/repository.ts`
- Create: `dsh-plugin/src/store/models.ts`
- Create: `dsh-plugin/tests/migrations.spec.ts`
- Create: `dsh-plugin/tests/repository.spec.ts`

**Step 1: Write failing schema tests**

Test transactional migration, repeat migration, rollback on invalid SQL,
owner-only backup, foreign keys, FTS search, and append-only message revisions.

The initial migration must create normalized storage for:

- source accounts and source identities;
- people and reversible identity links;
- conversations and participants;
- message change events and current projections;
- sync cursors and connector health;
- privacy exclusions;
- recordings and transcript segments;
- knowledge items and evidence links;
- redacted diagnostics and quarantine metadata;
- FTS content tied to current, non-excluded text projections.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/migrations.spec.ts tests/repository.spec.ts
```

Expected: FAIL.

**Step 3: Implement migration and repository transactions**

Repository methods must accept complete domain records, use bound parameters,
and never expose arbitrary SQL to connectors, tools, or the GUI.

**Step 4: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/migrations.spec.ts tests/repository.spec.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/src/store dsh-plugin/tests/migrations.spec.ts dsh-plugin/tests/repository.spec.ts
git commit -m "feat: add personal context fact schema"
```

### Task 9: Implement participation filtering, normalization, and identity

**Files:**
- Create: `dsh-plugin/src/ingest/normalizer.ts`
- Create: `dsh-plugin/src/ingest/participation-gate.ts`
- Create: `dsh-plugin/src/identity/service.ts`
- Create: `dsh-plugin/tests/normalizer.spec.ts`
- Create: `dsh-plugin/tests/participation-gate.spec.ts`
- Create: `dsh-plugin/tests/identity.spec.ts`

**Step 1: Write failing behavior tests**

Cover:

- a conversation without a `self` message leaves no persisted message body;
- the first authoritative `self` message qualifies the conversation;
- backfill then retains complete earlier and later context;
- `unknown` never becomes `self` through text heuristics;
- source `replyToMessageId` is authoritative;
- inferred relations remain separate and low-confidence;
- duplicate source change IDs are idempotent;
- person merge and split are versioned and reversible.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/normalizer.spec.ts tests/participation-gate.spec.ts tests/identity.spec.ts
```

Expected: FAIL.

**Step 3: Implement the minimal services**

Process discovery in a transaction-local staging structure. Persist message
bodies only after qualification. Normalize all timestamps to UTC while retaining
the source timestamp and source order.

**Step 4: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/normalizer.spec.ts tests/participation-gate.spec.ts tests/identity.spec.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/src/ingest dsh-plugin/src/identity dsh-plugin/tests
git commit -m "feat: normalize qualifying personal conversations"
```

### Task 10: Add bounded synchronization, cursors, reconciliation, and health

**Files:**
- Create: `dsh-plugin/src/sync/coordinator.ts`
- Create: `dsh-plugin/src/sync/scheduler.ts`
- Create: `dsh-plugin/src/sync/backoff.ts`
- Create: `dsh-plugin/src/sync/health.ts`
- Create: `dsh-plugin/tests/sync-coordinator.spec.ts`
- Create: `dsh-plugin/tests/scheduler.spec.ts`
- Create: `dsh-plugin/tests/sync-health.spec.ts`
- Modify: `dsh-plugin/src/index.ts`
- Modify: `dsh-plugin/cordis.patch.yml`

**Step 1: Write failing scheduler tests**

Use fake clocks and abort signals to cover:

- one-minute default polling;
- six-hour reconciliation;
- one active job per connector;
- cursor commit only after data commit;
- restart resumes from the committed cursor;
- bounded exponential backoff with jitter;
- circuit breaker after configured consecutive failures;
- pause and shutdown cancel reads and dispose timers;
- one connector failure does not affect another;
- health output contains counts/codes, never message text.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/sync-coordinator.spec.ts tests/scheduler.spec.ts tests/sync-health.spec.ts
```

Expected: FAIL.

**Step 3: Implement scheduler as a Cordis-managed effect**

Do not create detached promises. Every timer, watcher, and in-flight read must be
owned by the plugin lifecycle and settle on dispose. Keep backfill low-priority
and pausable.

**Step 4: Verify GREEN and idle behavior**

```bash
pnpm --dir dsh-plugin exec vitest run tests/sync-coordinator.spec.ts tests/scheduler.spec.ts tests/sync-health.spec.ts
```

Expected: PASS with no open-handle warning.

**Step 5: Commit**

```bash
git add dsh-plugin/src/sync dsh-plugin/src/index.ts dsh-plugin/cordis.patch.yml dsh-plugin/tests
git commit -m "feat: schedule resilient context synchronization"
```

### Task 11: Turn the proven Kim and WeChat probes into production connectors

**Files:**
- Modify: `dsh-plugin/src/connectors/wechat/index.ts`
- Create: `dsh-plugin/src/connectors/wechat/reader.ts`
- Modify: `dsh-plugin/src/connectors/kim/index.ts`
- Create: `dsh-plugin/src/connectors/kim/reader.ts`
- Create: `dsh-plugin/tests/wechat-connector.spec.ts`
- Create: `dsh-plugin/tests/kim-connector.spec.ts`
- Create: `dsh-plugin/tests/connector-crash-recovery.spec.ts`

**Step 1: Write contract-conformance tests from redacted schemas**

Each connector must pass the same shared suite for account discovery,
conversation qualification, paging, final text, direction, replies, supported
mutations, incremental resume, source replacement, and app-version mismatch.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/wechat-connector.spec.ts tests/kim-connector.spec.ts tests/connector-crash-recovery.spec.ts
```

Expected: FAIL because probes do not yet implement the full contract.

**Step 3: Implement from the proven field maps only**

Do not broaden file access or add heuristic sender classification. Every
production mapping must point back to a G2 evidence row.

**Step 4: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/connector-contract.spec.ts tests/wechat-connector.spec.ts tests/kim-connector.spec.ts tests/connector-crash-recovery.spec.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/src/connectors dsh-plugin/tests
git commit -m "feat: synchronize Kim and WeChat histories"
```

### Task 12: Add privacy-first search and DSH tools

**Files:**
- Create: `dsh-plugin/src/privacy/policy.ts`
- Create: `dsh-plugin/src/search/service.ts`
- Create: `dsh-plugin/src/tools/personal-context-tools.ts`
- Create: `dsh-plugin/tests/privacy-policy.spec.ts`
- Create: `dsh-plugin/tests/search.spec.ts`
- Create: `dsh-plugin/tests/tools.spec.ts`
- Modify: `dsh-plugin/src/index.ts`

**Step 1: Write failing privacy tests**

Cover exclusions at app, account, conversation, person, and item level. Assert
excluded text is absent from FTS, knowledge derivation inputs, tool output, and
Remote API results.

**Step 2: Write failing tool tests**

Register:

```text
personal_context.search
personal_context.get_conversation
personal_context.get_timeline
personal_context.get_person
personal_context.get_evidence
```

Assert results are bounded, include opaque evidence IDs, omit unrequested full
histories, and never expose an SQL or filesystem interface.

**Step 3: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/privacy-policy.spec.ts tests/search.spec.ts tests/tools.spec.ts
```

Expected: FAIL.

**Step 4: Implement policy-before-retrieval**

Apply exclusions before query ranking and again before serialization. The
system-prompt contribution describes the tools but contains no personal data.
Default interaction is tool-first; automatic context injection remains off.

**Step 5: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/privacy-policy.spec.ts tests/search.spec.ts tests/tools.spec.ts
```

Expected: PASS.

**Step 6: Apply G3**

Run Tasks 7–12 focused tests together and inspect logs for message fixtures.
G3 passes only if encryption, participation, revisions, idempotency, exclusions,
and no-body diagnostics all pass.

**Step 7: Commit**

```bash
git add dsh-plugin/src/privacy dsh-plugin/src/search dsh-plugin/src/tools dsh-plugin/src/index.ts dsh-plugin/tests
git commit -m "feat: expose privacy-filtered context tools"
```

### Task 13: Add a typed Host-to-Web API and Personal Context shell

**Files:**
- Create: `dsh-plugin/src/remote/service.ts`
- Create: `dsh-plugin/src/remote/contracts.ts`
- Create: `dsh-plugin/src/client/api.ts`
- Create: `dsh-plugin/src/client/PersonalContextApp.tsx`
- Create: `dsh-plugin/src/client/navigation.tsx`
- Create: `dsh-plugin/src/client/styles.css`
- Create: `dsh-plugin/tests/remote-service.spec.ts`
- Create: `dsh-plugin/tests/client-shell.spec.tsx`
- Modify: `dsh-plugin/src/client/index.tsx`

**Step 1: Write failing Remote API tests**

The API exposes typed methods for overview, source health, conversations,
search, knowledge, ASR, identities, privacy policies, and job actions. Assert:

- request limits and cursor validation;
- loopback/trusted DSH transport only;
- no raw database path or key exposure;
- no message body in overview/health;
- destructive actions require an explicit confirmation token.

**Step 2: Write failing shell tests**

Test a top-level `Personal Context` entry and five views:

```text
Overview | Conversations | Search & Knowledge | ASR | Sources & Privacy
```

The first render must show loading, empty, error, and unavailable-connector
states without crashing the DSH shell.

**Step 3: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/remote-service.spec.ts tests/client-shell.spec.tsx
```

Expected: FAIL.

**Step 4: Implement against the G1-proven Remote and UI seams**

Use DSH's generated/typed Remote mechanism if G1 proved it for an out-of-tree
plugin. If G1 selected another official seam, use exactly that documented seam;
do not add an unauthenticated ad-hoc HTTP server.

**Step 5: Verify GREEN and build**

```bash
pnpm --dir dsh-plugin exec vitest run tests/remote-service.spec.ts tests/client-shell.spec.tsx
pnpm --dir dsh-plugin build
```

Expected: PASS.

**Step 6: Commit**

```bash
git add dsh-plugin/src/remote dsh-plugin/src/client dsh-plugin/tests
git commit -m "feat: add DSH Personal Context GUI shell"
```

### Task 14: Implement overview, conversations, search, knowledge, and privacy UI

**Files:**
- Create: `dsh-plugin/src/client/views/OverviewView.tsx`
- Create: `dsh-plugin/src/client/views/ConversationsView.tsx`
- Create: `dsh-plugin/src/client/views/SearchKnowledgeView.tsx`
- Create: `dsh-plugin/src/client/views/SourcesPrivacyView.tsx`
- Create: `dsh-plugin/src/client/components/EvidenceDrawer.tsx`
- Create: `dsh-plugin/src/client/components/SourceStatusCard.tsx`
- Create: `dsh-plugin/src/client/components/ConversationTimeline.tsx`
- Create: `dsh-plugin/tests/overview-view.spec.tsx`
- Create: `dsh-plugin/tests/conversations-view.spec.tsx`
- Create: `dsh-plugin/tests/search-knowledge-view.spec.tsx`
- Create: `dsh-plugin/tests/privacy-view.spec.tsx`

**Step 1: Write failing user-flow tests**

Cover:

- source status, last success, lag, queued work, and redacted error code;
- app/account/person/direction/time conversation filters;
- distinct self/other/system timeline rendering;
- edit, retraction, and reply indicators;
- evidence drill-down;
- pause, sync now, backfill, and rebuild actions;
- identity merge/split and conversation exclusion;
- separate derived-knowledge and raw-data deletion confirmations;
- all empty, loading, stale, incompatible, and permission-denied states.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/*-view.spec.tsx
```

Expected: FAIL.

**Step 3: Implement the views**

Keep message text out of browser console output and error telemetry. Use cursor
pagination; do not fetch a full conversation list or full history at startup.

**Step 4: Verify GREEN and accessibility basics**

```bash
pnpm --dir dsh-plugin exec vitest run tests/*-view.spec.tsx
```

Expected: PASS with role/name-based selectors and keyboard-reachable controls.

**Step 5: Commit**

```bash
git add dsh-plugin/src/client dsh-plugin/tests
git commit -m "feat: build personal context management views"
```

### Task 15: Add ASR as another source connector

**Files:**
- Create: `dsh-plugin/src/connectors/asr/index.ts`
- Create: `dsh-plugin/src/asr/service.ts`
- Create: `dsh-plugin/src/client/views/AsrView.tsx`
- Create: `dsh-plugin/tests/asr-connector.spec.ts`
- Create: `dsh-plugin/tests/asr-identity.spec.ts`
- Create: `dsh-plugin/tests/asr-view.spec.tsx`

**Step 1: Write failing ASR tests**

Cover recording references, timestamped segments, `unknown` as the default
speaker, confirmed self identity, manual correction, reversible person mapping,
and rejection of a timestamp-only chat association.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/asr-connector.spec.ts tests/asr-identity.spec.ts tests/asr-view.spec.tsx
```

Expected: FAIL.

**Step 3: Implement metadata-first ASR ingestion**

Reference audio in place; do not duplicate the file. Persist transcript segments
and source evidence. Candidate chat associations require multiple signals and
remain low-confidence until confirmed in the GUI.

**Step 4: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/asr-connector.spec.ts tests/asr-identity.spec.ts tests/asr-view.spec.tsx
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/src/connectors/asr dsh-plugin/src/asr dsh-plugin/src/client/views/AsrView.tsx dsh-plugin/tests
git commit -m "feat: ingest ASR context with speaker correction"
```

### Task 16: Add traceable local knowledge derivation

**Files:**
- Create: `dsh-plugin/src/knowledge/types.ts`
- Create: `dsh-plugin/src/knowledge/rules.ts`
- Create: `dsh-plugin/src/knowledge/local-model.ts`
- Create: `dsh-plugin/src/knowledge/service.ts`
- Create: `dsh-plugin/tests/knowledge-rules.spec.ts`
- Create: `dsh-plugin/tests/knowledge-service.spec.ts`
- Create: `dsh-plugin/tests/knowledge-invalidation.spec.ts`

**Step 1: Write failing derivation tests**

Every derived item must include evidence IDs, derivation method/version,
confidence, validity, and supersession. Cover invalidation after edit,
retraction, delete, identity correction, and exclusion.

Assert the background service does not call a remote model. If no local model is
configured, it records `pending_local_model` and leaves ingestion/search healthy.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/knowledge-rules.spec.ts tests/knowledge-service.spec.ts tests/knowledge-invalidation.spec.ts
```

Expected: FAIL.

**Step 3: Implement deterministic rules first**

Add local-model extraction behind a provider interface. Do not make a remote
HTTP backend or OpenAI key setting part of this feature.

**Step 4: Verify GREEN**

```bash
pnpm --dir dsh-plugin exec vitest run tests/knowledge-rules.spec.ts tests/knowledge-service.spec.ts tests/knowledge-invalidation.spec.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add dsh-plugin/src/knowledge dsh-plugin/tests
git commit -m "feat: derive traceable local personal knowledge"
```

### Task 17: Run shadow synchronization and complete feature review

**Files:**
- Create: `docs/verification/dsh-personal-context-shadow-sync.md`
- Modify: `dsh-plugin/cordis.patch.yml`

**Step 1: Install into an isolated real DSH Web profile**

Enable `shadowMode: true`. In shadow mode, connectors and GUI work, but model
tools return `SHADOW_MODE` and no context enters an agent request.

**Step 2: Run bounded backfill**

Start with one explicitly selected Kim conversation and one WeChat conversation.
Verify source identity, participants, ordering, full context, edit/retraction
behavior, and duplicate-free restart.

**Step 3: Inspect privacy and runtime behavior**

Verify:

- no message body in logs or health;
- source applications remain responsive;
- no Accessibility, screenshot, OCR, clipboard, key event, focus, or network
  interception access occurs;
- idle CPU and I/O remain within the agreed local budget;
- stopping DSH leaves no watcher or helper process.

**Step 4: Run the full plugin suite**

```bash
pnpm --dir dsh-plugin test
pnpm --dir dsh-plugin build
node dsh-plugin/scripts/smoke-install.mjs
```

Expected: PASS with no open handles.

**Step 5: Request code review and apply G4**

Review source safety, encryption, privacy policy ordering, lifecycle ownership,
GUI destructive actions, and DSH compatibility. Fix every Critical/Important
finding and rerun the suite.

**Step 6: Commit**

```bash
git add docs/verification/dsh-personal-context-shadow-sync.md dsh-plugin/cordis.patch.yml
git commit -m "test: validate personal context shadow sync"
```

### Task 18: Import trustworthy legacy data without mutating the old database

**Files:**
- Create: `dsh-plugin/src/import/legacy-ominime.ts`
- Create: `dsh-plugin/tests/legacy-import.spec.ts`
- Create: `dsh-plugin/scripts/import-legacy.mjs`
- Create: `docs/verification/legacy-import.md`

**Step 1: Write failing import tests**

Use a synthetic copy of the legacy schema. Assert:

- source database opens read-only;
- import never changes its hash;
- only records with trustworthy final text and provenance are imported;
- imported records use source `legacy_ominime`;
- uncertain OCR/heuristic content does not enter derived knowledge;
- rerunning is idempotent.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/legacy-import.spec.ts
```

Expected: FAIL.

**Step 3: Implement dry-run-first import**

The CLI defaults to `--dry-run` and reports only counts and rejection reasons.
`--apply` requires an explicit destination and keeps the source untouched.

**Step 4: Verify GREEN and dry-run on the real legacy database**

```bash
pnpm --dir dsh-plugin exec vitest run tests/legacy-import.spec.ts
node dsh-plugin/scripts/import-legacy.mjs --dry-run
```

Expected: PASS and a redacted report. Confirm the legacy database hash is
unchanged.

**Step 5: Commit**

```bash
git add dsh-plugin/src/import dsh-plugin/tests/legacy-import.spec.ts dsh-plugin/scripts/import-legacy.mjs docs/verification/legacy-import.md
git commit -m "feat: import trustworthy legacy OmniMe records"
```

### Task 19: Remove Kim/WeChat keyboard and OCR capture after shadow acceptance

**Files:**
- Modify: `src/ominime/keyboard_listener.py`
- Modify: `src/ominime/main.py`
- Modify: `tests/test_keyboard_listener_capture.py`
- Modify: `tests/test_maintenance_surface.py`
- Delete if unreferenced: `src/ominime/post_send_capture.py`
- Delete if unreferenced: `src/ominime/chat_bubble_capture.py`
- Delete if unreferenced: `src/ominime/chat_window_capture.py`
- Delete if unreferenced: `src/ominime/chat_message_sources.py`
- Delete if unreferenced: `src/ominime/kim_composer_capture.py`
- Delete if unreferenced: `src/ominime/wechat_composer_capture.py`
- Delete corresponding obsolete tests only after replacement coverage exists
- Modify: `README.md`

**Step 1: Write failing passthrough tests**

Assert a Kim or WeChat Enter event is returned immediately and does not:

- enqueue a post-send capture;
- create a screenshot;
- call OCR;
- query Accessibility for message content;
- suppress keyDown or keyUp;
- change the clipboard;
- persist an input record.

Keep generic non-chat OmniMe behavior unchanged until equivalent source plugins
replace it.

**Step 2: Verify RED**

```bash
PYTHONPATH=src venv/bin/python -m pytest tests/test_keyboard_listener_capture.py tests/test_maintenance_surface.py -q
```

Expected: new tests fail against the legacy chat-capture path.

**Step 3: Remove the chat capture path surgically**

Use `rg` to prove each deleted module has no production references. Preserve the
legacy database and export code. Do not delete user data.

**Step 4: Run focused and full Python suites**

```bash
PYTHONPATH=src venv/bin/python -m pytest tests/test_keyboard_listener_capture.py tests/test_maintenance_surface.py -q
PYTHONPATH=src venv/bin/python -m pytest -q
```

Expected: PASS.

**Step 5: Commit**

Stage only the listed files and the exact obsolete modules proven unreferenced:

```bash
git add src/ominime/keyboard_listener.py src/ominime/main.py tests/test_keyboard_listener_capture.py tests/test_maintenance_surface.py README.md
git add -u -- src/ominime/post_send_capture.py src/ominime/chat_bubble_capture.py src/ominime/chat_window_capture.py src/ominime/chat_message_sources.py src/ominime/kim_composer_capture.py src/ominime/wechat_composer_capture.py
git add -u -- tests/test_post_send_capture.py tests/test_chat_bubble_capture.py tests/test_chat_window_capture.py tests/test_chat_message_sources.py
git commit -m "refactor: retire keyboard and OCR chat capture"
```

Before committing, inspect `git diff --cached --name-status` and unstage any
unrelated file.

### Task 20: Install one loopback-only DSH Web background service

**Files:**
- Create: `dsh-plugin/launchd/com.ominime.dsh-personal-context.plist`
- Create: `dsh-plugin/scripts/install-service.sh`
- Create: `dsh-plugin/scripts/uninstall-service.sh`
- Create: `dsh-plugin/scripts/status-service.sh`
- Create: `dsh-plugin/tests/service-scripts.spec.ts`
- Modify: `README.md`
- Create: `docs/verification/dsh-personal-context-deployment.md`

**Step 1: Write failing service-contract tests**

Assert the plist and scripts:

- run one `dsh --profile web` process;
- bind to `127.0.0.1` only;
- use the pinned profile and plugin bundle;
- do not embed API keys or database keys;
- write owner-only runtime files;
- expose install/status/uninstall without broad destructive paths;
- restart on crash with bounded launchd behavior;
- never start a second headless polling process.

**Step 2: Verify RED**

```bash
pnpm --dir dsh-plugin exec vitest run tests/service-scripts.spec.ts
```

Expected: FAIL.

**Step 3: Implement and test install in an isolated launchd label first**

Use explicit paths resolved by the installer. Do not use `~`, `$HOME`, or an
unresolved recursive target in cleanup commands.

**Step 4: Verify service health**

```bash
pnpm --dir dsh-plugin exec vitest run tests/service-scripts.spec.ts
bash dsh-plugin/scripts/status-service.sh
curl --fail --silent http://127.0.0.1:3080/
```

Expected: one healthy DSH Web process and one Personal Context scheduler.

**Step 5: Apply G5**

Restart the service and verify cursor resume, Keychain access, GUI loading,
loopback binding, low idle load, and no duplicate jobs. On failure, uninstall
the new service and leave the legacy system available.

**Step 6: Commit**

```bash
git add dsh-plugin/launchd dsh-plugin/scripts dsh-plugin/tests/service-scripts.spec.ts README.md docs/verification/dsh-personal-context-deployment.md
git commit -m "feat: run Personal Context as a local DSH service"
```

### Task 21: Complete real acceptance, retire port 8001, and prepare merge

**Files:**
- Create: `docs/verification/dsh-personal-context-live-acceptance.md`
- Modify: `src/ominime/scripts/install_web.sh`
- Modify: `src/ominime/scripts/uninstall_web.sh`
- Modify: `src/ominime/scripts/status_all.sh`
- Modify: `src/ominime/menu_bar_app.py`
- Modify: `tests/test_install_scripts_arch.py`
- Modify: `tests/test_menu_bar_daily_counter.py`
- Modify: `README.md`

**Step 1: Run real Kim acceptance**

In a dedicated conversation, verify:

- one self message;
- one other-person response;
- one reply/reference if supported;
- one edit/retraction if supported;
- stable identity and no duplicate after restart;
- no visible app interaction or send delay.

Record IDs and outcomes in redacted form only.

**Step 2: Run real WeChat acceptance**

Repeat the same matrix.

**Step 3: Run ASR acceptance**

Verify unknown speaker, manual correction, identity mapping, and rejection of an
incorrect chat association.

**Step 4: Apply G6**

G6 passes only when both required chat connectors and ASR behavior meet the
approved success criteria. Disable any failed connector and do not claim full
completion.

**Step 5: Write and verify the port-8001 retirement tests**

After DSH Web feature parity is confirmed, update the installer and menu bar so
they open `http://127.0.0.1:3080` and no longer auto-start the old Web dashboard.
Retain a read-only legacy export command; do not delete the legacy database.

Run:

```bash
PYTHONPATH=src venv/bin/python -m pytest tests/test_install_scripts_arch.py tests/test_menu_bar_daily_counter.py -q
```

Expected: PASS.

**Step 6: Run every verification command without output-truncating pipes**

```bash
pnpm --dir dsh-plugin test
pnpm --dir dsh-plugin build
node dsh-plugin/scripts/smoke-install.mjs
PYTHONPATH=src venv/bin/python -m pytest -q
git diff --check
```

Expected: all PASS and clean diff check.

**Step 7: Request final code review**

Require no unresolved Critical/Important findings. Re-run affected tests after
every fix.

**Step 8: Commit the acceptance and retirement**

```bash
git add docs/verification/dsh-personal-context-live-acceptance.md src/ominime/scripts src/ominime/menu_bar_app.py tests/test_install_scripts_arch.py tests/test_menu_bar_daily_counter.py README.md
git commit -m "feat: switch personal context control to DSH Web"
```

**Step 9: Merge and deploy only from a clean main**

Use @finishing-a-development-branch to choose the merge path. Before deployment:

```bash
git status --short
git log --oneline --decorate -10
```

Expected: clean implementation worktree and reviewed commits. Merge to `main`,
rerun the full verification from clean `main`, push, install the single DSH Web
service, and perform the G5/G6 smoke checks again.

## Deferred work

Do not include these in the first production cut:

- vector database or remote embeddings;
- attachment copying, vision, or OCR;
- automatic global context injection on every agent turn;
- process injection or network capture;
- background remote-model knowledge extraction;
- syncing conversations in which the user never participated;
- connectors for additional applications before Kim and WeChat pass G6.
