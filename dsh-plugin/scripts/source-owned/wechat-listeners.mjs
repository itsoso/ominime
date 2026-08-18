import { execFile } from 'node:child_process'
import { realpath as nodeRealpath } from 'node:fs/promises'

export const tools = Object.freeze({
  pgrep: '/usr/bin/pgrep',
  ps: '/bin/ps',
  lsof: '/usr/sbin/lsof',
  codesign: '/usr/bin/codesign',
})

export const expectedSignature = Object.freeze({
  bundleIdentifier: 'com.tencent.xinWeChat',
  teamIdentifier: '5A4RE8SF68',
})

const commandTimeout = 2_000
const commandMaxBuffer = 32_768

class WechatListenerError extends Error {
  constructor(code) {
    super(code)
    this.name = 'WechatListenerError'
    this.code = code
  }
}

function fail(code) {
  throw new WechatListenerError(code)
}

function diagnosticValue(error, key) {
  try {
    return error?.[key]
  } catch {
    return undefined
  }
}

function defaultRunner(file, args, options) {
  return new Promise((resolve, reject) => {
    execFile(file, args, options, (error, stdout, stderr) => {
      if (error) {
        const exitCode = diagnosticValue(error, 'code')
        if (Number.isInteger(exitCode)) {
          resolve({ stdout, stderr, exitCode })
          return
        }
        reject(error)
        return
      }
      resolve({ stdout, stderr, exitCode: 0 })
    })
  })
}

function classifyCommandError(error, externalSignal) {
  if (externalSignal?.aborted) fail('WECHAT_COMMAND_ABORTED')
  const code = diagnosticValue(error, 'code')
  if (code === 'ETIMEDOUT' || diagnosticValue(error, 'killed') === true) {
    fail('WECHAT_COMMAND_TIMEOUT')
  }
  if (code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER') {
    fail('WECHAT_COMMAND_OUTPUT_TOO_LARGE')
  }
  if (diagnosticValue(error, 'name') === 'AbortError') fail('WECHAT_COMMAND_ABORTED')
  fail('WECHAT_COMMAND_FAILED')
}

function outputBytes(stdout, stderr) {
  return Buffer.byteLength(stdout, 'utf8') + Buffer.byteLength(stderr, 'utf8')
}

async function runBounded(runner, file, args, externalSignal) {
  if (externalSignal?.aborted) fail('WECHAT_COMMAND_ABORTED')

  const controller = new AbortController()
  let settleBoundary
  const boundary = new Promise((resolve) => {
    settleBoundary = resolve
  })
  const settleAndTerminate = (kind) => {
    settleBoundary({ kind })
    controller.abort()
  }
  const timeout = setTimeout(() => settleAndTerminate('timeout'), commandTimeout)
  const abort = () => settleAndTerminate('abort')
  externalSignal?.addEventListener('abort', abort, { once: true })
  if (externalSignal?.aborted) {
    clearTimeout(timeout)
    externalSignal.removeEventListener('abort', abort)
    controller.abort()
    fail('WECHAT_COMMAND_ABORTED')
  }

  const runnerOutcome = Promise.resolve().then(() => runner(file, args, {
    encoding: 'utf8',
    timeout: commandTimeout,
    maxBuffer: commandMaxBuffer,
    signal: controller.signal,
  })).then(
    (result) => ({ kind: 'result', result }),
    (error) => ({ kind: 'runner-error', error }),
  )

  let outcome
  try {
    outcome = await Promise.race([runnerOutcome, boundary])
  } finally {
    clearTimeout(timeout)
    externalSignal?.removeEventListener('abort', abort)
  }

  if (outcome.kind === 'timeout') fail('WECHAT_COMMAND_TIMEOUT')
  if (outcome.kind === 'abort' || externalSignal?.aborted) {
    fail('WECHAT_COMMAND_ABORTED')
  }
  if (outcome.kind === 'runner-error') {
    classifyCommandError(outcome.error, externalSignal)
  }

  let stdout
  let stderr
  let exitCode
  try {
    stdout = outcome.result?.stdout
    stderr = outcome.result?.stderr
    exitCode = outcome.result?.exitCode ?? 0
  } catch {
    fail('WECHAT_COMMAND_FAILED')
  }
  if (
    typeof stdout !== 'string'
    || typeof stderr !== 'string'
    || !Number.isInteger(exitCode)
    || exitCode < 0
    || exitCode > 255
  ) fail('WECHAT_COMMAND_FAILED')
  if (outputBytes(stdout, stderr) > commandMaxBuffer) {
    fail('WECHAT_COMMAND_OUTPUT_TOO_LARGE')
  }
  return { stdout, stderr, exitCode }
}

