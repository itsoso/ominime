import { realpathSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  requiredCapabilityKeys,
  sanitizeSourceOwnedEvidence,
} from './evidence.mjs'
import { classifyLoopback } from './loopback-classifier.mjs'
import { collectWechatListeners } from './wechat-listeners.mjs'

const allowedArguments = new Set([
  '--redact',
  '--isolated-test-user-confirmed',
  '--test-account-confirmed',
  '--inventory-only',
  '--classify',
])

const requiredArguments = Object.freeze([
  '--redact',
  '--isolated-test-user-confirmed',
  '--test-account-confirmed',
])

const summaryKeys = Object.freeze([
  'protocolClass',
  'bannerClass',
  'alpnClass',
  'statusClass',
  'allowHeaderPresent',
  'linkHeaderPresent',
  'wwwAuthenticateHeaderPresent',
])

const runnerOptionKeys = new Set([
  'argv',
  'collectListeners',
  'classify',
  'stdout',
])

const standardProtocols = new Set(['banner', 'http', 'tls'])
export const WECHAT_OWNED_PROBE_TIMEOUT_MS = 5_000

function exactArrayValues(value, stringsOnly = true) {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype) return null
  const descriptors = Object.getOwnPropertyDescriptors(value)
  const lengthDescriptor = descriptors.length
  if (
    lengthDescriptor === undefined
    || !('value' in lengthDescriptor)
    || lengthDescriptor.enumerable
    || !Number.isSafeInteger(lengthDescriptor.value)
    || lengthDescriptor.value < 0
  ) return null

  const expectedKeys = new Set(['length'])
  const result = []
  for (let index = 0; index < lengthDescriptor.value; index += 1) {
    const key = String(index)
    expectedKeys.add(key)
    const descriptor = descriptors[key]
    if (
      descriptor === undefined
      || !('value' in descriptor)
      || !descriptor.enumerable
      || (stringsOnly && typeof descriptor.value !== 'string')
    ) return null
    result.push(descriptor.value)
  }
  const ownKeys = Reflect.ownKeys(value)
  if (
    ownKeys.length !== expectedKeys.size
    || ownKeys.some(key => typeof key !== 'string' || !expectedKeys.has(key))
  ) return null
  return result
}

function parseArguments(argv) {
  let values
  try {
    values = exactArrayValues(argv)
  } catch {
    return null
  }
  if (values === null) return null

  const seen = new Set()
  for (const argument of values) {
    if (!allowedArguments.has(argument) || seen.has(argument)) return null
    seen.add(argument)
  }
  if (requiredArguments.some(argument => !seen.has(argument))) return null
  const inventoryOnly = seen.has('--inventory-only')
  const classify = seen.has('--classify')
  if (inventoryOnly === classify) return null
  return inventoryOnly ? 'inventory-only' : 'classify'
}

function sanitizeRunnerOptions(value) {
  try {
    if (value === undefined) return Object.create(null)
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
    const prototype = Object.getPrototypeOf(value)
    if (prototype !== Object.prototype && prototype !== null) return null
    const ownKeys = Reflect.ownKeys(value)
    if (ownKeys.some(key => typeof key !== 'string' || !runnerOptionKeys.has(key))) return null
    const descriptors = Object.getOwnPropertyDescriptors(value)
    const result = Object.create(null)
    for (const key of ownKeys) {
      const descriptor = descriptors[key]
      if (descriptor === undefined || !('value' in descriptor) || !descriptor.enumerable) return null
      result[key] = descriptor.value
    }
    return result
  } catch {
    return null
  }
}

function falseCapabilities() {
  return Object.fromEntries(requiredCapabilityKeys.map(key => [key, false]))
}

function report({ status = 'block', protocolClass = null, failureCode }) {
  return sanitizeSourceOwnedEvidence({
    source: 'wechat',
    interfaceClass: 'app_loopback',
    status,
    protocolClass,
    authorizationClass: null,
    versionClass: null,
    capabilities: falseCapabilities(),
    fieldMappings: {},
    failureCodes: [failureCode],
  })
}

function exactRecordValues(value, keys) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) return null
  const ownKeys = Reflect.ownKeys(value)
  if (
    ownKeys.length !== keys.length
    || ownKeys.some(key => typeof key !== 'string' || !keys.includes(key))
  ) return null
  const descriptors = Object.getOwnPropertyDescriptors(value)
  const result = Object.create(null)
  for (const key of keys) {
    const descriptor = descriptors[key]
    if (descriptor === undefined || !('value' in descriptor) || !descriptor.enumerable) return null
    result[key] = descriptor.value
  }
  return result
}

