# Kim Chat Skill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a bundled DSH Skill and four restricted tools that let OmniMe query Kim through a locally verified `chatkimv2` MCP process without OCR, UI automation, arbitrary shell access, or background persistence.

**Architecture:** A lifecycle-owned TypeScript `ChatkimClient` validates a configured executable and speaks line-delimited MCP JSON-RPC over stdio. Restricted DSH tools validate and project reader results, while a packaged `kim-chat-history` Skill teaches the agent the bounded query workflow. Background source synchronization remains disabled.

**Tech Stack:** TypeScript 6, Node.js 22.19+, DSH `0.1.0-rc.5`, Cordis, MCP stdio JSON-RPC, Vitest 4, Rust `chatkimv2` as an external local dependency.

---

## Execution rules

- Use @test-driven-development for every production change.
- Use @writing-skills for the Skill RED/GREEN cycle.
- Use @systematic-debugging for unexpected failures.
- Use @verification-before-completion before completion claims.
- Preserve the untracked `dsh-plugin/tests/kim-source-owned-catalog.spec.ts` unless
  a separately approved reframe explicitly incorporates it.
- Never commit or print real Kim messages, identities, paths, keys, source URLs,
  binary hashes, or database artifacts.
- Do not enable the production `SourceConnector`, scheduler, persistence, or
  legacy cutover in this plan.

### Task 1: Record the approved local-adapter reframe

**Files:**
- Create: `docs/plans/2026-08-18-kim-chat-skill-design.md`
- Create: `docs/plans/2026-08-18-kim-chat-skill-implementation.md`
- Modify: `docs/dossiers/2026-08-17-dsh-personal-context.md`
- Modify: `docs/verification/chat-source-gate.md`

**Step 1:** Add a documentation contract test that expects the dossier and gate
to describe the user-authorized local adapter as a Kim-only evidence path while
keeping overall G2 blocked.

**Step 2:** Run the focused contract and verify RED on the missing reframe text.

**Step 3:** Add the minimum dossier and gate amendments. Do not copy the internal
repository URL or source metadata into committed documents.

**Step 4:** Re-run the focused contract and verify GREEN.

**Step 5:** Commit only the design, plan, dossier, gate, and contract test.

### Task 2: Implement executable provenance validation

**Files:**
- Create: `dsh-plugin/src/chatkim/config.ts`
- Create: `dsh-plugin/tests/chatkim-config.spec.ts`

**Step 1:** Write tests for missing configuration, relative paths, symlinks,
non-files, writable mode, uppercase/malformed hashes, mismatch, valid executable,
and abort during hashing.

**Step 2:** Run:

```bash
pnpm --dir dsh-plugin exec vitest run tests/chatkim-config.spec.ts
```

Expected: RED because `src/chatkim/config.ts` does not exist.

**Step 3:** Implement the minimum async validator using `lstat`, owner/mode checks,
streaming SHA-256, and fixed plugin-owned errors. Accept injected filesystem and
hash readers only at the module boundary so tests never need a real reader.

**Step 4:** Re-run the focused test and verify GREEN.

**Step 5:** Commit the config module and its test.

### Task 3: Implement the bounded MCP stdio client

**Files:**
- Create: `dsh-plugin/src/chatkim/client.ts`
- Create: `dsh-plugin/tests/fixtures/chatkim/fake-reader.mjs`
- Create: `dsh-plugin/tests/chatkim-client.spec.ts`

**Step 1:** Write integration tests against the fake child for initialize,
one valid `tools/call`, serialization, response correlation, malformed JSON,
wrong IDs, unexpected envelope, stderr noise, response overflow, timeout, abort,
child exit, and idempotent disposal.

**Step 2:** Run the focused test and verify RED on the missing client.

**Step 3:** Implement one serialized client with `spawn(binary, ['mcp'])`,
`shell:false`, a minimal environment, newline framing, byte caps, hard timeouts,
AbortSignal handling, and lifecycle cleanup. Never include child output in errors.

**Step 4:** Re-run the focused test and verify GREEN with no leaked fixture body.

**Step 5:** Commit the client, fake reader, and test.

### Task 4: Add strict response projections and restricted DSH tools

**Files:**
- Create: `dsh-plugin/src/chatkim/project.ts`
- Create: `dsh-plugin/src/chatkim/tools.ts`
- Create: `dsh-plugin/tests/chatkim-tools.spec.ts`
- Modify: `dsh-plugin/src/index.ts`

