import { createConnection as createNetConnection } from 'node:net'
import { connect as createTlsConnection } from 'node:tls'

const allowedInputKeys = new Set(['host', 'port', 'budgets', 'signal'])
const budgetKeys = Object.freeze([
  'stageTimeoutMs',
  'overallTimeoutMs',
  'maxReadBytes',
  'maxConnections',
])
const defaultBudgets = Object.freeze({
  stageTimeoutMs: 250,
  overallTimeoutMs: 1_000,
  maxReadBytes: 4_096,
  maxConnections: 3,
})
const safeRequest = Buffer.from([
  'OPTIONS * HTTP/1.1',
  'Host: localhost',
  'Connection: close',
  '',
  '',
].join('\r\n'), 'ascii')

class LoopbackClassifierError extends Error {
  constructor(code) {
    super(code)
    this.name = 'LoopbackClassifierError'
    this.code = code
  }
}

function fail(code) {
  throw new LoopbackClassifierError(code)
}

function exactRecord(value, allowedKeys, requiredKeys = []) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')
  }
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) {
    fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')
  }
  const keys = Reflect.ownKeys(value)
  if (
    keys.some((key) => typeof key !== 'string' || !allowedKeys.has(key))
    || requiredKeys.some((key) => !keys.includes(key))
  ) fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')

  const descriptors = Object.getOwnPropertyDescriptors(value)
  const result = Object.create(null)
  for (const key of keys) {
    const descriptor = descriptors[key]
    if (!('value' in descriptor) || !descriptor.enumerable) {
      fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')
    }
    result[key] = descriptor.value
  }
  return result
}

function sanitizeBudgets(value) {
  if (value === undefined) return defaultBudgets

  const raw = exactRecord(value, new Set(budgetKeys), budgetKeys)
  const integerWithin = (candidate, minimum, maximum) => (
    Number.isInteger(candidate) && candidate >= minimum && candidate <= maximum
  )
  if (
    !integerWithin(raw.stageTimeoutMs, 10, 2_000)
    || !integerWithin(raw.overallTimeoutMs, 20, 10_000)
    || !integerWithin(raw.maxReadBytes, 64, 16_384)
    || !integerWithin(raw.maxConnections, 1, 3)
  ) fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')

  return Object.freeze({
    stageTimeoutMs: raw.stageTimeoutMs,
    overallTimeoutMs: raw.overallTimeoutMs,
    maxReadBytes: raw.maxReadBytes,
    maxConnections: raw.maxConnections,
  })
}

function sanitizeInput(value) {
  try {
    const raw = exactRecord(value, allowedInputKeys, ['host', 'port'])
    if (raw.host !== '127.0.0.1' && raw.host !== '::1') {
      fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')
    }
    if (!Number.isInteger(raw.port) || raw.port < 1 || raw.port > 65_535) {
      fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')
    }
    if (raw.signal !== undefined && !(raw.signal instanceof AbortSignal)) {
      fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')
    }
    return Object.freeze({
      host: raw.host,
      port: raw.port,
      budgets: sanitizeBudgets(raw.budgets),
      signal: raw.signal,
    })
  } catch (error) {
    if (error instanceof LoopbackClassifierError) throw error
    fail('WECHAT_STANDARD_PROTOCOL_INPUT_INVALID')
  }
}

function summary({
  protocolClass,
  bannerClass = null,
  alpnClass = null,
  statusClass = null,
  allowHeaderPresent = false,
  linkHeaderPresent = false,
  wwwAuthenticateHeaderPresent = false,
}) {
  return Object.freeze({
    protocolClass,
    bannerClass,
    alpnClass,
    statusClass,
    allowHeaderPresent,
    linkHeaderPresent,
    wwwAuthenticateHeaderPresent,
  })
}

function normalizeStageError(error) {
  if (error instanceof LoopbackClassifierError) return error
  return new LoopbackClassifierError('WECHAT_STANDARD_PROTOCOL_NOT_PROVEN')
}

function allocateConnection(context) {
  if (context.connections >= context.input.budgets.maxConnections) {
    fail('WECHAT_STANDARD_PROTOCOL_CONNECTION_BUDGET_EXHAUSTED')
  }
  context.connections += 1
}

