# DSH compatibility

This scaffold targets DeepSeek Harness `0.1.0-rc.5` at source commit `47f943859bef60e4160492346772ded9b24f765a`.

## Verified extension points

- The Host half follows `docs/cookbook/adding-a-tool.md` and registers the read-only `personal_context_health` definition through `ctx.tools.register(...)` with the `tools` service injected. RC5's runtime validator accepted the definition, including its object-level `required` output schema, when the pinned Web profile booted.
- The browser half contributes to the additive `conversation.view` list slot defined in `packages/client/ui-conversation/src/client/contract/slots.ts`. The pinned source describes this slot as one whole tab rendered one at a time and explicitly recommends it for adding a view without replacing `conversation.session`.
- Registration uses `ctx.slots.inject('conversation.view', ...)`, as required by `packages/client/AGENTS.md`, so it waits for the owner declaration and follows its lifecycle.
- `lib/client.js` uses the `window.__ModuleLoader__.load({ id, factory })` handoff implemented by `packages/client/tsdown.client.ts` and consumed by `packages/client/modules/src/index.ts`.
- The first out-of-tree view uses direct Chinese copy (`个人上下文`) rather than taking a dependency on the RC5 locale service. This keeps the scaffold's dependency surface minimal; a complete locale namespace belongs with the later functional GUI, not this compatibility probe.

## Reproducible G1 command

After `pnpm install`, run `pnpm run test:g1`. It deliberately continues past transpilation:

1. `pnpm test` builds the Host/client bundles and runs the manifest, lifecycle, isolation/cleanup, schema, and Host behavior tests.
2. `scripts/g1-pinned.mjs` first enforces this package's Node engine (`^22.19.0 || >=24.0.0`), so unsupported Node 23 and pre-22.19 runtimes fail before cloning or installation. It then rejects a canonical source checkout whose commit, root version, or tracked-file status differs from the pin and creates a disposable detached shared clone at that exact commit. The required ignored declarations and CLI output must be absent before `pnpm install --frozen-lockfile` and `pnpm run build:lib`, and present afterward. The canonical checkout is never installed, built, or modified.
3. The same freshly built clone supplies the real RC5 Host/client declarations to temporary TypeScript projects, dispatches the health tool through the real RC5 `Context` and `ToolRuntime`, and supplies the real RC5 CLI to an isolated install smoke. The smoke uses a unique temporary `DSH_HOME`, checks the composed Host/browser package row and both installed `lib/index.js` and `lib/client.js`, and all temporary clone, typecheck, and profile roots are removed in `finally`.

`pnpm run typecheck:pinned` and `pnpm run smoke:pinned` are also available as standalone proofs; each creates and removes its own fresh pinned build. Source discovery accepts `--dsh-source`, `DSH_SOURCE`, or the documented local default. No absolute path is committed.

## Local pinned verification

The clean pinned checkout was exercised with Node `24.19.0` on an isolated temporary `DSH_HOME`:

- `plugin --profile web add` and `--dump-config` exposed the single `personal-context` bundle row. `packages/client/modules/src/index.ts` projects that row into its browser module because the package manifest declares `dsh.client`; a second patch row is neither required nor supported by this bundle format. The smoke verifies both artifacts through the installed package path, not the source tree.
- The Web boot manifest included `@ominime/dsh-personal-context` and its three declared client injections, and the plugin client asset was served successfully.
- The initial temporary workspace/session displayed the normal `对话` and `轨迹` tabs alongside the scaffold tab, proving the contribution is additive and visible against the pinned GUI. The automated lifecycle test is narrower: a unit harness invokes the real plugin callback/disposer, simulates owner declaration collapse and redeclaration, and verifies the Chinese `个人上下文` tab/heading/placeholder. It is not a second real-browser `Context`/`SlotRegistry` integration proof.
- The Host module loaded in the same Web process, while the unit integration invokes the registered raw health definition and verifies the exact `{ status: 'scaffold', schemaVersion: 0, sources: [] }` result. The definition declares an empty-object schema and also performs strict runtime validation, rejecting extra properties, arrays, strings, and `null` with the plugin-owned `InvalidHealthArgsError`. Its name, `INVALID_HEALTH_ARGS` code, and violations are internal plugin diagnostics, not an RC5 structured-error promise.

The unit behavior test calls the captured raw definition's `execute` function. The pinned G1 additionally registers that definition with the freshly built RC5 `ToolRuntime` and executes `{}`, an extra-key object, an array, a string, and `null` through `ctx.tools.execute`. It asserts successful scaffold output for `{}` and stable generic raw-tool error messages for invalid calls. It explicitly asserts that `error.info` is absent: the plugin does not claim RC5 `ToolArgsError`/`INVALID_ARGS` identity. RC5 does not validate a raw definition's `parameters` schema itself, and a linked out-of-tree package cannot safely runtime-import the unavailable optional peer, so the bundle owns its strict guard without bundling or hard-linking an RC5 runtime package.

Therefore G1 is **PASS for the local pinned RC5 runtime**: fresh source-derived build, type compatibility, install, Host tool registration/behavior, client wiring, and GUI rendering have all been observed. All profiles and sessions used for this proof lived under temporary paths and were removed after the process stopped.

## Source feasibility gate

G2 is currently **BLOCKED** for both chat sources:

- WeChat reports only `WECHAT_ATOMIC_OPEN_UNAVAILABLE`.
- Kim reports only `KIM_ATOMIC_OPEN_UNAVAILABLE`.

For both sources, every required live capability remains unproven and every
field mapping remains unavailable. This does not establish that the underlying
applications lack suitable business data. It establishes that the current
adapters cannot safely evaluate or use the live stores without an atomic
directory-descriptor/`openat` path helper or a source-owned read-only structured
interface.

Both production connectors remain disabled. Storage, migration, and other
downstream source implementation must not proceed while G2 is blocked. The
existing legacy keyboard/OCR capture remains active and unchanged.

An atomic helper or source-owned interface is only the next prerequisite. Each
source must then pass a new live redacted probe with authoritative, stable
evidence for all required capabilities before its G2 decision can change to
`PASS`. See [`chat-source-gate.md`](../docs/verification/chat-source-gate.md)
for the capability-level decision and reproduction commands.

## Distribution constraint

As verified on 2026-08-17, npm publishes DSH `0.1.0-rc.2`, `0.1.0-rc.3`, and `0.1.0-rc.6`, but not `0.1.0-rc.5`. The original scaffold plan requested exact RC5 peer and development dependencies. The manifest records all directly named RC5 runtime packages as exact optional peers, but deliberately does not repeat unavailable RC5 packages as registry-resolved development dependencies or commit a machine-specific `file:`/`link:` path. Build-time DSH imports remain type-only and runtime dependencies remain external.

Portable npm distribution is therefore **BLOCKED** until RC5 is published or the compatibility baseline is deliberately moved. The PASS above is intentionally limited to the clean local checkout at the exact pinned commit; it is not a claim that a third party can reproduce the install from the public registry alone.

This portable distribution block is independent of G2. A local pinned G1
`PASS` does not prove source feasibility, and resolving npm distribution would
not resolve the WeChat or Kim source blocks.