**Step 1:** Write tests for exact empty status arguments, conversation filters,
message bounds, context bounds, unknown properties, missing source fields,
self/other/system direction, strict output projection, fixed child errors, and
absence of raw paths/metadata.

**Step 2:** Run the focused test and verify RED.

**Step 3:** Implement the four tools and project only approved fields. Cache only
the current user ID in memory for the child lifetime; never persist or log it.

**Step 4:** Register the tools and own client disposal through the Cordis effect.

**Step 5:** Re-run focused tests, the existing bundle test, and pinned typecheck;
verify GREEN.

**Step 6:** Commit only the tool modules, host wiring, and tests.

### Task 5: Create and register the bundled Skill

**Files:**
- Create: `dsh-plugin/skills/kim-chat-history/SKILL.md`
- Create: `dsh-plugin/src/chatkim/skill.ts`
- Create: `dsh-plugin/tests/kim-chat-skill.spec.ts`
- Modify: `dsh-plugin/package.json`
- Modify: `dsh-plugin/src/index.ts`
- Modify: `dsh-plugin/scripts/smoke-install.mjs`

**Step 1:** Run a baseline Skill-use scenario without the Skill and record the
failure: the synthetic agent must either miss the status-first workflow, use an
unbounded query, or attempt a generic shell path.

**Step 2:** Add unit/package tests expecting `kim-chat-history`, exact frontmatter,
bounded instructions, runtime registration/disposal, tarball inclusion, and no
binary/source/credential content. Verify RED.

**Step 3:** Initialize the Skill using the skill-creator initializer, then replace
the template with the minimum instructions addressing the observed baseline
failure. Do not add README or installation instructions.

**Step 4:** Parse and register the packaged `SKILL.md` through `ctx.skills` from
the Host plugin. Add `skills` to the Host injection contract.

**Step 5:** Run Skill tests and the same use scenario with the Skill; verify
GREEN and bounded tool selection.

**Step 6:** Update the isolated installed-package smoke to prove the Skill is
present and loadable without touching real `~/.dsh`.

**Step 7:** Commit the Skill, runtime registration, manifest changes, smoke
changes, and tests.

### Task 6: Perform redacted live Kim validation

**Files:**
- Create: `dsh-plugin/scripts/chatkim-live-proof.mjs`
- Modify: `docs/verification/kim-source-feasibility.md`
- Modify: `docs/verification/chat-source-gate.md`
- Modify: `docs/dossiers/2026-08-17-dsh-personal-context.md`

**Step 1:** Build the reviewed reader from a clean, fixed local source checkout
outside the repository. Do not run repository install scripts or ship the binary.

**Step 2:** Configure its absolute path and SHA-256 only in the current process.

**Step 3:** Run a redacted proof that calls status and bounded synthetic-free live
operations but emits only seven capability booleans, adapter version class, and
fixed failure codes. Raw stdout/stderr must never reach the terminal or files
outside a private temporary directory removed in `finally`.

**Step 4:** If any required field is absent or unstable, keep the Skill disabled
and record BLOCK. If the on-demand Skill contract passes, record that result
separately from the still-unproven durable incremental connector.

**Step 5:** Commit only the redacted proof script and redacted documents.

### Task 7: Run final gates and review

**Files:**
- Modify as required only for findings introduced by Tasks 1-6.

**Step 1:** Run all focused chatkim, connector, bundle, and Skill tests.

**Step 2:** Run `pnpm --dir dsh-plugin test`, `pnpm --dir dsh-plugin build`,
`pnpm --dir dsh-plugin run test:g1`, tarball inspection, and `git diff --check`.

**Step 3:** Run the legacy Python suite without piping through `tail`.

**Step 4:** Review executable provenance, child lifecycle, stdout/stderr leakage,
tool schemas, Skill scope, package contents, temporary cleanup, and unchanged
production connector flags.

**Step 5:** Fix findings through new RED/GREEN cycles, then commit only owned
files. Do not stage the pre-existing untracked catalog test unless Task 1
explicitly adopted it.

**Step 6:** Report separately: on-demand Kim Skill status, Kim background-sync
G2 status, WeChat G2 status, deployment status, and whether legacy capture
changed.