function runSocketStage(context, {
  createSocket,
  readyEvent,
  onReady,
  onData,
  onEnd,
  onTimeout,
  onError,
}) {
  allocateConnection(context)

  return new Promise((resolve, reject) => {
    let socket
    let settled = false
    let timer

    const cleanup = () => {
      clearTimeout(timer)
      context.signal.removeEventListener('abort', abort)
      if (socket !== undefined) {
        socket.removeAllListeners()
        socket.on('error', () => undefined)
        socket.destroy()
      }
    }
    const settle = (kind, value) => {
      if (settled) return
      settled = true
      cleanup()
      if (kind === 'reject') reject(normalizeStageError(value))
      else resolve(value)
    }
    const controls = Object.freeze({
      resolve: (value) => settle('resolve', value),
      rejectCode: (code) => settle('reject', new LoopbackClassifierError(code)),
    })
    const guard = (callback, ...args) => {
      if (settled) return
      try {
        callback(...args, controls)
      } catch (error) {
        settle('reject', error)
      }
    }
    const abort = () => controls.rejectCode(context.abortState.code)

    timer = setTimeout(() => guard(onTimeout), context.input.budgets.stageTimeoutMs)
    context.signal.addEventListener('abort', abort, { once: true })
    if (context.signal.aborted) {
      abort()
      return
    }

    try {
      socket = createSocket()
      socket.once(readyEvent, () => guard(onReady, socket))
      socket.on('data', (chunk) => guard(onData, chunk, socket))
      socket.once('end', () => guard(onEnd))
      socket.once('error', (error) => guard(onError, error))
    } catch {
      controls.resolve(null)
    }
  })
}

function isBinaryPrefix(buffer) {
  for (const byte of buffer) {
    if (byte !== 9 && byte !== 10 && byte !== 13 && (byte < 32 || byte > 126)) return true
  }
  return false
}

