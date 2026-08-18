import { execFile } from 'node:child_process'
import { describe, expect, it, vi } from 'vitest'
import { collectWechatListeners } from '../scripts/source-owned/wechat-listeners.mjs'

const executable = '/Applications/WeChat.app/Contents/MacOS/WeChat'
const bundle = '/Applications/WeChat.app'

type Output = { stdout: string; stderr: string; exitCode?: number }
type OutputKey = 'pgrep' | 'ps' | 'identityBefore' | 'verify' | 'display' | 'lsof'
  | 'identityAfter' | 'psAfter' | 'verifyAfter' | 'displayAfter'

const goodOutputs: Record<OutputKey, Output> = {
  pgrep: { stdout: '123\n', stderr: '' },
  ps: { stdout: `${executable}\n`, stderr: '' },
  identityBefore: { stdout: '501 Mon Aug 18 03:00:00 2026\n', stderr: '' },
  verify: { stdout: '', stderr: '' },
  display: {
    stdout: '',
    stderr: [
      'Executable=/Applications/WeChat.app/Contents/MacOS/WeChat',
      'Identifier=com.tencent.xinWeChat',
      'TeamIdentifier=5A4RE8SF68',
      '',
    ].join('\n'),
  },
  lsof: {
    stdout: [
      'p123',
      'cWeChat',
      'f17',
      'n127.0.0.1:4567',
      'TST=LISTEN',
      'f18',
      'n[::1]:4568',
      'TST=LISTEN',
      '',
    ].join('\n'),
    stderr: '',
  },
  identityAfter: { stdout: '501 Mon Aug 18 03:00:00 2026\n', stderr: '' },
  psAfter: { stdout: `${executable}\n`, stderr: '' },
  verifyAfter: { stdout: '', stderr: '' },
  displayAfter: {
    stdout: '',
    stderr: [
      'Executable=/Applications/WeChat.app/Contents/MacOS/WeChat',
      'Identifier=com.tencent.xinWeChat',
      'TeamIdentifier=5A4RE8SF68',
      '',
    ].join('\n'),
  },
}

type Overrides = Partial<Record<OutputKey, Output>>

function inventedRunner(overrides: Overrides = {}) {
  const outputs = { ...goodOutputs, ...overrides }
  let commCalls = 0
  let identityCalls = 0
  let verifyCalls = 0
  let displayCalls = 0

  return vi.fn(async (file: string, args: string[], _options?: object) => {
    if (file === '/usr/bin/pgrep') return outputs.pgrep
    if (file === '/bin/ps' && args.includes('comm=')) {
      commCalls += 1
      return commCalls === 1 ? outputs.ps : outputs.psAfter
    }
    if (file === '/bin/ps' && args.includes('uid=')) {
      identityCalls += 1
      return identityCalls === 1 ? outputs.identityBefore : outputs.identityAfter
    }
    if (file === '/usr/sbin/lsof') return outputs.lsof
    if (file === '/usr/bin/codesign' && args[0] === '--verify') {
      verifyCalls += 1
      return verifyCalls === 1 ? outputs.verify : outputs.verifyAfter
    }
    if (file === '/usr/bin/codesign' && args[0] === '--display') {
      displayCalls += 1
      return displayCalls === 1 ? outputs.display : outputs.displayAfter
    }
    throw new Error('invented unexpected command')
  })
}

function identityRealpath(path: string) {
  return Promise.resolve(path)
}

function collectWith(
  runner = inventedRunner(),
  realpath: (path: string) => Promise<string> = identityRealpath,
  signal?: AbortSignal,
  currentUid: () => number = () => 501,
) {
  return collectWechatListeners({ runner, realpath, signal, currentUid })
}

function runStandaloneNode(source: string) {
  const startedAt = Date.now()
  return new Promise<{
    error: Error & { code?: number | string } | null
    stdout: string
    stderr: string
    elapsedMs: number
  }>((resolve) => {
    execFile(
      process.execPath,
      ['--input-type=module', '--eval', source],
      { encoding: 'utf8', timeout: 5_000, maxBuffer: 1_024 },
      (error, stdout, stderr) => resolve({
        error,
        stdout,
        stderr,
        elapsedMs: Date.now() - startedAt,
      }),
    )
  })
}