function sanitizeCandidates(value) {
  try {
    if (!Object.isFrozen(value)) return null
    const candidates = exactArrayValues(value, false)
    if (candidates === null) return null

    const result = []
    for (const candidate of candidates) {
      if (!Object.isFrozen(candidate)) return null
      const raw = exactRecordValues(candidate, ['host', 'port'])
      if (raw === null) return null
      if (raw.host !== '127.0.0.1' && raw.host !== '::1') return null
      if (!Number.isSafeInteger(raw.port) || raw.port < 1 || raw.port > 65_535) return null
      result.push(Object.freeze({ host: raw.host, port: raw.port }))
    }
    return Object.freeze(result)
  } catch {
    return null
  }
}

function sanitizeSummary(value) {
  try {
    if (!Object.isFrozen(value)) return null
    const raw = exactRecordValues(value, summaryKeys)
    if (raw === null) return null
    if (!standardProtocols.has(raw.protocolClass)) return null
    if (raw.bannerClass !== null && raw.bannerClass !== 'ssh') return null
    if (raw.alpnClass !== null && raw.alpnClass !== 'http1') return null
    if (raw.statusClass !== null && !/^[1-5]xx$/.test(raw.statusClass)) return null
    for (const key of [
      'allowHeaderPresent',
      'linkHeaderPresent',
      'wwwAuthenticateHeaderPresent',
    ]) {
      if (typeof raw[key] !== 'boolean') return null
    }
    const anyHeader = raw.allowHeaderPresent
      || raw.linkHeaderPresent
      || raw.wwwAuthenticateHeaderPresent
    if (raw.statusClass === null && anyHeader) return null

    if (raw.protocolClass === 'banner') {
      if (
        raw.bannerClass !== 'ssh'
        || raw.alpnClass !== null
        || raw.statusClass !== null
        || anyHeader
      ) return null
    }
    if (raw.protocolClass === 'http') {
      if (raw.bannerClass !== null || raw.alpnClass !== null || raw.statusClass === null) return null
    }
    if (raw.protocolClass === 'tls') {
      if (raw.bannerClass !== null) return null
      if (raw.alpnClass === null && (raw.statusClass !== null || anyHeader)) return null
    }
    return raw.protocolClass
  } catch {
    return null
  }
}

function createOverallDeadline() {
  const controller = new AbortController()
  let expired = false
  let resolveBoundary
  const boundary = new Promise((resolveBoundaryPromise) => {
    resolveBoundary = resolveBoundaryPromise
  })
  const timeout = setTimeout(() => {
    expired = true
    controller.abort()
    resolveBoundary(Object.freeze({ kind: 'timeout' }))
  }, WECHAT_OWNED_PROBE_TIMEOUT_MS)

  return Object.freeze({
    signal: controller.signal,
    boundary,
    expired: () => expired,
    close() {
      clearTimeout(timeout)
    },
  })
}

async function awaitExternal(deadline, action) {
  if (deadline.expired()) return Object.freeze({ kind: 'timeout' })
  const external = Promise.resolve().then(action).then(
    value => Object.freeze({ kind: 'value', value }),
    () => Object.freeze({ kind: 'error' }),
  )
  const outcome = await Promise.race([external, deadline.boundary])
  return deadline.expired() ? Object.freeze({ kind: 'timeout' }) : outcome
}

async function writeReport(stdout, evidence, deadline) {
  let write
  let addErrorListener
  let removeErrorListener
  try {
    if (stdout === null || typeof stdout !== 'object') return false
    write = stdout.write
    addErrorListener = stdout.on
    removeErrorListener = stdout.removeListener
  } catch {
    return false
  }
  if (typeof write !== 'function') return false
  const eventMethodsAbsent = addErrorListener === undefined && removeErrorListener === undefined
  if (
    !eventMethodsAbsent
    && (typeof addErrorListener !== 'function' || typeof removeErrorListener !== 'function')
  ) return false

  const line = `${JSON.stringify(evidence)}\n`
  const emission = new Promise((resolveEmission) => {
    let returned = false
    let resultSettled = false
    let terminalSettled = false
    let deadlineExpired = false
    let callbackCount = 0
    let firstCallbackSucceeded = false
    let streamError = false
    let errorListenerAttached = false
    let finalization
    const callbackOnlyFinalization = Object.freeze({})
    const onError = () => {
      streamError = true
      if (returned) scheduleFinalization()
    }
    const cleanupGuard = () => {
      let succeeded = true
      if (finalization !== undefined) {
        if (finalization !== callbackOnlyFinalization) clearImmediate(finalization)
        finalization = undefined
      }
      if (errorListenerAttached) {
        errorListenerAttached = false
        try {
          removeErrorListener.call(stdout, 'error', onError)
        } catch {
          succeeded = false
        }
      }
      return succeeded
    }
    const resolveResult = (success) => {
      if (resultSettled) return
      resultSettled = true
      resolveEmission(success)
    }
    const finishTerminal = (success) => {
      if (terminalSettled) return
      terminalSettled = true
      const cleanupSucceeded = cleanupGuard()
      resolveResult(!deadlineExpired && success && cleanupSucceeded)
    }
    const scheduleFinalization = () => {
      if (terminalSettled || finalization !== undefined) return
      if (eventMethodsAbsent) {
        finalization = callbackOnlyFinalization
        queueMicrotask(() => {
          if (finalization !== callbackOnlyFinalization) return
          finalization = undefined
          finishTerminal(callbackCount === 1 && firstCallbackSucceeded && !streamError)
        })
        return
      }
      finalization = setImmediate(() => {
        finalization = undefined
        finishTerminal(callbackCount === 1 && firstCallbackSucceeded && !streamError)
      })
    }
    const callback = (error) => {
      callbackCount += 1
      if (callbackCount === 1) firstCallbackSucceeded = error === undefined || error === null
      if (returned) scheduleFinalization()
    }
    try {
      if (!eventMethodsAbsent) {
        errorListenerAttached = true
        addErrorListener.call(stdout, 'error', onError)
      }
      write.call(stdout, line, callback)
      returned = true
      if (callbackCount > 0 || streamError) scheduleFinalization()
    } catch {
      finishTerminal(false)
    }
    deadline?.boundary.then(() => {
      deadlineExpired = true
      if (callbackCount > 0 || streamError) scheduleFinalization()
      else resolveResult(false)
    })
  })

  const emitted = await emission
  return emitted && (deadline === undefined || !deadline.expired())
}