function strictLines(value, invalidCode) {
  if (value.includes('\0') || value.includes('\r')) fail(invalidCode)
  const lines = value.split('\n')
  if (lines.at(-1) === '') lines.pop()
  if (lines.some((line) => line.length === 0)) fail(invalidCode)
  return lines
}

function parsePid(stdout) {
  if (stdout === '') fail('WECHAT_PROCESS_NOT_FOUND')
  const lines = strictLines(stdout, 'WECHAT_PROCESS_INVALID')
  if (lines.length > 1) fail('WECHAT_PROCESS_AMBIGUOUS')
  if (!/^[1-9][0-9]{0,9}$/.test(lines[0])) fail('WECHAT_PROCESS_INVALID')

  const pid = Number(lines[0])
  if (!Number.isSafeInteger(pid) || pid > 2_147_483_647) fail('WECHAT_PROCESS_INVALID')
  return lines[0]
}

function requireSuccess(result, { allowStderr = false, allowStdout = true } = {}) {
  if (
    result.exitCode !== 0
    || (!allowStderr && result.stderr !== '')
    || (!allowStdout && result.stdout !== '')
  ) fail('WECHAT_COMMAND_FAILED')
  return result
}

function defaultCurrentUid() {
  if (typeof process.getuid !== 'function') fail('WECHAT_CURRENT_UID_UNAVAILABLE')
  return process.getuid()
}

function readCurrentUid(currentUid) {
  let uid
  try {
    uid = currentUid()
  } catch {
    fail('WECHAT_CURRENT_UID_UNAVAILABLE')
  }
  if (!Number.isSafeInteger(uid) || uid < 0 || uid > 4_294_967_295) {
    fail('WECHAT_CURRENT_UID_UNAVAILABLE')
  }
  return uid
}

function parseProcessIdentity(stdout, currentUid) {
  const lines = strictLines(stdout, 'WECHAT_PROCESS_IDENTITY_INVALID')
  if (lines.length !== 1) fail('WECHAT_PROCESS_IDENTITY_INVALID')
  const match = /^\s*([0-9]{1,10})\s+([A-Za-z0-9: ]{16,48})$/.exec(lines[0])
  if (!match || match[2].trim() !== match[2]) fail('WECHAT_PROCESS_IDENTITY_INVALID')
  const uid = Number(match[1])
  if (!Number.isSafeInteger(uid) || uid < 0 || uid > 4_294_967_295) {
    fail('WECHAT_PROCESS_IDENTITY_INVALID')
  }
  if (uid !== currentUid) fail('WECHAT_PROCESS_UID_MISMATCH')
  return Object.freeze({ uid, start: match[2] })
}

function canonicalAbsolutePath(value) {
  if (!value.startsWith('/') || value.endsWith('/')) return false
  const components = value.slice(1).split('/')
  return components.length > 0 && components.every((part) => (
    part.length > 0 && part !== '.' && part !== '..' && !part.includes('\0')
  ))
}