async function expectFixedError(
  action: Promise<unknown>,
  code: string,
  privateValues: string[] = [],
) {
  let thrown: unknown
  try {
    await action
  } catch (error) {
    thrown = error
  }

  expect(thrown).toBeInstanceOf(Error)
  expect(thrown).toMatchObject({ name: 'WechatListenerError', code, message: code })
  expect(Object.keys(thrown as object).sort()).toEqual(['code', 'name'])
  const serialized = `${String(thrown)}\n${JSON.stringify(thrown)}\n${(thrown as Error).stack}`
  for (const privateValue of privateValues) {
    expect(serialized).not.toContain(privateValue)
  }
}

describe('passive source-owned WeChat listener inventory', () => {
  it('uses only bounded absolute commands and returns a deeply frozen allowlisted result', async () => {
    const runner = inventedRunner()
    const realpath = vi.fn(identityRealpath)

    const listeners = await collectWith(runner, realpath)

    expect(listeners).toEqual([
      { host: '127.0.0.1', port: 4567 },
      { host: '::1', port: 4568 },
    ])
    expect(Object.isFrozen(listeners)).toBe(true)
    expect(listeners.every(Object.isFrozen)).toBe(true)
    expect(listeners.map(Object.keys)).toEqual([['host', 'port'], ['host', 'port']])
    expect(realpath.mock.calls).toEqual([
      [executable],
      [bundle],
      [executable],
      [bundle],
    ])
    expect(runner.mock.calls.map(([file, args]) => [file, args])).toEqual([
      ['/usr/bin/pgrep', ['-x', 'WeChat']],
      ['/bin/ps', ['-p', '123', '-o', 'comm=']],
      ['/bin/ps', ['-p', '123', '-o', 'uid=', '-o', 'lstart=']],
      ['/usr/bin/codesign', ['--verify', '--strict', '--verbose=2', bundle]],
      ['/usr/bin/codesign', ['--display', '--verbose=4', bundle]],
      ['/usr/sbin/lsof', ['-nP', '-a', '-p', '123', '-iTCP', '-sTCP:LISTEN', '-FpcfnT']],
      ['/bin/ps', ['-p', '123', '-o', 'comm=']],
      ['/usr/bin/codesign', ['--verify', '--strict', '--verbose=2', bundle]],
      ['/usr/bin/codesign', ['--display', '--verbose=4', bundle]],
      ['/bin/ps', ['-p', '123', '-o', 'uid=', '-o', 'lstart=']],
    ])
    for (const [, , options] of runner.mock.calls) {
      expect(options).toMatchObject({ encoding: 'utf8', timeout: 2_000, maxBuffer: 32_768 })
      expect(options.signal).toBeInstanceOf(AbortSignal)
    }
  })

  it.each([
    ['no exact main process', '', 'WECHAT_PROCESS_NOT_FOUND'],
    ['multiple exact main processes', '123\n124\n', 'WECHAT_PROCESS_AMBIGUOUS'],
    ['malformed process identifier', '123x\n', 'WECHAT_PROCESS_INVALID'],
    ['unsafe process identifier', '0\n', 'WECHAT_PROCESS_INVALID'],
  ])('rejects %s', async (_name, stdout, code) => {
    await expectFixedError(
      collectWith(inventedRunner({ pgrep: { stdout, stderr: '' } })),
      code,
    )
  })

  it.each([
    ['helper executable', '/Applications/WeChat.app/Contents/MacOS/WeChat Helper\n'],
    ['lookalike bundle', '/Applications/WeChat.app.evil/Contents/MacOS/WeChat\n'],
    ['path traversal', '/Applications/WeChat.app/Contents/Helpers/../MacOS/WeChat\n'],
    ['relative executable', 'Applications/WeChat.app/Contents/MacOS/WeChat\n'],
  ])('rejects %s instead of treating it as the exact main process', async (_name, stdout) => {
    await expectFixedError(
      collectWith(inventedRunner({ ps: { stdout, stderr: '' } })),
      'WECHAT_BUNDLE_OWNERSHIP_INVALID',
    )
  })

  it('rejects symlink-ambiguous executable ownership after resolving both paths', async () => {
    const realpath = vi.fn(async (path: string) => (
      path === executable ? '/private/redirect/WeChat' : path
    ))

    await expectFixedError(
      collectWith(inventedRunner(), realpath),
      'WECHAT_BUNDLE_OWNERSHIP_INVALID',
      ['/private/redirect/WeChat'],
    )
  })

  it.each([
    [
      'bundle identifier',
      'Identifier=com.tencent.xinWeChat.beta\nTeamIdentifier=5A4RE8SF68\n',
    ],
    [
      'team identifier',
      'Identifier=com.tencent.xinWeChat\nTeamIdentifier=AAAAAAAAAA\n',
    ],
    [
      'duplicate identity claims',
      'Identifier=com.tencent.xinWeChat\nIdentifier=com.tencent.xinWeChat\nTeamIdentifier=5A4RE8SF68\n',
    ],
  ])('rejects a mismatched or ambiguous %s', async (_name, stderr) => {
    await expectFixedError(
      collectWith(inventedRunner({ display: { stdout: '', stderr } })),
      'WECHAT_SIGNATURE_INVALID',
      [stderr.trim()],
    )
  })

  it.each([
    ['wildcard', 'p123\ncWeChat\nn*:4567\n', 'WECHAT_NON_LOOPBACK_LISTENER'],
    ['IPv4 wildcard', 'p123\ncWeChat\nf1\nn0.0.0.0:4567\nTST=LISTEN\n', 'WECHAT_NON_LOOPBACK_LISTENER'],
    ['LAN address', 'p123\ncWeChat\nf1\nn192.168.1.8:4567\nTST=LISTEN\n', 'WECHAT_NON_LOOPBACK_LISTENER'],
    ['public address', 'p123\ncWeChat\nf1\nn203.0.113.9:4567\nTST=LISTEN\n', 'WECHAT_NON_LOOPBACK_LISTENER'],
    ['IPv6 wildcard', 'p123\ncWeChat\nf1\nn[::]:4567\nTST=LISTEN\n', 'WECHAT_NON_LOOPBACK_LISTENER'],
    ['malformed endpoint', 'p123\ncWeChat\nf1\nnnot-an-endpoint\nTST=LISTEN\n', 'WECHAT_LISTENER_OUTPUT_INVALID'],
    ['leading-zero descriptor', 'p123\ncWeChat\nf01\nn127.0.0.1:4567\nTST=LISTEN\n', 'WECHAT_LISTENER_OUTPUT_INVALID'],
    [
      'duplicate descriptor',
      'p123\ncWeChat\nf1\nn127.0.0.1:4567\nTST=LISTEN\nf1\nn[::1]:4568\nTST=LISTEN\n',
      'WECHAT_LISTENER_OUTPUT_INVALID',
    ],
    ['zero port', 'p123\ncWeChat\nf1\nn127.0.0.1:0\nTST=LISTEN\n', 'WECHAT_LISTENER_PORT_INVALID'],
    ['out-of-range port', 'p123\ncWeChat\nf1\nn127.0.0.1:65536\nTST=LISTEN\n', 'WECHAT_LISTENER_PORT_INVALID'],
    [
      'duplicate listener',
      'p123\ncWeChat\nf1\nn127.0.0.1:4567\nTST=LISTEN\nf2\nn127.0.0.1:4567\nTST=LISTEN\n',
      'WECHAT_DUPLICATE_LISTENER',
    ],
  ])('fails closed for a %s without reflecting it', async (_name, stdout, code) => {
    await expectFixedError(
      collectWith(inventedRunner({ lsof: { stdout, stderr: '' } })),
      code,
      [stdout.trim()],
    )
  })

  it.each([
    ['wrong process owner', 'p124\ncWeChat\nf1\nn127.0.0.1:4567\nTST=LISTEN\n', 'WECHAT_LISTENER_OWNERSHIP_INVALID'],
    ['helper command owner', 'p123\ncWeChat Helper\nf1\nn127.0.0.1:4567\nTST=LISTEN\n', 'WECHAT_LISTENER_OWNERSHIP_INVALID'],
    ['non-listening socket', 'p123\ncWeChat\nf1\nn127.0.0.1:4567\nTST=CLOSED\n', 'WECHAT_LISTENER_STATE_INVALID'],
    ['missing listen state', 'p123\ncWeChat\nf1\nn127.0.0.1:4567\n', 'WECHAT_LISTENER_STATE_INVALID'],
  ])('rejects %s', async (_name, stdout, code) => {
    await expectFixedError(
      collectWith(inventedRunner({ lsof: { stdout, stderr: '' } })),
      code,
    )
  })

  it('does not return or log raw ps, lsof, codesign, or runner errors', async () => {
    const privateValue = 'private-command-output-token'
    const privateExecutable = `/private/${privateValue}/WeChat.app/Contents/MacOS/WeChat`
    const successfulRunner = inventedRunner({
      ps: { stdout: `${privateExecutable}\n`, stderr: '' },
      psAfter: { stdout: `${privateExecutable}\n`, stderr: '' },
      display: {
        stdout: '',
        stderr: `${privateValue}\nIdentifier=com.tencent.xinWeChat\nTeamIdentifier=5A4RE8SF68\n`,
      },
      displayAfter: {
        stdout: '',
        stderr: `${privateValue}\nIdentifier=com.tencent.xinWeChat\nTeamIdentifier=5A4RE8SF68\n`,
      },
    })
    const failingRunner = vi.fn(async (): Promise<Output> => {
      throw new Error(privateValue)
    })
    const spies = [
      vi.spyOn(console, 'log').mockImplementation(() => undefined),
      vi.spyOn(console, 'error').mockImplementation(() => undefined),
      vi.spyOn(console, 'warn').mockImplementation(() => undefined),
      vi.spyOn(console, 'debug').mockImplementation(() => undefined),
    ]

    try {
      const result = await collectWith(successfulRunner)
      expect(JSON.stringify(result)).not.toContain(privateValue)
      expect(JSON.stringify(result)).not.toContain('TST=LISTEN')
      await expectFixedError(collectWith(failingRunner), 'WECHAT_COMMAND_FAILED', [privateValue])
      for (const spy of spies) expect(spy).not.toHaveBeenCalled()
    } finally {
      for (const spy of spies) spy.mockRestore()
    }
  })

  it.each([
    ['abort', Object.assign(new Error('private abort'), { name: 'AbortError' }), 'WECHAT_COMMAND_ABORTED'],
    ['timeout', Object.assign(new Error('private timeout'), { code: 'ETIMEDOUT' }), 'WECHAT_COMMAND_TIMEOUT'],
    [
      'oversized output',
      Object.assign(new Error('private oversized output'), { code: 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER' }),
      'WECHAT_COMMAND_OUTPUT_TOO_LARGE',
    ],
    ['command failure', Object.assign(new Error('private failure'), { code: 'EACCES' }), 'WECHAT_COMMAND_FAILED'],
  ])('maps %s to one fixed non-reflective code', async (_name, failure, code) => {
    const runner = vi.fn(async (): Promise<Output> => {
      throw failure
    })

    await expectFixedError(collectWith(runner), code, [failure.message])
  })

  it('normalizes a runner failure whose diagnostic properties throw', async () => {
    const privateValue = 'private throwing diagnostic getter'
    const failure = new Proxy(new Error(privateValue), {
      get(_target, property) {
        if (property === 'code' || property === 'name') throw new Error(privateValue)
        return Reflect.get(_target, property)
      },
    })
    const runner = vi.fn(async (): Promise<Output> => {
      throw failure
    })

    await expectFixedError(collectWith(runner), 'WECHAT_COMMAND_FAILED', [privateValue])
  })

  it('hard-times out a signal-ignoring runner that never settles', async () => {
    vi.useFakeTimers()
    let outcome: unknown = 'pending'
    const runner = vi.fn(() => new Promise<Output>(() => undefined))

    try {
      void collectWith(runner).then(
        (value) => { outcome = value },
        (error) => { outcome = error },
      )
      await vi.advanceTimersByTimeAsync(2_001)
      await Promise.resolve()

      expect(outcome).toMatchObject({
        name: 'WechatListenerError',
        code: 'WECHAT_COMMAND_TIMEOUT',
        message: 'WECHAT_COMMAND_TIMEOUT',
      })
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('keeps a standalone Node process alive until a real hard timeout is reported', async () => {
    const moduleUrl = new URL('../scripts/source-owned/wechat-listeners.mjs', import.meta.url).href
    const source = `
      import { collectWechatListeners } from ${JSON.stringify(moduleUrl)}
      try {
        await collectWechatListeners({
          runner: () => new Promise(() => undefined),
          realpath: async (value) => value,
          currentUid: () => 501,
        })
        process.exitCode = 90
      } catch (error) {
        const exact = error?.name === 'WechatListenerError'
          && error?.code === 'WECHAT_COMMAND_TIMEOUT'
          && error?.message === 'WECHAT_COMMAND_TIMEOUT'
        if (!exact) process.exitCode = 91
        else process.stdout.write('WECHAT_COMMAND_TIMEOUT\\n')
      }
    `

    const result = await runStandaloneNode(source)

    expect(result.error).toBeNull()
    expect(result.stdout).toBe('WECHAT_COMMAND_TIMEOUT\n')
    expect(result.stderr).toBe('')
    expect(result.elapsedMs).toBeGreaterThanOrEqual(1_500)
    expect(result.elapsedMs).toBeLessThan(5_000)
  })

  it('cleans bounded-command timers after normal completion and abort', async () => {
    vi.useFakeTimers()
    try {
      await collectWith(inventedRunner())
      expect(vi.getTimerCount()).toBe(0)

      const controller = new AbortController()
      controller.abort()
      await expectFixedError(
        collectWith(inventedRunner(), identityRealpath, controller.signal),
        'WECHAT_COMMAND_ABORTED',
      )
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      vi.useRealTimers()
    }
  })

  it('consumes a losing runner rejection after the hard-timeout result', async () => {
    vi.useFakeTimers()
    let rejectRunner!: (error: Error) => void
    const lateRunner = new Promise<Output>((_resolve, reject) => {
      rejectRunner = reject
    })
    const runner = vi.fn(() => lateRunner)
    const unhandled = vi.fn()
    process.on('unhandledRejection', unhandled)

    try {
      const action = collectWith(runner)
      const timeoutAssertion = expectFixedError(action, 'WECHAT_COMMAND_TIMEOUT')
      await vi.advanceTimersByTimeAsync(2_001)
      await timeoutAssertion
      rejectRunner(new Error('private late runner rejection'))
      await Promise.resolve()
      await Promise.resolve()

      expect(unhandled).not.toHaveBeenCalled()
      expect(vi.getTimerCount()).toBe(0)
    } finally {
      process.off('unhandledRejection', unhandled)
      vi.useRealTimers()
    }
  })

  it('rejects an abort during final listener enumeration even if the runner later resolves', async () => {
    const baseRunner = inventedRunner()
    let resolveListeners!: (output: Output) => void
    const delayedListeners = new Promise<Output>((resolve) => {
      resolveListeners = resolve
    })
    const runner = vi.fn(async (file: string, args: string[], options: object) => {
      if (file === '/usr/sbin/lsof') return delayedListeners
      return baseRunner(file, args, options)
    })
    const controller = new AbortController()
    const action = collectWith(runner, identityRealpath, controller.signal)

    await vi.waitFor(() => {
      expect(runner.mock.calls.some(([file]) => file === '/usr/sbin/lsof')).toBe(true)
    })
    controller.abort(new Error('private final-command abort'))
    resolveListeners(goodOutputs.lsof)

    await expectFixedError(action, 'WECHAT_COMMAND_ABORTED', ['private final-command abort'])
  })

  it('does not miss an abort immediately before listener registration', async () => {
    const controller = new AbortController()
    const signal = controller.signal
    const addEventListener = signal.addEventListener.bind(signal)
    const addSpy = vi.spyOn(signal, 'addEventListener').mockImplementation((...args) => {
      controller.abort(new Error('private registration-window abort'))
      return addEventListener(...args)
    })
    const runner = vi.fn(() => new Promise<Output>(() => undefined))
    let outcome: unknown = 'pending'

    try {
      void collectWith(runner, identityRealpath, signal).then(
        (value) => { outcome = value },
        (error) => { outcome = error },
      )
      await Promise.resolve()
      await Promise.resolve()

      expect(outcome).toMatchObject({
        name: 'WechatListenerError',
        code: 'WECHAT_COMMAND_ABORTED',
        message: 'WECHAT_COMMAND_ABORTED',
      })
      expect(runner).not.toHaveBeenCalled()
    } finally {
      addSpy.mockRestore()
    }
  })

  it('normalizes mutated genuine inventory errors rejected by external dependencies', async () => {
    let captured: any
    try {
      await collectWith(inventedRunner({ pgrep: { stdout: 'invalid\n', stderr: '' } }))
    } catch (error) {
      captured = error
    }
    captured.name = 'PrivateMutatedError'
    captured.code = 'PRIVATE_MUTATED_CODE'
    captured.message = 'private mutated diagnostic'

    const runner = vi.fn(async (): Promise<Output> => {
      throw captured
    })
    await expectFixedError(
      collectWith(runner),
      'WECHAT_COMMAND_FAILED',
      ['private mutated diagnostic', 'PRIVATE_MUTATED_CODE'],
    )

    const realpath = vi.fn(async (): Promise<string> => {
      throw captured
    })
    await expectFixedError(
      collectWith(inventedRunner(), realpath),
      'WECHAT_BUNDLE_OWNERSHIP_INVALID',
      ['private mutated diagnostic', 'PRIVATE_MUTATED_CODE'],
    )
  })

  it('requires the main process to belong to the exact current uid', async () => {
    await expectFixedError(
      collectWith(inventedRunner({
        identityBefore: { stdout: '502 Mon Aug 18 03:00:00 2026\n', stderr: '' },
      })),
      'WECHAT_PROCESS_UID_MISMATCH',
    )
  })

  it('rejects a process restart between listener checks', async () => {
    await expectFixedError(
      collectWith(inventedRunner({
        identityAfter: { stdout: '501 Mon Aug 18 03:00:01 2026\n', stderr: '' },
      })),
      'WECHAT_PROCESS_IDENTITY_CHANGED',
    )
  })

  it('rejects an executable or bundle path swap after listener enumeration', async () => {
    const swappedExecutable = '/private/swapped/WeChat.app/Contents/MacOS/WeChat'

    await expectFixedError(
      collectWith(inventedRunner({
        psAfter: { stdout: `${swappedExecutable}\n`, stderr: '' },
      })),
      'WECHAT_BUNDLE_OWNERSHIP_CHANGED',
      [swappedExecutable],
    )
  })

  it('returns a frozen empty inventory only for the exact lsof no-match exit', async () => {
    const runner = inventedRunner({
      lsof: { stdout: '', stderr: '', exitCode: 1 },
    })

    const listeners = await collectWith(runner)

    expect(listeners).toEqual([])
    expect(Object.isFrozen(listeners)).toBe(true)
    expect(runner).toHaveBeenCalledTimes(10)
  })

  it.each([
    ['nonempty no-match stdout', { stdout: 'private output', stderr: '', exitCode: 1 }],
    ['nonempty no-match stderr', { stdout: '', stderr: 'private error', exitCode: 1 }],
    ['other exit status', { stdout: '', stderr: '', exitCode: 2 }],
  ])('rejects lsof %s as a fixed command failure', async (_name, lsof) => {
    await expectFixedError(
      collectWith(inventedRunner({ lsof })),
      'WECHAT_COMMAND_FAILED',
      [lsof.stdout, lsof.stderr].filter(Boolean),
    )
  })

  it('maps the exact pgrep no-match exit to process-not-found', async () => {
    await expectFixedError(
      collectWith(inventedRunner({
        pgrep: { stdout: '', stderr: '', exitCode: 1 },
      })),
      'WECHAT_PROCESS_NOT_FOUND',
    )
  })

  it.each([
    ['pgrep', { pgrep: { stdout: '123\n', stderr: 'private pgrep warning' } }],
    ['ps', { ps: { stdout: `${executable}\n`, stderr: 'private ps warning' } }],
    ['lsof', { lsof: { ...goodOutputs.lsof, stderr: 'private lsof warning' } }],
  ])('fails closed on successful %s stderr', async (_name, overrides) => {
    const privateValue = Object.values(overrides)[0].stderr
    await expectFixedError(
      collectWith(inventedRunner(overrides)),
      'WECHAT_COMMAND_FAILED',
      [privateValue],
    )
  })

  it('allows codesign verify diagnostics but requires display identity on stderr', async () => {
    const listeners = await collectWith(inventedRunner({
      verify: { stdout: '', stderr: 'synthetic verify diagnostic' },
      verifyAfter: { stdout: '', stderr: 'synthetic verify diagnostic' },
    }))
    expect(listeners).toHaveLength(2)

    await expectFixedError(
      collectWith(inventedRunner({
        display: {
          stdout: 'Identifier=com.tencent.xinWeChat\nTeamIdentifier=5A4RE8SF68\n',
          stderr: '',
        },
      })),
      'WECHAT_COMMAND_FAILED',
    )
  })

  it('rejects oversized successful output even when an injected runner ignores maxBuffer', async () => {
    const privateValue = 'x'.repeat(32_769)
    const runner = inventedRunner({ pgrep: { stdout: privateValue, stderr: '' } })

    await expectFixedError(
      collectWith(runner),
      'WECHAT_COMMAND_OUTPUT_TOO_LARGE',
      [privateValue],
    )
  })

  it('fails with the fixed abort code before invoking a command when already aborted', async () => {
    const runner = inventedRunner()
    const controller = new AbortController()
    controller.abort(new Error('private abort reason'))

    await expectFixedError(
      collectWith(runner, identityRealpath, controller.signal),
      'WECHAT_COMMAND_ABORTED',
      ['private abort reason'],
    )
    expect(runner).not.toHaveBeenCalled()
  })
})