async function classifyBanner(context) {
  let received = Buffer.alloc(0)
  return runSocketStage(context, {
    createSocket: () => createNetConnection({
      host: context.input.host,
      port: context.input.port,
    }),
    readyEvent: 'connect',
    onReady: () => undefined,
    onData(chunk, _socket, controls) {
      if (!Buffer.isBuffer(chunk)) {
        controls.rejectCode('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
        return
      }
      const newline = chunk.indexOf(10)
      if (newline === -1) {
        if (received.length + chunk.length > context.input.budgets.maxReadBytes) {
          controls.rejectCode('WECHAT_STANDARD_PROTOCOL_RESPONSE_TOO_LARGE')
          return
        }
        if (isBinaryPrefix(chunk)) {
          controls.rejectCode('WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE')
          return
        }
        received = Buffer.concat([received, chunk])
        return
      }

      const boundedLineChunk = chunk.subarray(0, newline + 1)
      if (received.length + boundedLineChunk.length > context.input.budgets.maxReadBytes) {
        controls.rejectCode('WECHAT_STANDARD_PROTOCOL_RESPONSE_TOO_LARGE')
        return
      }
      if (isBinaryPrefix(boundedLineChunk)) {
        controls.rejectCode('WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE')
        return
      }
      const firstLine = Buffer.concat([received, boundedLineChunk]).toString('ascii')
      if (/^SSH-2\.0-[\x21-\x7e]{1,48}\r?\n$/.test(firstLine)) {
        controls.resolve(summary({ protocolClass: 'banner', bannerClass: 'ssh' }))
        return
      }
      controls.resolve(null)
    },
    onEnd(controls) {
      if (received.length === 0) controls.resolve(null)
      else controls.resolve(null)
    },
    onTimeout(controls) {
      controls.resolve(null)
    },
    onError(_error, controls) {
      controls.resolve(null)
    },
  })
}

function parseHttpHead(buffer) {
  const separator = buffer.indexOf(Buffer.from('\r\n\r\n'))
  if (separator === -1) {
    if (isBinaryPrefix(buffer)) fail('WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE')
    return null
  }
  const headerBuffer = buffer.subarray(0, separator)
  if (isBinaryPrefix(headerBuffer)) fail('WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE')

  const headerText = headerBuffer.toString('latin1')
  const lines = headerText.split('\r\n')
  const status = /^HTTP\/1\.[01] ([1-5][0-9]{2})(?: [\x20-\x7e]*)?$/.exec(lines[0])
  if (status === null) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')

  const present = new Set()
  const contentLengths = []
  const transferEncodings = []
  for (const line of lines.slice(1)) {
    const match = /^([!#$%&'*+.^_`|~0-9A-Za-z-]+):([\t\x20-\x7e]*)$/.exec(line)
    if (match === null) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    const name = match[1].toLowerCase()
    const value = match[2].trim()
    present.add(name)
    if (name === 'content-length') contentLengths.push(value)
    if (name === 'transfer-encoding') transferEncodings.push(value)
  }

  return Object.freeze({
    headerEnd: separator + 4,
    statusCode: Number(status[1]),
    contentLengths: Object.freeze(contentLengths),
    transferEncodings: Object.freeze(transferEncodings),
    httpSummary: Object.freeze({
      statusClass: `${status[1][0]}xx`,
      allowHeaderPresent: present.has('allow'),
      linkHeaderPresent: present.has('link'),
      wwwAuthenticateHeaderPresent: present.has('www-authenticate'),
    }),
  })
}

const tokenPunctuation = new Set(Buffer.from("!#$%&'*+-.^_`|~", 'ascii'))

function isHexByte(byte) {
  return (byte >= 48 && byte <= 57)
    || (byte >= 65 && byte <= 70)
    || (byte >= 97 && byte <= 102)
}

function isTokenByte(byte) {
  return (byte >= 48 && byte <= 57)
    || (byte >= 65 && byte <= 90)
    || (byte >= 97 && byte <= 122)
    || tokenPunctuation.has(byte)
}

function isOptionalWhitespace(byte) {
  return byte === 9 || byte === 32
}

function isQuotedTextByte(byte) {
  return byte === 9
    || byte === 32
    || byte === 33
    || (byte >= 35 && byte <= 91)
    || (byte >= 93 && byte <= 126)
}

function parseChunkSizeLine(line) {
  if (isBinaryPrefix(line)) fail('WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE')
  let cursor = 0
  while (cursor < line.length && isHexByte(line[cursor])) cursor += 1
  if (cursor === 0 || cursor > 8) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
  const size = Number.parseInt(line.subarray(0, cursor).toString('latin1'), 16)

  while (cursor < line.length) {
    while (cursor < line.length && isOptionalWhitespace(line[cursor])) cursor += 1
    if (cursor === line.length) break
    if (line[cursor] !== 59) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    cursor += 1
    while (cursor < line.length && isOptionalWhitespace(line[cursor])) cursor += 1

    const nameStart = cursor
    while (cursor < line.length && isTokenByte(line[cursor])) cursor += 1
    if (cursor === nameStart) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    while (cursor < line.length && isOptionalWhitespace(line[cursor])) cursor += 1
    if (cursor === line.length || line[cursor] === 59) continue
    if (line[cursor] !== 61) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    cursor += 1
    while (cursor < line.length && isOptionalWhitespace(line[cursor])) cursor += 1

    if (line[cursor] === 34) {
      cursor += 1
      let closed = false
      while (cursor < line.length) {
        const byte = line[cursor]
        if (byte === 34) {
          cursor += 1
          closed = true
          break
        }
        if (byte === 92) {
          cursor += 1
          if (
            cursor >= line.length
            || !(
              line[cursor] === 9
              || line[cursor] === 32
              || (line[cursor] >= 33 && line[cursor] <= 126)
            )
          ) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
          cursor += 1
          continue
        }
        if (!isQuotedTextByte(byte)) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
        cursor += 1
      }
      if (!closed) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    } else {
      const valueStart = cursor
      while (cursor < line.length && isTokenByte(line[cursor])) cursor += 1
      if (cursor === valueStart) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    }

    while (cursor < line.length && isOptionalWhitespace(line[cursor])) cursor += 1
    if (cursor < line.length && line[cursor] !== 59) {
      fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    }
  }

  return size
}

function parseChunkedBody(buffer, start, maxReadBytes) {
  let cursor = start
  while (true) {
    const sizeLineEnd = buffer.indexOf(Buffer.from('\r\n'), cursor)
    if (sizeLineEnd === -1) return null
    const size = parseChunkSizeLine(buffer.subarray(cursor, sizeLineEnd))
    cursor = sizeLineEnd + 2
    if (cursor + size + 2 > maxReadBytes) {
      fail('WECHAT_STANDARD_PROTOCOL_RESPONSE_TOO_LARGE')
    }

    if (size === 0) {
      if (buffer.length < cursor + 2) return null
      if (buffer[cursor] === 13 && buffer[cursor + 1] === 10) return cursor + 2

      const trailersEnd = buffer.indexOf(Buffer.from('\r\n\r\n'), cursor)
      if (trailersEnd === -1) return null
      const trailerBuffer = buffer.subarray(cursor, trailersEnd)
      if (isBinaryPrefix(trailerBuffer)) fail('WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE')
      const trailerText = trailerBuffer.toString('latin1')
      for (const line of trailerText.split('\r\n')) {
        if (!/^([!#$%&'*+.^_`|~0-9A-Za-z-]+):[\t\x20-\x7e]*$/.test(line)) {
          fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
        }
      }
      return trailersEnd + 4
    }

    if (buffer.length < cursor + size + 2) return null
    if (buffer[cursor + size] !== 13 || buffer[cursor + size + 1] !== 10) {
      fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    }
    cursor += size + 2
  }
}

function parseHttpFrame(buffer, maxReadBytes) {
  const head = parseHttpHead(buffer)
  if (head === null) return null
  if (head.contentLengths.length > 1 || head.transferEncodings.length > 1) {
    fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
  }
  if (head.contentLengths.length === 1 && head.transferEncodings.length === 1) {
    fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
  }

  const noBody = (head.statusCode >= 100 && head.statusCode <= 199)
    || head.statusCode === 204
    || head.statusCode === 304
  let frameEnd

  if (head.transferEncodings.length === 1) {
    if (noBody || head.transferEncodings[0].toLowerCase() !== 'chunked') {
      fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    }
    frameEnd = parseChunkedBody(buffer, head.headerEnd, maxReadBytes)
    if (frameEnd === null) return null
  } else if (head.contentLengths.length === 1) {
    const rawLength = head.contentLengths[0]
    if (!/^(?:0|[1-9][0-9]{0,9})$/.test(rawLength)) {
      fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    }
    const bodyLength = Number(rawLength)
    if (!Number.isSafeInteger(bodyLength) || (noBody && bodyLength !== 0)) {
      fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
    }
    frameEnd = head.headerEnd + bodyLength
    if (frameEnd > maxReadBytes) fail('WECHAT_STANDARD_PROTOCOL_RESPONSE_TOO_LARGE')
    if (buffer.length < frameEnd) return null
  } else if (noBody) {
    frameEnd = head.headerEnd
  } else {
    fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
  }

  return Object.freeze({ frameEnd, httpSummary: head.httpSummary })
}

function inspectExtraResponse(state, maxReadBytes) {
  if (state.received.length === 0) return
  const prefix = Buffer.from('HTTP/1.', 'ascii')
  const compared = Math.min(prefix.length, state.received.length)
  if (!state.received.subarray(0, compared).equals(prefix.subarray(0, compared))) {
    fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
  }
  const second = parseHttpFrame(state.received, maxReadBytes)
  if (second !== null) fail('WECHAT_STANDARD_PROTOCOL_MULTIPLE_RESPONSES')
}

function advanceHttpState(context, state) {
  if (state.httpSummary === null) {
    const frame = parseHttpFrame(state.received, context.input.budgets.maxReadBytes)
    if (frame === null) return
    state.httpSummary = frame.httpSummary
    state.received = Buffer.from(state.received.subarray(frame.frameEnd))
  }
  inspectExtraResponse(state, context.input.budgets.maxReadBytes)
}

function receiveHttpData(context, state, chunk) {
  if (!Buffer.isBuffer(chunk)) fail('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
  if (state.totalBytes + chunk.length > context.input.budgets.maxReadBytes) {
    fail('WECHAT_STANDARD_PROTOCOL_RESPONSE_TOO_LARGE')
  }
  state.totalBytes += chunk.length
  state.received = Buffer.concat([state.received, chunk])
  advanceHttpState(context, state)
}

function resolveFramedSummary(state, controls, protocolClass, alpnClass = null) {
  if (state.httpSummary === null || state.received.length !== 0) return false
  controls.resolve(summary({ protocolClass, alpnClass, ...state.httpSummary }))
  return true
}

function finishHttpStage(state, controls, { protocolClass, alpnClass = null, eof, tlsProven }) {
  if (resolveFramedSummary(state, controls, protocolClass, alpnClass)) return
  if (state.httpSummary !== null || state.totalBytes > 0) {
    controls.rejectCode(eof
      ? 'WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE'
      : 'WECHAT_STANDARD_PROTOCOL_STAGE_TIMEOUT')
    return
  }
  if (tlsProven) {
    controls.resolve(summary({ protocolClass: 'tls', alpnClass }))
    return
  }
  if (eof) controls.resolve(null)
  else controls.rejectCode('WECHAT_STANDARD_PROTOCOL_STAGE_TIMEOUT')
}

async function classifyTls(context) {
  const state = {
    received: Buffer.alloc(0),
    totalBytes: 0,
    requestSent: false,
    tlsProven: false,
    httpSummary: null,
  }
  return runSocketStage(context, {
    createSocket: () => createTlsConnection({
      host: context.input.host,
      port: context.input.port,
      ALPNProtocols: ['http/1.1'],
      // This loopback-only probe identifies TLS framing; it does not authenticate the peer.
      rejectUnauthorized: false,
    }),
    readyEvent: 'secureConnect',
    onReady(socket, controls) {
      state.tlsProven = true
      if (socket.alpnProtocol === false || socket.alpnProtocol === '') {
        controls.resolve(summary({ protocolClass: 'tls' }))
        return
      }
      if (socket.alpnProtocol !== 'http/1.1') {
        controls.rejectCode('WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE')
        return
      }
      if (state.requestSent) {
        controls.rejectCode('WECHAT_STANDARD_PROTOCOL_MULTIPLE_RESPONSES')
        return
      }
      state.requestSent = true
      socket.write(safeRequest)
    },
    onData(chunk) {
      receiveHttpData(context, state, chunk)
    },
    onEnd(controls) {
      if (!state.tlsProven) {
        controls.resolve(null)
        return
      }
      finishHttpStage(state, controls, {
        protocolClass: 'tls',
        alpnClass: state.requestSent ? 'http1' : null,
        eof: true,
        tlsProven: state.tlsProven,
      })
    },
    onTimeout(controls) {
      if (!state.tlsProven) {
        controls.resolve(null)
        return
      }
      finishHttpStage(state, controls, {
        protocolClass: 'tls',
        alpnClass: state.requestSent ? 'http1' : null,
        eof: false,
        tlsProven: state.tlsProven,
      })
    },
    onError(_error, controls) {
      if (!state.tlsProven) {
        controls.resolve(null)
        return
      }
      finishHttpStage(state, controls, {
        protocolClass: 'tls',
        alpnClass: state.requestSent ? 'http1' : null,
        eof: true,
        tlsProven: state.tlsProven,
      })
    },
  })
}

async function classifyHttp(context) {
  const state = {
    received: Buffer.alloc(0),
    totalBytes: 0,
    requestSent: false,
    httpSummary: null,
  }
  return runSocketStage(context, {
    createSocket: () => createNetConnection({
      host: context.input.host,
      port: context.input.port,
    }),
    readyEvent: 'connect',
    onReady(socket, controls) {
      if (state.requestSent) {
        controls.rejectCode('WECHAT_STANDARD_PROTOCOL_MULTIPLE_RESPONSES')
        return
      }
      state.requestSent = true
      socket.write(safeRequest)
    },
    onData(chunk) {
      receiveHttpData(context, state, chunk)
    },
    onEnd(controls) {
      finishHttpStage(state, controls, {
        protocolClass: 'http',
        eof: true,
        tlsProven: false,
      })
    },
    onTimeout(controls) {
      finishHttpStage(state, controls, {
        protocolClass: 'http',
        eof: false,
        tlsProven: false,
      })
    },
    onError(_error, controls) {
      finishHttpStage(state, controls, {
        protocolClass: 'http',
        eof: true,
        tlsProven: false,
      })
    },
  })
}

async function runClassifier(context) {
  const banner = await classifyBanner(context)
  if (banner !== null) return banner

  const tls = await classifyTls(context)
  if (tls !== null) return tls

  const http = await classifyHttp(context)
  if (http !== null) return http

  fail('WECHAT_STANDARD_PROTOCOL_NOT_PROVEN')
}

export async function classifyLoopback(value) {
  const input = sanitizeInput(value)
  if (input.signal?.aborted) fail('WECHAT_STANDARD_PROTOCOL_ABORTED')

  const controller = new AbortController()
  const abortState = { code: 'WECHAT_STANDARD_PROTOCOL_ABORTED' }
  let settleBoundary
  const boundary = new Promise((resolve) => {
    settleBoundary = resolve
  })
  const terminate = (code) => {
    abortState.code = code
    controller.abort()
    settleBoundary({ kind: 'boundary', code })
  }
  const timeout = setTimeout(
    () => terminate('WECHAT_STANDARD_PROTOCOL_TIMEOUT'),
    input.budgets.overallTimeoutMs,
  )
  const abort = () => terminate('WECHAT_STANDARD_PROTOCOL_ABORTED')
  input.signal?.addEventListener('abort', abort, { once: true })
  if (input.signal?.aborted) abort()

  const context = {
    input,
    signal: controller.signal,
    abortState,
    connections: 0,
  }
  const classifierOutcome = Promise.resolve().then(() => runClassifier(context)).then(
    (result) => ({ kind: 'result', result }),
    (error) => ({ kind: 'error', error }),
  )

  let outcome
  try {
    outcome = await Promise.race([classifierOutcome, boundary])
  } finally {
    clearTimeout(timeout)
    input.signal?.removeEventListener('abort', abort)
    if (!controller.signal.aborted) controller.abort()
  }

  if (outcome.kind === 'boundary') fail(outcome.code)
  if (outcome.kind === 'error') throw normalizeStageError(outcome.error)
  return outcome.result
}