function deriveBundlePath(stdout) {
  const lines = strictLines(stdout, 'WECHAT_BUNDLE_OWNERSHIP_INVALID')
  if (lines.length !== 1) fail('WECHAT_BUNDLE_OWNERSHIP_INVALID')
  const executable = lines[0]
  if (!canonicalAbsolutePath(executable)) fail('WECHAT_BUNDLE_OWNERSHIP_INVALID')

  const suffix = '/WeChat.app/Contents/MacOS/WeChat'
  if (!executable.endsWith(suffix)) fail('WECHAT_BUNDLE_OWNERSHIP_INVALID')
  const bundle = executable.slice(0, -'/Contents/MacOS/WeChat'.length)
  if (!canonicalAbsolutePath(bundle)) fail('WECHAT_BUNDLE_OWNERSHIP_INVALID')
  return { executable, bundle }
}

async function resolveBundleOwnership(stdout, realpath) {
  const paths = deriveBundlePath(stdout)
  let resolvedPaths
  try {
    resolvedPaths = await Promise.all([
      realpath(paths.executable),
      realpath(paths.bundle),
    ])
  } catch {
    fail('WECHAT_BUNDLE_OWNERSHIP_INVALID')
  }
  const [resolvedExecutable, resolvedBundle] = resolvedPaths
  if (
    typeof resolvedExecutable !== 'string'
    || typeof resolvedBundle !== 'string'
    || !canonicalAbsolutePath(resolvedExecutable)
    || !canonicalAbsolutePath(resolvedBundle)
    || !resolvedBundle.endsWith('/WeChat.app')
    || resolvedExecutable !== `${resolvedBundle}/Contents/MacOS/WeChat`
  ) fail('WECHAT_BUNDLE_OWNERSHIP_INVALID')
  return Object.freeze({ executable: resolvedExecutable, bundle: resolvedBundle })
}

function verifySignature(stderr) {
  const lines = strictLines(stderr, 'WECHAT_SIGNATURE_INVALID')
  const identifiers = lines.filter((line) => line.startsWith('Identifier='))
  const teams = lines.filter((line) => line.startsWith('TeamIdentifier='))
  if (
    identifiers.length !== 1
    || teams.length !== 1
    || identifiers[0] !== `Identifier=${expectedSignature.bundleIdentifier}`
    || teams[0] !== `TeamIdentifier=${expectedSignature.teamIdentifier}`
  ) fail('WECHAT_SIGNATURE_INVALID')
}

function parseEndpoint(line) {
  const ipv4 = /^n127\.0\.0\.1:([0-9]+)$/.exec(line)
  const ipv6 = /^n\[::1\]:([0-9]+)$/.exec(line)
  const match = ipv4 ?? ipv6
  if (match) {
    const port = Number(match[1])
    if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
      fail('WECHAT_LISTENER_PORT_INVALID')
    }
    return Object.freeze({ host: ipv4 ? '127.0.0.1' : '::1', port })
  }

  if (/^n(?:\*|[^\s:[\]]+):[0-9]+$/.test(line) || /^n\[[0-9A-Fa-f:.]+\]:[0-9]+$/.test(line)) {
    fail('WECHAT_NON_LOOPBACK_LISTENER')
  }
  fail('WECHAT_LISTENER_OUTPUT_INVALID')
}

function parseListeners(stdout, pid) {
  const lines = strictLines(stdout, 'WECHAT_LISTENER_OUTPUT_INVALID')

  for (const line of lines) {
    if (line.startsWith('n')) parseEndpoint(line)
  }

  if (lines[0] !== `p${pid}` || lines[1] !== 'cWeChat') {
    fail('WECHAT_LISTENER_OWNERSHIP_INVALID')
  }
  if (lines.slice(2).some((line) => line.startsWith('p') || line.startsWith('c'))) {
    fail('WECHAT_LISTENER_OWNERSHIP_INVALID')
  }

  const listeners = []
  const seen = new Set()
  const descriptors = new Set()
  for (let index = 2; index < lines.length; index += 3) {
    const descriptor = lines[index]
    const endpoint = lines[index + 1]
    const state = lines[index + 2]
    if (!/^f(?:0|[1-9][0-9]*)$/.test(descriptor ?? '') || !endpoint?.startsWith('n')) {
      fail('WECHAT_LISTENER_OUTPUT_INVALID')
    }
    if (descriptors.has(descriptor)) fail('WECHAT_LISTENER_OUTPUT_INVALID')
    descriptors.add(descriptor)
    if (state !== 'TST=LISTEN') fail('WECHAT_LISTENER_STATE_INVALID')

    const listener = parseEndpoint(endpoint)
    const key = `${listener.host}:${listener.port}`
    if (seen.has(key)) fail('WECHAT_DUPLICATE_LISTENER')
    seen.add(key)
    listeners.push(listener)
  }
  return Object.freeze(listeners)
}

