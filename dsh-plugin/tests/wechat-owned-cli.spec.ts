import { execFile, spawnSync } from 'node:child_process'
import { EventEmitter } from 'node:events'
import { mkdtempSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { Writable } from 'node:stream'
import { describe, expect, it, vi } from 'vitest'
import { requiredCapabilityKeys } from '../scripts/source-owned/evidence.mjs'
import {
  WECHAT_OWNED_PROBE_TIMEOUT_MS,
  runWechatOwnedProbeCli,
} from '../scripts/source-owned/probe-wechat-owned.mjs'

const validPrefix = [
  '--redact',
  '--isolated-test-user-confirmed',
  '--test-account-confirmed',
]

const standardSummary = Object.freeze({
  protocolClass: 'http',
  bannerClass: null,
  alpnClass: null,
  statusClass: '4xx',
  allowHeaderPresent: true,
  linkHeaderPresent: false,
  wwwAuthenticateHeaderPresent: true,
})

function frozenListeners(...listeners: Array<{ host: string; port: number }>) {
  return Object.freeze(listeners.map(listener => Object.freeze({ ...listener })))
}

function capture() {
  let stdout = ''
  let stderr = ''
  return {
    stdout: Object.freeze({
      write: vi.fn((value: string, callback?: (error?: Error | null) => void) => {
        stdout += value
        callback?.()
        return true
      }),
    }),
    stderr: Object.freeze({
      write: vi.fn((value: string) => {
        stderr += value
        return true
      }),
    }),
    read() {
      return { stdout, stderr }
    },
  }
}

async function invoke({
  argv,
  listeners = frozenListeners(),
  collectListeners = vi.fn(async () => listeners),
  classify = vi.fn(async () => standardSummary),
  stdout,
}: {
  argv: string[]
  listeners?: ReadonlyArray<Readonly<{ host: string; port: number }>>
  collectListeners?: ReturnType<typeof vi.fn>
  classify?: ReturnType<typeof vi.fn>
  stdout?: { write: (...arguments_: never[]) => unknown }
}) {
  const output = capture()
  const exitCode = await runWechatOwnedProbeCli({
    argv,
    collectListeners,
    classify,
    stdout: stdout ?? output.stdout,
  })
  const written = output.read()
  const report = written.stdout === '' ? undefined : JSON.parse(written.stdout)
  return { exitCode, report, ...written, collectListeners, classify, output }
}

function runStandaloneNode(source: string, timeout = WECHAT_OWNED_PROBE_TIMEOUT_MS + 3_000) {
  const startedAt = Date.now()
  return new Promise<{
    error: (Error & { code?: number | string }) | null
    stdout: string
    stderr: string
    elapsedMs: number
  }>((done) => {
    execFile(
      process.execPath,
      ['--input-type=module', '--eval', source],
      { encoding: 'utf8', timeout, maxBuffer: 4_096 },
      (error, stdout, stderr) => done({
        error,
        stdout,
        stderr,
        elapsedMs: Date.now() - startedAt,
      }),
    )
  })
}

function expectStrictUnprovenReport(report: Record<string, unknown>) {
  expect(Object.keys(report)).toEqual([
    'source',
    'interfaceClass',
    'status',
    'protocolClass',
    'authorizationClass',
    'versionClass',
    'capabilities',
    'fieldMappings',
    'failureCodes',
  ])
  expect(report).toMatchObject({
    source: 'wechat',
    interfaceClass: 'app_loopback',
    authorizationClass: null,
    versionClass: null,
    capabilities: Object.fromEntries(requiredCapabilityKeys.map(key => [key, false])),
    fieldMappings: {},
  })
  expect(Object.keys(report.capabilities as object)).toEqual(requiredCapabilityKeys)
  expect(Object.values(report.capabilities as object)).toEqual(Array(7).fill(false))
  expect(Object.keys(report.fieldMappings as object)).toEqual([])
}

describe('isolated WeChat source-owned probe CLI', () => {
  it.each([
    ['missing redaction', ['--isolated-test-user-confirmed', '--test-account-confirmed', '--inventory-only']],
    ['missing isolated user confirmation', ['--redact', '--test-account-confirmed', '--inventory-only']],
    ['missing test account confirmation', ['--redact', '--isolated-test-user-confirmed', '--inventory-only']],
    ['missing mode', validPrefix],
    ['both modes', [...validPrefix, '--inventory-only', '--classify']],
    ['unknown flag', [...validPrefix, '--inventory-only', '--verbose']],
    ['valued flag', [...validPrefix, '--inventory-only', '--redact=true']],
    ['separate value', [...validPrefix, '--inventory-only', '--port', '4567']],
    ['positional argument', [...validPrefix, '--inventory-only', '/private/path']],
    ['duplicate confirmation', [...validPrefix, '--redact', '--inventory-only']],
    ['duplicate mode', [...validPrefix, '--inventory-only', '--inventory-only']],
    ['arbitrary host', [...validPrefix, '--inventory-only', '--host=127.0.0.1']],
    ['arbitrary executable', [...validPrefix, '--inventory-only', '--executable=/private/tool']],
    ['arbitrary request', [...validPrefix, '--inventory-only', '--request=GET']],
    ['arbitrary header', [...validPrefix, '--inventory-only', '--header=private']],
    ['arbitrary payload', [...validPrefix, '--inventory-only', '--payload=private']],
  ])('refuses %s before inventory with one fixed report', async (_name, argv) => {
    const privateValue = argv.at(-1) ?? 'private'
    const collectListeners = vi.fn(async () => {
      throw new Error('inventory must not run')
    })
    const classify = vi.fn(async () => {
      throw new Error('classifier must not run')
    })

    const result = await invoke({ argv, collectListeners, classify })

    expect(result.exitCode).toBe(2)
    expect(result.collectListeners).not.toHaveBeenCalled()
    expect(result.classify).not.toHaveBeenCalled()
    expect(result.stderr).toBe('')
    expect(result.stdout.endsWith('\n')).toBe(true)
    expect(result.stdout.trim().split('\n')).toHaveLength(1)
    expect(result.stdout).not.toContain(privateValue)
    expect(result.report.failureCodes).toEqual(['WECHAT_OWNED_PROBE_ARGUMENTS_INVALID'])
    expectStrictUnprovenReport(result.report)
  })

  it.each([
    [frozenListeners(), 'WECHAT_OWNED_LISTENER_NOT_FOUND'],
    [frozenListeners({ host: '127.0.0.1', port: 4567 }), 'WECHAT_INTERFACE_CONTRACT_NOT_PROVEN'],
  ])('inventory-only never opens a socket and remains NOT PROVEN', async (listeners, code) => {
    const result = await invoke({
      argv: [...validPrefix, '--inventory-only'],
      listeners,
    })

    expect(result.exitCode).toBe(2)
    expect(result.collectListeners).toHaveBeenCalledTimes(1)
    expect(result.classify).not.toHaveBeenCalled()
    expect(result.report).toMatchObject({ status: 'block', protocolClass: null })
    expect(result.report.failureCodes).toEqual([code])
    expectStrictUnprovenReport(result.report)
    expect(result.stdout).not.toContain('4567')
  })

  it('classifies every frozen candidate sequentially exactly once without retrying', async () => {
    const listeners = frozenListeners(
      { host: '127.0.0.1', port: 4567 },
      { host: '::1', port: 4568 },
    )
    const order: string[] = []
    const classify = vi.fn(async (candidate) => {
      order.push(`${candidate.host}:${candidate.port}`)
      throw new Error(`private failure ${candidate.port}`)
    })

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners,
      classify,
    })

    expect(result.exitCode).toBe(2)
    expect(result.classify).toHaveBeenCalledTimes(2)
    const classified = result.classify.mock.calls.map(([candidate]) => candidate)
    expect(classified.map(({ host, port }) => ({ host, port }))).toEqual(listeners)
    expect(classified.every(candidate => Object.isFrozen(candidate))).toBe(true)
    expect(classified.every(candidate => candidate.signal instanceof AbortSignal)).toBe(true)
    expect(new Set(classified.map(candidate => candidate.signal)).size).toBe(1)
    expect(order).toEqual(['127.0.0.1:4567', '::1:4568'])
    expect(result.report).toMatchObject({ status: 'block', protocolClass: null })
    expect(result.report.failureCodes).toEqual(['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN'])
    expect(result.stdout).not.toMatch(/4567|4568|private failure/)
    expectStrictUnprovenReport(result.report)
  })

  it.each(['banner', 'http', 'tls'] as const)(
    'returns exit 0 only for one self-describing %s candidate without proving chat capabilities',
    async (protocolClass) => {
      const classify = vi.fn(async () => Object.freeze({
        ...standardSummary,
        protocolClass,
        bannerClass: protocolClass === 'banner' ? 'ssh' : null,
        alpnClass: protocolClass === 'tls' ? 'http1' : null,
        statusClass: protocolClass === 'banner' ? null : standardSummary.statusClass,
        allowHeaderPresent: protocolClass === 'banner' ? false : standardSummary.allowHeaderPresent,
        wwwAuthenticateHeaderPresent: protocolClass === 'banner'
          ? false
          : standardSummary.wwwAuthenticateHeaderPresent,
      }))

      const result = await invoke({
        argv: [...validPrefix, '--classify'],
        listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
        classify,
      })

      expect(result.exitCode).toBe(0)
      expect(result.classify).toHaveBeenCalledTimes(1)
      expect(result.report).toMatchObject({ status: 'candidate', protocolClass })
      expect(result.report.failureCodes).toContain('WECHAT_INTERFACE_CONTRACT_NOT_PROVEN')
      expect(result.stdout).not.toContain('4567')
      expectStrictUnprovenReport(result.report)
    },
  )

  it('blocks a partial classification when one listener succeeds and another rejects', async () => {
    const privateValue = 'private-second-listener-error'
    const classify = vi.fn()
      .mockResolvedValueOnce(standardSummary)
      .mockRejectedValueOnce(new Error(privateValue))

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners(
        { host: '127.0.0.1', port: 4567 },
        { host: '::1', port: 4568 },
      ),
      classify,
    })

    expect(result.exitCode).toBe(2)
    expect(result.classify).toHaveBeenCalledTimes(2)
    expect(result.report).toMatchObject({ status: 'block', protocolClass: null })
    expect(result.report.failureCodes).toEqual(['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN'])
    expect(result.stdout).not.toContain(privateValue)
    expectStrictUnprovenReport(result.report)
  })

  it.each([
    ['banner with ALPN', { protocolClass: 'banner', bannerClass: 'ssh', alpnClass: 'http1' }],
    ['banner with status', { protocolClass: 'banner', bannerClass: 'ssh', statusClass: '2xx' }],
    ['banner with a header flag', { protocolClass: 'banner', bannerClass: 'ssh', allowHeaderPresent: true }],
    ['HTTP with banner', { protocolClass: 'http', bannerClass: 'ssh' }],
    ['HTTP with ALPN', { protocolClass: 'http', alpnClass: 'http1' }],
    ['HTTP without status', { protocolClass: 'http', statusClass: null }],
    ['TLS with banner', { protocolClass: 'tls', bannerClass: 'ssh', alpnClass: null, statusClass: null }],
    ['bare TLS with status', { protocolClass: 'tls', alpnClass: null, statusClass: '2xx' }],
    ['bare TLS with headers', { protocolClass: 'tls', alpnClass: null, statusClass: null, linkHeaderPresent: true }],
    ['HTTP-over-TLS without status but headers', {
      protocolClass: 'tls',
      alpnClass: 'http1',
      statusClass: null,
      wwwAuthenticateHeaderPresent: true,
    }],
  ])('blocks impossible frozen protocol summary: %s', async (_name, overrides) => {
    const impossible = Object.freeze({
      ...standardSummary,
      ...overrides,
      ...(overrides.protocolClass === 'banner'
        ? {
            statusClass: overrides.statusClass ?? null,
            allowHeaderPresent: overrides.allowHeaderPresent ?? false,
            linkHeaderPresent: overrides.linkHeaderPresent ?? false,
            wwwAuthenticateHeaderPresent: overrides.wwwAuthenticateHeaderPresent ?? false,
          }
        : {}),
      ...(overrides.protocolClass === 'tls' && overrides.statusClass === null
        ? {
            allowHeaderPresent: overrides.allowHeaderPresent ?? false,
            linkHeaderPresent: overrides.linkHeaderPresent ?? false,
            wwwAuthenticateHeaderPresent: overrides.wwwAuthenticateHeaderPresent ?? false,
          }
        : {}),
    })
    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      classify: vi.fn(async () => impossible),
    })

    expect(result.exitCode).toBe(2)
    expect(result.report.failureCodes).toEqual(['WECHAT_STANDARD_PROTOCOL_INCONSISTENT'])
    expectStrictUnprovenReport(result.report)
  })

  it('blocks ambiguous standard candidates after classifying each candidate once', async () => {
    const classify = vi.fn()
      .mockResolvedValueOnce(Object.freeze({ ...standardSummary, protocolClass: 'http' }))
      .mockResolvedValueOnce(Object.freeze({
        ...standardSummary,
        protocolClass: 'tls',
        alpnClass: 'http1',
      }))

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners(
        { host: '127.0.0.1', port: 4567 },
        { host: '::1', port: 4568 },
      ),
      classify,
    })

    expect(result.exitCode).toBe(2)
    expect(result.classify).toHaveBeenCalledTimes(2)
    expect(result.report).toMatchObject({ status: 'block', protocolClass: null })
    expect(result.report.failureCodes).toEqual(['WECHAT_STANDARD_PROTOCOL_AMBIGUOUS'])
    expectStrictUnprovenReport(result.report)
  })

  it('blocks malformed classifier summaries without reflecting injected data', async () => {
    const privateValue = 'private-header-value-and-path-/Users/private'
    const classify = vi.fn(async () => ({
      ...standardSummary,
      rawHeader: privateValue,
    }))

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      classify,
    })

    expect(result.exitCode).toBe(2)
    expect(result.report.failureCodes).toEqual(['WECHAT_STANDARD_PROTOCOL_INCONSISTENT'])
    expect(result.stdout).not.toContain(privateValue)
    expectStrictUnprovenReport(result.report)
  })

  it('normalizes inventory and dependency failures without raw output, errors, or logs', async () => {
    const privateValues = [
      'private pid 98765',
      '/private/account/container',
      'private-command-output',
      'private-response-bytes',
      'private-certificate-data',
      'private-hash-or-identifier',
    ]
    const spies = [
      vi.spyOn(console, 'log').mockImplementation(() => undefined),
      vi.spyOn(console, 'error').mockImplementation(() => undefined),
      vi.spyOn(console, 'warn').mockImplementation(() => undefined),
      vi.spyOn(console, 'debug').mockImplementation(() => undefined),
    ]

    try {
      for (const privateValue of privateValues) {
        const collectListeners = vi.fn(async () => {
          throw Object.assign(new Error(privateValue), { code: privateValue })
        })
        const result = await invoke({
          argv: [...validPrefix, '--inventory-only'],
          collectListeners,
        })

        expect(result.exitCode).toBe(2)
        expect(result.stderr).toBe('')
        expect(result.stdout).not.toContain(privateValue)
        expect(result.report.failureCodes).toEqual(['WECHAT_OWNED_LISTENER_INVENTORY_FAILED'])
        expectStrictUnprovenReport(result.report)
      }
      for (const spy of spies) expect(spy).not.toHaveBeenCalled()
    } finally {
      for (const spy of spies) spy.mockRestore()
    }
  })

  it('fails closed when injected runner options or inventory reflection throws', async () => {
    const privateValue = 'private-reflection-error-and-token'
    const throwingOptions = new Proxy({}, {
      get() {
        throw new Error(privateValue)
      },
      ownKeys() {
        throw new Error(privateValue)
      },
    })
    await expect(runWechatOwnedProbeCli(throwingOptions)).resolves.toBe(2)

    const listeners = new Proxy([], {
      preventExtensions() {
        throw new Error(privateValue)
      },
      ownKeys() {
        throw new Error(privateValue)
      },
    })
    const result = await invoke({
      argv: [...validPrefix, '--inventory-only'],
      collectListeners: vi.fn(async () => listeners),
    })
    expect(result.exitCode).toBe(2)
    expect(result.report.failureCodes).toEqual(['WECHAT_OWNED_LISTENER_INVENTORY_FAILED'])
    expect(result.stdout).not.toContain(privateValue)
  })

  it('returns exit 2 without retry when candidate report emission throws synchronously', async () => {
    const privateValue = 'private-sync-write-error'
    const stdout = {
      write: vi.fn(() => {
        throw new Error(privateValue)
      }),
    }

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      stdout: stdout as never,
    })

    expect(result.exitCode).toBe(2)
    expect(stdout.write).toHaveBeenCalledTimes(1)
    expect(JSON.stringify(result)).not.toContain(privateValue)
  })

  it('observes an asynchronous write callback error and emits no second report', async () => {
    const privateValue = 'private-async-write-error'
    const written: string[] = []
    const stdout = {
      write: vi.fn((line: string, callback: (error?: Error | null) => void) => {
        written.push(line)
        setTimeout(() => callback(new Error(privateValue)), 5)
        return true
      }),
    }
    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      stdout: stdout as never,
    })

    expect(result.exitCode).toBe(2)
    expect(stdout.write).toHaveBeenCalledTimes(1)
    expect(written).toHaveLength(1)
    expect(written[0]).not.toContain(privateValue)
  })

  it('treats write false as backpressure when its callback succeeds', async () => {
    const written: string[] = []
    const stdout = {
      write: vi.fn((line: string, callback: (error?: Error | null) => void) => {
        written.push(line)
        setImmediate(() => callback())
        return false
      }),
    }

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      stdout: stdout as never,
    })

    expect(result.exitCode).toBe(0)
    expect(stdout.write).toHaveBeenCalledTimes(1)
    expect(written).toHaveLength(1)
    expect(JSON.parse(written[0])).toMatchObject({ status: 'candidate', protocolClass: 'http' })
  })

  it.each([
    ['error then success', [new Error('private-first-error'), undefined]],
    ['success then error', [undefined, new Error('private-second-error')]],
  ])('fails closed when a reporter invokes its callback twice: %s', async (_name, results) => {
    const written: string[] = []
    const stdout = {
      write: vi.fn((line: string, callback: (error?: Error | null) => void) => {
        written.push(line)
        for (const result of results) callback(result)
        return true
      }),
    }

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      stdout: stdout as never,
    })

    expect(result.exitCode).toBe(2)
    expect(stdout.write).toHaveBeenCalledTimes(1)
    expect(written).toHaveLength(1)
    expect(JSON.stringify(result)).not.toMatch(/private-first-error|private-second-error/)
  })

  it('fails when a successful callback is accompanied by an error event', async () => {
    const privateValue = 'private-callback-plus-error-event'
    class CallbackAndErrorSink extends EventEmitter {
      writes = 0

      write(_line: string, callback: (error?: Error | null) => void) {
        this.writes += 1
        callback()
        this.emit('error', new Error(privateValue))
        return true
      }
    }
    const stdout = new CallbackAndErrorSink()

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      stdout: stdout as never,
    })

    expect(result.exitCode).toBe(2)
    expect(stdout.writes).toBe(1)
    expect(stdout.listenerCount('error')).toBe(0)
    expect(JSON.stringify(result)).not.toContain(privateValue)
  })

  it('handles a real Writable error without a raw unhandled event or listener leak', async () => {
    const moduleUrl = new URL('../scripts/source-owned/probe-wechat-owned.mjs', import.meta.url).href
    const privateValue = 'private-real-writable-error'
    const source = `
      import { Writable } from 'node:stream'
      import { runWechatOwnedProbeCli } from ${JSON.stringify(moduleUrl)}
      let writes = 0
      const sink = new Writable({
        write(_chunk, _encoding, callback) {
          writes += 1
          callback(new Error(${JSON.stringify(privateValue)}))
        },
      })
      const exitCode = await runWechatOwnedProbeCli({
        argv: [
          '--redact',
          '--isolated-test-user-confirmed',
          '--test-account-confirmed',
          '--classify',
        ],
        collectListeners: async () => Object.freeze([
          Object.freeze({ host: '127.0.0.1', port: 4567 }),
        ]),
        classify: async () => Object.freeze({
          protocolClass: 'http',
          bannerClass: null,
          alpnClass: null,
          statusClass: '4xx',
          allowHeaderPresent: true,
          linkHeaderPresent: false,
          wwwAuthenticateHeaderPresent: true,
        }),
        stdout: sink,
      })
      process.stdout.write(JSON.stringify({
        exitCode,
        writes,
        errorListeners: sink.listenerCount('error'),
      }))
      process.exitCode = exitCode
    `
    const result = await runStandaloneNode(source)

    expect(result.error?.code).toBe(2)
    expect(result.stderr).toBe('')
    expect(JSON.parse(result.stdout)).toEqual({ exitCode: 2, writes: 1, errorListeners: 0 })
    expect(`${result.stdout}\n${result.stderr}`).not.toContain(privateValue)
  })

  it('keeps the redacting guard until a late real Writable error settles after deadline', async () => {
    const moduleUrl = new URL('../scripts/source-owned/probe-wechat-owned.mjs', import.meta.url).href
    const privateValue = 'private-late-real-writable-error'
    const source = `
      import { Writable } from 'node:stream'
      import {
        WECHAT_OWNED_PROBE_TIMEOUT_MS,
        runWechatOwnedProbeCli,
      } from ${JSON.stringify(moduleUrl)}
      let writes = 0
      const sink = new Writable({
        write(_chunk, _encoding, callback) {
          writes += 1
          setTimeout(
            () => callback(new Error(${JSON.stringify(privateValue)})),
            WECHAT_OWNED_PROBE_TIMEOUT_MS + 200,
          )
        },
      })
      const startedAt = Date.now()
      const exitCode = await runWechatOwnedProbeCli({
        argv: ['--redact'],
        stdout: sink,
      })
      const returnedAfterMs = Date.now() - startedAt
      const listenersAtReturn = sink.listenerCount('error')
      await new Promise(resolve => setTimeout(resolve, 400))
      process.stdout.write(JSON.stringify({
        exitCode,
        writes,
        returnedAfterMs,
        listenersAtReturn,
        terminalListeners: sink.listenerCount('error'),
      }))
      process.exitCode = exitCode
    `
    const result = await runStandaloneNode(source)

    expect(result.error?.code).toBe(2)
    expect(result.stderr).toBe('')
    const evidence = JSON.parse(result.stdout)
    expect(evidence).toMatchObject({
      exitCode: 2,
      writes: 1,
      listenersAtReturn: 1,
      terminalListeners: 0,
    })
    expect(evidence.returnedAfterMs).toBeGreaterThanOrEqual(WECHAT_OWNED_PROBE_TIMEOUT_MS - 250)
    expect(evidence.returnedAfterMs).toBeLessThan(WECHAT_OWNED_PROBE_TIMEOUT_MS + 200)
    expect(`${result.stdout}\n${result.stderr}`).not.toContain(privateValue)
  }, WECHAT_OWNED_PROBE_TIMEOUT_MS + 4_000)

  it('removes its temporary Writable error listener after successful emission', async () => {
    const stdout = new Writable({
      write(_chunk, _encoding, callback) {
        callback()
      },
    })

    const result = await invoke({
      argv: [...validPrefix, '--classify'],
      listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
      stdout: stdout as never,
    })

    expect(result.exitCode).toBe(0)
    expect(stdout.listenerCount('error')).toBe(0)
  })

  it('bounds invalid-argument emission and never inventories when its sink hangs', async () => {
    vi.useFakeTimers()
    class HangingSink extends EventEmitter {
      writes = 0

      write(_line: string, _callback: (error?: Error | null) => void) {
        this.writes += 1
        return true
      }
    }
    const stdout = new HangingSink()
    const collectListeners = vi.fn(async () => frozenListeners())
    const classify = vi.fn(async () => standardSummary)
    let outcome: Awaited<ReturnType<typeof invoke>> | 'pending' = 'pending'
    try {
      void invoke({
        argv: ['--redact'],
        collectListeners,
        classify,
        stdout: stdout as never,
      }).then((result) => { outcome = result })
      await vi.advanceTimersByTimeAsync(WECHAT_OWNED_PROBE_TIMEOUT_MS)
      await Promise.resolve()

      expect(outcome).not.toBe('pending')
      if (outcome === 'pending') return
      expect(outcome.exitCode).toBe(2)
      expect(stdout.writes).toBe(1)
      expect(stdout.listenerCount('error')).toBe(1)
      expect(collectListeners).not.toHaveBeenCalled()
      expect(classify).not.toHaveBeenCalled()
      stdout.emit('error', new Error('private-terminal-error'))
      await vi.runOnlyPendingTimersAsync()
      expect(stdout.listenerCount('error')).toBe(0)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('retains a handle-free guard when report emission never terminally settles', async () => {
    vi.useFakeTimers()
    class HangingSink extends EventEmitter {
      write(_line: string, _callback: (error?: Error | null) => void) {
        return true
      }
    }
    const stdout = new HangingSink()
    try {
      const action = invoke({
        argv: [...validPrefix, '--classify'],
        listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
        stdout: stdout as never,
      })
      await vi.advanceTimersByTimeAsync(WECHAT_OWNED_PROBE_TIMEOUT_MS)
      const result = await action

      expect(result.exitCode).toBe(2)
      expect(stdout.listenerCount('error')).toBe(1)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('times out a hung collector with one fixed report and propagates one abort signal', async () => {
    vi.useFakeTimers()
    let receivedSignal: AbortSignal | undefined
    let aborts = 0
    const collectListeners = vi.fn(({ signal }: { signal: AbortSignal }) => {
      receivedSignal = signal
      signal.addEventListener('abort', () => { aborts += 1 }, { once: true })
      return new Promise(() => undefined)
    })
    try {
      const action = invoke({
        argv: [...validPrefix, '--inventory-only'],
        collectListeners,
      })
      await vi.advanceTimersByTimeAsync(WECHAT_OWNED_PROBE_TIMEOUT_MS)
      const result = await action

      expect(result.exitCode).toBe(2)
      expect(result.report.failureCodes).toEqual(['WECHAT_OWNED_PROBE_TIMEOUT'])
      expect(result.collectListeners).toHaveBeenCalledTimes(1)
      expect(result.collectListeners.mock.calls[0]).toEqual([{ signal: receivedSignal }])
      expect(receivedSignal?.aborted).toBe(true)
      expect(aborts).toBe(1)
      expect(result.stdout.trim().split('\n')).toHaveLength(1)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('uses the same total deadline for sequential classifiers and stops after abort', async () => {
    vi.useFakeTimers()
    let firstSignal: AbortSignal | undefined
    const classify = vi.fn(({ signal }: { signal: AbortSignal }) => {
      firstSignal = signal
      return new Promise(() => undefined)
    })
    try {
      const action = invoke({
        argv: [...validPrefix, '--classify'],
        listeners: frozenListeners(
          { host: '127.0.0.1', port: 4567 },
          { host: '::1', port: 4568 },
        ),
        classify,
      })
      await vi.advanceTimersByTimeAsync(WECHAT_OWNED_PROBE_TIMEOUT_MS)
      const result = await action

      expect(result.exitCode).toBe(2)
      expect(result.report.failureCodes).toEqual(['WECHAT_OWNED_PROBE_TIMEOUT'])
      expect(result.classify).toHaveBeenCalledTimes(1)
      expect(firstSignal?.aborted).toBe(true)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('consumes a late classifier rejection after the overall timeout', async () => {
    vi.useFakeTimers()
    const privateValue = 'private-late-classifier-rejection'
    let rejectClassifier!: (error: Error) => void
    const classify = vi.fn(() => new Promise((_resolve, reject) => {
      rejectClassifier = reject
    }))
    const unhandled = vi.fn()
    process.on('unhandledRejection', unhandled)
    try {
      const action = invoke({
        argv: [...validPrefix, '--classify'],
        listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
        classify,
      })
      await vi.advanceTimersByTimeAsync(WECHAT_OWNED_PROBE_TIMEOUT_MS)
      const result = await action
      rejectClassifier(new Error(privateValue))
      await Promise.resolve()
      await Promise.resolve()

      expect(result.exitCode).toBe(2)
      expect(result.report.failureCodes).toEqual(['WECHAT_OWNED_PROBE_TIMEOUT'])
      expect(result.stdout).not.toContain(privateValue)
      expect(unhandled).not.toHaveBeenCalled()
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      process.removeListener('unhandledRejection', unhandled)
      vi.useRealTimers()
    }
  })

  it('fails candidate emission on the same overall deadline without a second write', async () => {
    vi.useFakeTimers()
    const written: string[] = []
    const stdout = {
      write: vi.fn((line: string, _callback: (error?: Error | null) => void) => {
        written.push(line)
        return true
      }),
    }
    try {
      const action = invoke({
        argv: [...validPrefix, '--classify'],
        listeners: frozenListeners({ host: '127.0.0.1', port: 4567 }),
        stdout: stdout as never,
      })
      await vi.advanceTimersByTimeAsync(WECHAT_OWNED_PROBE_TIMEOUT_MS)
      const result = await action

      expect(result.exitCode).toBe(2)
      expect(stdout.write).toHaveBeenCalledTimes(1)
      expect(written).toHaveLength(1)
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps a standalone Node process alive until the real overall timeout', async () => {
    const moduleUrl = new URL('../scripts/source-owned/probe-wechat-owned.mjs', import.meta.url).href
    const source = `
      import { runWechatOwnedProbeCli } from ${JSON.stringify(moduleUrl)}
      const exitCode = await runWechatOwnedProbeCli({
        argv: [
          '--redact',
          '--isolated-test-user-confirmed',
          '--test-account-confirmed',
          '--inventory-only',
        ],
        collectListeners: () => new Promise(() => undefined),
      })
      process.exitCode = exitCode
    `
    const result = await runStandaloneNode(source)

    expect(result.error?.code).toBe(2)
    expect(result.stderr).toBe('')
    expect(JSON.parse(result.stdout).failureCodes).toEqual(['WECHAT_OWNED_PROBE_TIMEOUT'])
    expect(result.elapsedMs).toBeGreaterThanOrEqual(WECHAT_OWNED_PROBE_TIMEOUT_MS - 250)
    expect(result.elapsedMs).toBeLessThan(WECHAT_OWNED_PROBE_TIMEOUT_MS + 3_000)
  }, WECHAT_OWNED_PROBE_TIMEOUT_MS + 4_000)

  it('executes through a symlink and rejects invalid args before live inventory', () => {
    const temporaryRoot = mkdtempSync(join(tmpdir(), 'wechat-owned-cli-link-'))
    try {
      const linked = join(temporaryRoot, 'probe-wechat-owned.mjs')
      symlinkSync(resolve(import.meta.dirname, '../scripts/source-owned/probe-wechat-owned.mjs'), linked)
      const result = spawnSync(process.execPath, [linked, '--redact'], {
        encoding: 'utf8',
        timeout: 5_000,
        maxBuffer: 4_096,
      })
      expect(result.status).toBe(2)
      expect(result.signal).toBeNull()
      expect(result.stderr).toBe('')
      expect(result.stdout.trim().split('\n')).toHaveLength(1)
      const evidence = JSON.parse(result.stdout)
      expect(evidence.failureCodes).toEqual(['WECHAT_OWNED_PROBE_ARGUMENTS_INVALID'])
      expectStrictUnprovenReport(evidence)
    } finally {
      rmSync(temporaryRoot, { recursive: true, force: true })
    }
  })
})