async function finish(stdout, evidence, exitCode, deadline) {
  const emitted = await writeReport(stdout, evidence, deadline)
  if (exitCode === 0 && (!emitted || deadline.expired())) return 2
  return exitCode
}

export async function runWechatOwnedProbeCli(options) {
  const injected = sanitizeRunnerOptions(options)
  if (injected === null) return 2
  const argv = injected.argv ?? process.argv.slice(2)
  const collectListeners = injected.collectListeners ?? collectWechatListeners
  const classify = injected.classify ?? classifyLoopback
  const stdout = injected.stdout ?? process.stdout
  const deadline = createOverallDeadline()
  try {
    const mode = parseArguments(argv)
    if (mode === null || typeof collectListeners !== 'function' || typeof classify !== 'function') {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_OWNED_PROBE_ARGUMENTS_INVALID' }),
        2,
        deadline,
      )
    }

    const inventory = await awaitExternal(
      deadline,
      () => collectListeners(Object.freeze({ signal: deadline.signal })),
    )
    if (inventory.kind === 'timeout') {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_OWNED_PROBE_TIMEOUT' }),
        2,
        deadline,
      )
    }
    if (inventory.kind === 'error') {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_OWNED_LISTENER_INVENTORY_FAILED' }),
        2,
        deadline,
      )
    }

    const listeners = sanitizeCandidates(inventory.value)
    if (listeners === null) {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_OWNED_LISTENER_INVENTORY_FAILED' }),
        2,
        deadline,
      )
    }
    if (listeners.length === 0) {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_OWNED_LISTENER_NOT_FOUND' }),
        2,
        deadline,
      )
    }
    if (mode === 'inventory-only') {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_INTERFACE_CONTRACT_NOT_PROVEN' }),
        2,
        deadline,
      )
    }

    const protocols = []
    let inconsistent = false
    let failed = false
    for (const listener of listeners) {
      const classified = await awaitExternal(
        deadline,
        () => classify(Object.freeze({ ...listener, signal: deadline.signal })),
      )
      if (classified.kind === 'timeout') {
        return await finish(
          stdout,
          report({ failureCode: 'WECHAT_OWNED_PROBE_TIMEOUT' }),
          2,
          deadline,
        )
      }
      if (classified.kind === 'error') {
        failed = true
        continue
      }
      const protocol = sanitizeSummary(classified.value)
      if (protocol === null) inconsistent = true
      else protocols.push(protocol)
    }

    if (inconsistent) {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_STANDARD_PROTOCOL_INCONSISTENT' }),
        2,
        deadline,
      )
    }
    if (failed || protocols.length === 0) {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_STANDARD_PROTOCOL_NOT_PROVEN' }),
        2,
        deadline,
      )
    }
    if (protocols.length > 1) {
      return await finish(
        stdout,
        report({ failureCode: 'WECHAT_STANDARD_PROTOCOL_AMBIGUOUS' }),
        2,
        deadline,
      )
    }

    return await finish(stdout, report({
      status: 'candidate',
      protocolClass: protocols[0],
      failureCode: 'WECHAT_INTERFACE_CONTRACT_NOT_PROVEN',
    }), 0, deadline)
  } finally {
    deadline.close()
  }
}

function isDirectInvocation() {
  try {
    if (process.argv[1] === undefined) return false
    return realpathSync(resolve(process.argv[1])) === realpathSync(fileURLToPath(import.meta.url))
  } catch {
    return false
  }
}

if (isDirectInvocation()) {
  process.exitCode = await runWechatOwnedProbeCli()
}