async function readProcessIdentity(runner, pid, signal, currentUid) {
  const result = requireSuccess(await runBounded(
    runner,
    tools.ps,
    ['-p', pid, '-o', 'uid=', '-o', 'lstart='],
    signal,
  ))
  return parseProcessIdentity(result.stdout, readCurrentUid(currentUid))
}

async function readBundleOwnership(runner, pid, signal, realpath) {
  const result = requireSuccess(await runBounded(
    runner,
    tools.ps,
    ['-p', pid, '-o', 'comm='],
    signal,
  ))
  return resolveBundleOwnership(result.stdout, realpath)
}

async function verifyBundleSignature(runner, bundle, signal) {
  requireSuccess(await runBounded(
    runner,
    tools.codesign,
    ['--verify', '--strict', '--verbose=2', bundle],
    signal,
  ), { allowStderr: true, allowStdout: false })
  const display = requireSuccess(await runBounded(
    runner,
    tools.codesign,
    ['--display', '--verbose=4', bundle],
    signal,
  ), { allowStderr: true, allowStdout: false })
  verifySignature(display.stderr)
}

export async function collectWechatListeners({
  runner = defaultRunner,
  realpath = nodeRealpath,
  signal,
  currentUid = defaultCurrentUid,
} = {}) {
  if (
    typeof runner !== 'function'
    || typeof realpath !== 'function'
    || typeof currentUid !== 'function'
  ) {
    fail('WECHAT_COMMAND_FAILED')
  }

  const processResult = await runBounded(runner, tools.pgrep, ['-x', 'WeChat'], signal)
  if (processResult.exitCode === 1) {
    if (processResult.stdout === '' && processResult.stderr === '') {
      fail('WECHAT_PROCESS_NOT_FOUND')
    }
    fail('WECHAT_COMMAND_FAILED')
  }
  requireSuccess(processResult)
  const pid = parsePid(processResult.stdout)

  const ownershipBefore = await readBundleOwnership(runner, pid, signal, realpath)
  const identityBefore = await readProcessIdentity(runner, pid, signal, currentUid)
  await verifyBundleSignature(runner, ownershipBefore.bundle, signal)

  const listenerResult = await runBounded(
    runner,
    tools.lsof,
    ['-nP', '-a', '-p', pid, '-iTCP', '-sTCP:LISTEN', '-FpcfnT'],
    signal,
  )
  let listeners
  if (listenerResult.exitCode === 1) {
    if (listenerResult.stdout !== '' || listenerResult.stderr !== '') {
      fail('WECHAT_COMMAND_FAILED')
    }
    listeners = Object.freeze([])
  } else {
    requireSuccess(listenerResult)
    listeners = parseListeners(listenerResult.stdout, pid)
  }

  const ownershipAfter = await readBundleOwnership(runner, pid, signal, realpath)
  if (
    ownershipAfter.executable !== ownershipBefore.executable
    || ownershipAfter.bundle !== ownershipBefore.bundle
  ) fail('WECHAT_BUNDLE_OWNERSHIP_CHANGED')
  await verifyBundleSignature(runner, ownershipAfter.bundle, signal)

  const identityAfter = await readProcessIdentity(runner, pid, signal, currentUid)
  if (
    identityAfter.uid !== identityBefore.uid
    || identityAfter.start !== identityBefore.start
  ) fail('WECHAT_PROCESS_IDENTITY_CHANGED')

  return listeners
}
