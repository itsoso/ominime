import { access, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { createServer as createNetServer, type Server, type Socket } from 'node:net'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createServer as createTlsServer, type Server as TlsServer, type TLSSocket } from 'node:tls'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { classifyLoopback } from '../scripts/source-owned/loopback-classifier.mjs'
import { generateTestCertificate } from './fixtures/source-owned/generate-test-cert.mjs'

const standardBudgets = Object.freeze({
  stageTimeoutMs: 80,
  overallTimeoutMs: 700,
  maxReadBytes: 1_024,
  maxConnections: 3,
})

type OwnedServer = Readonly<{
  port: number
  sockets: Set<Socket>
  close: () => Promise<void>
}>

const activeServers = new Set<OwnedServer>()

async function listen(server: Server | TlsServer, sockets: Set<Socket>): Promise<OwnedServer> {
  server.on('connection', (socket) => sockets.add(socket))
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', () => {
      server.removeListener('error', reject)
      resolve()
    })
  })
  const address = server.address()
  if (address === null || typeof address === 'string') throw new Error('TEST_LISTENER_INVALID')

  const owned = Object.freeze({
    port: address.port,
    sockets,
    async close() {
      for (const socket of sockets) socket.destroy()
      await new Promise<void>((resolve, reject) => {
        server.close((error) => error === undefined ? resolve() : reject(error))
      })
    },
  })
  activeServers.add(owned)
  return owned
}

async function listenNet(handler: (socket: Socket) => void): Promise<OwnedServer> {
  return listen(createNetServer(handler), new Set())
}

async function listenHttp(
  respond: (socket: Socket, request: Buffer) => void,
): Promise<OwnedServer> {
  return listenNet((socket) => {
    let request = Buffer.alloc(0)
    let classified = false
    let responded = false
    socket.on('data', (chunk) => {
      if (!classified) {
        classified = true
        if (chunk[0] === 22) {
          socket.destroy()
          return
        }
      }
      request = Buffer.concat([request, chunk])
      if (!responded && request.includes(Buffer.from('\r\n\r\n'))) {
        responded = true
        respond(socket, request)
      }
    })
  })
}

async function allAcceptedSocketsClose(server: OwnedServer) {
  await vi.waitFor(() => {
    expect(server.sockets.size).toBeGreaterThan(0)
    expect([...server.sockets].every((socket) => socket.destroyed)).toBe(true)
  }, { timeout: 1_000 })
}

function frozenInput(port: number, overrides: Record<string, unknown> = {}) {
  return Object.freeze({
    host: '127.0.0.1',
    port,
    budgets: standardBudgets,
    signal: undefined,
    ...overrides,
  })
}

async function expectFixedError(
  action: Promise<unknown>,
  code: string,
  privateValues: readonly string[] = [],
) {
  let thrown: any
  try {
    await action
  } catch (error) {
    thrown = error
  }

  expect(thrown).toMatchObject({
    name: 'LoopbackClassifierError',
    code,
    message: code,
  })
  const serialized = JSON.stringify(thrown)
  for (const value of privateValues) expect(serialized).not.toContain(value)
}

afterEach(async () => {
  vi.unstubAllEnvs()
  const servers = [...activeServers]
  activeServers.clear()
  await Promise.all(servers.map((server) => server.close()))
})

describe('bounded standard-protocol classifier', () => {
  it('classifies only an allowlisted bounded server-first banner and freezes the summary', async () => {
    const privateBanner = 'SSH-2.0-private-product-and-version\r\n'
    const server = await listenNet((socket) => socket.end(privateBanner))

    const result = await classifyLoopback(frozenInput(server.port))

    expect(result).toEqual({
      protocolClass: 'banner',
      bannerClass: 'ssh',
      alpnClass: null,
      statusClass: null,
      allowHeaderPresent: false,
      linkHeaderPresent: false,
      wwwAuthenticateHeaderPresent: false,
    })
    expect(Object.keys(result)).toEqual([
      'protocolClass',
      'bannerClass',
      'alpnClass',
      'statusClass',
      'allowHeaderPresent',
      'linkHeaderPresent',
      'wwwAuthenticateHeaderPresent',
    ])
    expect(Object.isFrozen(result)).toBe(true)
    expect(JSON.stringify(result)).not.toContain(privateBanner.trim())
    await allAcceptedSocketsClose(server)
  })

  it('classifies a valid bounded SSH first line before ignoring a binary tail', async () => {
    const server = await listenNet((socket) => socket.end(Buffer.concat([
      Buffer.from('SSH-2.0-synthetic\r\n', 'ascii'),
      Buffer.from([0, 255, 16, 128]),
    ])))

    await expect(classifyLoopback(frozenInput(server.port))).resolves.toMatchObject({
      protocolClass: 'banner',
      bannerClass: 'ssh',
    })
    expect(server.sockets.size).toBe(1)
    await allAcceptedSocketsClose(server)
  })

  it('still rejects binary bytes inside the bounded SSH first line', async () => {
    const server = await listenNet((socket) => socket.end(Buffer.concat([
      Buffer.from('SSH-2.0-synth', 'ascii'),
      Buffer.from([0]),
      Buffer.from('etic\r\n', 'ascii'),
    ])))

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE',
    )
    await allAcceptedSocketsClose(server)
  })

  it('defensively snapshots ordinary mutable input and budget records before opening a socket', async () => {
    const server = await listenNet((socket) => socket.end('SSH-2.0-synthetic\r\n'))
    const budgets = {
      stageTimeoutMs: 80,
      overallTimeoutMs: 700,
      maxReadBytes: 1_024,
      maxConnections: 3,
    }
    const input = {
      host: '127.0.0.1',
      port: server.port,
      budgets,
    }

    const action = classifyLoopback(input)
    input.host = '192.0.2.50'
    input.port = 1
    budgets.stageTimeoutMs = 2_000
    budgets.overallTimeoutMs = 10_000
    budgets.maxReadBytes = 16_384
    budgets.maxConnections = 1

    await expect(action).resolves.toMatchObject({
      protocolClass: 'banner',
      bannerClass: 'ssh',
    })
    expect(server.sockets.size).toBe(1)
    await allAcceptedSocketsClose(server)
  })

  it('classifies TLS with a fixed ALPN class and sends OPTIONS star on that same TLS socket', async () => {
    const certificate = await generateTestCertificate()
    try {
      vi.stubEnv('NODE_ENV', 'production')
      const received: Buffer[] = []
      const secureSockets = new Set<TLSSocket>()
      const tlsServer = createTlsServer({
        key: certificate.key,
        cert: certificate.cert,
        ALPNProtocols: ['http/1.1'],
      }, (socket) => {
        secureSockets.add(socket)
        socket.on('data', (chunk) => {
          received.push(chunk)
          if (Buffer.concat(received).includes(Buffer.from('\r\n\r\n'))) {
            socket.end([
              'HTTP/1.1 204 No Content',
              'Allow: OPTIONS, GET',
              'Link: <private-link-value>',
              'WWW-Authenticate: Private private-auth-value',
              'Connection: close',
              '',
              '',
            ].join('\r\n'))
          }
        })
      })
      tlsServer.on('tlsClientError', () => undefined)
      const server = await listen(tlsServer, new Set())
      const result = await classifyLoopback(frozenInput(server.port))

      expect(result).toEqual({
        protocolClass: 'tls',
        bannerClass: null,
        alpnClass: 'http1',
        statusClass: '2xx',
        allowHeaderPresent: true,
        linkHeaderPresent: true,
        wwwAuthenticateHeaderPresent: true,
      })
      expect(secureSockets.size).toBe(1)
      const request = Buffer.concat(received).toString('ascii')
      expect(request).toMatch(/^OPTIONS \* HTTP\/1\.1\r\n/)
      expect(request).not.toContain('/api/')
      expect(request.endsWith('\r\n\r\n')).toBe(true)
      expect(request.slice(request.indexOf('\r\n\r\n') + 4)).toBe('')
      expect(JSON.stringify(result)).not.toContain('synthetic-loopback.invalid')
      expect(JSON.stringify(result)).not.toContain('BEGIN CERTIFICATE')
      expect(JSON.stringify(result)).not.toContain('private-link-value')
      expect(JSON.stringify(result)).not.toContain('private-auth-value')
      await allAcceptedSocketsClose(server)
    } finally {
      await certificate.cleanup()
    }
  })

  it('classifies a production self-signed TLS listener without claiming peer identity', async () => {
    const certificate = await generateTestCertificate()
    try {
      vi.stubEnv('NODE_ENV', 'production')
      const tlsServer = createTlsServer(
        { key: certificate.key, cert: certificate.cert },
        () => undefined,
      )
      tlsServer.on('tlsClientError', () => undefined)
      const server = await listen(tlsServer, new Set())
      const result = await classifyLoopback(frozenInput(server.port))

      expect(result).toEqual({
        protocolClass: 'tls',
        bannerClass: null,
        alpnClass: null,
        statusClass: null,
        allowHeaderPresent: false,
        linkHeaderPresent: false,
        wwwAuthenticateHeaderPresent: false,
      })
      await allAcceptedSocketsClose(server)
    } finally {
      await certificate.cleanup()
    }
  })

  it('keeps TLS plus HTTP ALPN proof when the optional OPTIONS response stays silent', async () => {
    const certificate = await generateTestCertificate()
    try {
      vi.stubEnv('NODE_ENV', 'production')
      const received: Buffer[] = []
      const tlsServer = createTlsServer({
        key: certificate.key,
        cert: certificate.cert,
        ALPNProtocols: ['http/1.1'],
      }, (socket) => socket.on('data', (chunk) => received.push(chunk)))
      tlsServer.on('tlsClientError', () => undefined)
      const server = await listen(tlsServer, new Set())

      const result = await classifyLoopback(frozenInput(server.port))

      expect(result).toEqual({
        protocolClass: 'tls',
        bannerClass: null,
        alpnClass: 'http1',
        statusClass: null,
        allowHeaderPresent: false,
        linkHeaderPresent: false,
        wwwAuthenticateHeaderPresent: false,
      })
      expect(Buffer.concat(received).toString('ascii')).toMatch(/^OPTIONS \* HTTP\/1\.1\r\n/)
      expect(JSON.stringify(result)).not.toContain('authorized')
      expect(JSON.stringify(result)).not.toContain('certificate')
      await allAcceptedSocketsClose(server)
    } finally {
      await certificate.cleanup()
    }
  })

  it('sends exactly one safe OPTIONS star request to a synthetic plain HTTP listener', async () => {
    const received: Buffer[] = []
    let responseSent = false
    const server = await listenNet((socket) => {
      let classifiedConnection = false
      socket.on('data', (chunk) => {
        if (!classifiedConnection) {
          classifiedConnection = true
          if (!chunk.toString('ascii').startsWith('OPTIONS ')) {
            socket.destroy()
            return
          }
        }
        received.push(chunk)
        const request = Buffer.concat(received)
        if (!responseSent && request.includes(Buffer.from('\r\n\r\n'))) {
          responseSent = true
          socket.end([
            'HTTP/1.1 401 Unauthorized',
            'Allow: private-allow-value',
            'Link: private-link-value',
            'WWW-Authenticate: private-auth-value',
            'X-Private: private-header-value',
            'Content-Length: 18',
            'Connection: close',
            '',
            'private-body-value',
          ].join('\r\n'))
        }
      })
    })

    const result = await classifyLoopback(frozenInput(server.port))

    const request = Buffer.concat(received).toString('ascii')
    expect(request).toMatch(/^OPTIONS \* HTTP\/1\.1\r\n/)
    expect(request).not.toContain('/api/')
    expect(request.endsWith('\r\n\r\n')).toBe(true)
    expect(request.slice(request.indexOf('\r\n\r\n') + 4)).toBe('')
    expect(result).toEqual({
      protocolClass: 'http',
      bannerClass: null,
      alpnClass: null,
      statusClass: '4xx',
      allowHeaderPresent: true,
      linkHeaderPresent: true,
      wwwAuthenticateHeaderPresent: true,
    })
    const serialized = JSON.stringify(result)
    for (const value of [
      'private-allow-value',
      'private-link-value',
      'private-auth-value',
      'private-header-value',
      'private-body-value',
    ]) expect(serialized).not.toContain(value)
    expect(server.sockets.size).toBe(3)
    await allAcceptedSocketsClose(server)
  })

  it('returns a framed 204 keep-alive response without waiting for EOF', async () => {
    const server = await listenHttp((socket) => socket.write([
      'HTTP/1.1 204 No Content',
      'Allow: OPTIONS',
      'Connection: keep-alive',
      '',
      '',
    ].join('\r\n')))

    await expect(classifyLoopback(frozenInput(server.port))).resolves.toMatchObject({
      protocolClass: 'http',
      statusClass: '2xx',
      allowHeaderPresent: true,
    })
    await allAcceptedSocketsClose(server)
  })

  it('incrementally frames a response header split across socket writes', async () => {
    const server = await listenHttp((socket) => {
      socket.write('HTTP/1.1 204 No Content\r\nAll')
      setTimeout(() => socket.write('ow: OPTIONS\r\nConnection: keep-alive\r\n\r\n'), 5)
    })

    await expect(classifyLoopback(frozenInput(server.port))).resolves.toMatchObject({
      protocolClass: 'http',
      statusClass: '2xx',
      allowHeaderPresent: true,
    })
    await allAcceptedSocketsClose(server)
  })

  it('treats a status-looking line inside a bounded Content-Length body only as body', async () => {
    const body = 'first\r\nHTTP/1.1 500 private-body-line\r\nlast'
    const server = await listenHttp((socket) => socket.end([
      'HTTP/1.1 200 OK',
      `Content-Length: ${Buffer.byteLength(body)}`,
      'Connection: close',
      '',
      body,
    ].join('\r\n')))

    await expect(classifyLoopback(frozenInput(server.port))).resolves.toMatchObject({
      protocolClass: 'http',
      statusClass: '2xx',
    })
    await allAcceptedSocketsClose(server)
  })

  it('completes a bounded Content-Length body while the connection stays open', async () => {
    const server = await listenHttp((socket) => {
      socket.write('HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: keep-alive\r\n\r\nabc')
      setTimeout(() => socket.write('def'), 5)
    })

    await expect(classifyLoopback(frozenInput(server.port))).resolves.toMatchObject({
      protocolClass: 'http',
      statusClass: '2xx',
    })
    await allAcceptedSocketsClose(server)
  })

  it('completes a split bounded chunked body and trailer while the connection stays open', async () => {
    const server = await listenHttp((socket) => {
      socket.write([
        'HTTP/1.1 200 OK',
        'Transfer-Encoding: chunked',
        'Connection: keep-alive',
        '',
        '4',
        'Wi',
      ].join('\r\n'))
      setTimeout(() => socket.write('ki\r\n0\r\nX-Synthetic: trailer\r\n\r\n'), 5)
    })

    await expect(classifyLoopback(frozenInput(server.port))).resolves.toMatchObject({
      protocolClass: 'http',
      statusClass: '2xx',
    })
    await allAcceptedSocketsClose(server)
  })

  it('accepts bounded standard token and quoted chunk extensions', async () => {
    const server = await listenHttp((socket) => socket.end([
      'HTTP/1.1 200 OK',
      'Transfer-Encoding: chunked',
      'Connection: close',
      '',
      '4;foo=bar;quoted="safe value"',
      'Wiki',
      '0',
      '',
      '',
    ].join('\r\n')))

    await expect(classifyLoopback(frozenInput(server.port))).resolves.toMatchObject({
      protocolClass: 'http',
      statusClass: '2xx',
    })
    await allAcceptedSocketsClose(server)
  })

  it('rejects a high-bit chunk-size byte instead of lossy ASCII aliasing it', async () => {
    const server = await listenHttp((socket) => socket.end(Buffer.concat([
      Buffer.from('HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n', 'ascii'),
      Buffer.from([0xb1]),
      Buffer.from('\r\na\r\n0\r\n\r\n', 'ascii'),
    ])))

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE',
    )
    await allAcceptedSocketsClose(server)
  })

  it('rejects high-bit trailer metadata before any text decoding', async () => {
    const server = await listenHttp((socket) => socket.end(Buffer.concat([
      Buffer.from('HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n', 'ascii'),
      Buffer.from([0xd8]),
      Buffer.from('-Synthetic: safe\r\n\r\n', 'ascii'),
    ])))

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE',
    )
    await allAcceptedSocketsClose(server)
  })

  it('rejects a second framed response split across writes during the bounded guard', async () => {
    const privateValue = 'private-split-second-response'
    const server = await listenHttp((socket) => {
      socket.write('HTTP/1.1 204 No Content\r\nConnection: keep-alive\r\n\r\n')
      setTimeout(() => socket.write(
        `HTTP/1.1 500 ${privateValue}\r\nContent-Length: 0\r\n\r\n`,
      ), 5)
    })

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_MULTIPLE_RESPONSES',
      [privateValue],
    )
    await allAcceptedSocketsClose(server)
  })

  it.each([
    [
      'conflicting Content-Length fields',
      'HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\na',
      'WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE',
    ],
    [
      'Content-Length plus chunked framing',
      'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n',
      'WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE',
    ],
    [
      'malformed chunk size',
      'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\nnot-hex\r\n',
      'WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE',
    ],
    [
      'declared body beyond the total byte budget',
      'HTTP/1.1 200 OK\r\nContent-Length: 2000\r\n\r\n',
      'WECHAT_STANDARD_PROTOCOL_RESPONSE_TOO_LARGE',
    ],
  ])('rejects %s with a fixed framing code', async (_name, response, code) => {
    const server = await listenHttp((socket) => socket.end(response))

    await expectFixedError(classifyLoopback(frozenInput(server.port)), code, [response])
    await allAcceptedSocketsClose(server)
  })

  it.each([
    ['non-loopback host', { host: '192.0.2.10' }],
    ['zero port', { port: 0 }],
    ['unsafe port', { port: 65_536 }],
    ['unknown input key', { endpoint: 'private-endpoint' }],
    ['unknown budget key', { budgets: Object.freeze({ ...standardBudgets, retries: 1 }) }],
    ['unsafe byte budget', { budgets: Object.freeze({ ...standardBudgets, maxReadBytes: 1_000_000 }) }],
  ])('rejects %s with one fixed non-reflective input code', async (_name, overrides) => {
    const privateValue = JSON.stringify(overrides)
    await expectFixedError(
      classifyLoopback(frozenInput(1, overrides)),
      'WECHAT_STANDARD_PROTOCOL_INPUT_INVALID',
      [privateValue, 'private-endpoint', 'private-certificate'],
    )
  })

  it('rejects the removed arbitrary test CA seam before opening a socket', async () => {
    const server = await listenNet((socket) => socket.end('SSH-2.0-synthetic\r\n'))
    const privateCertificate = [
      '-----BEGIN CERTIFICATE-----',
      'private-certificate-value',
      '-----END CERTIFICATE-----',
      '',
    ].join('\n')

    await expectFixedError(
      classifyLoopback(frozenInput(server.port, { testOnlyTlsCa: privateCertificate })),
      'WECHAT_STANDARD_PROTOCOL_INPUT_INVALID',
      [privateCertificate],
    )
    expect(server.sockets.size).toBe(0)
  })

  it('rejects binary server-first data with a fixed code and closes the socket', async () => {
    const server = await listenNet((socket) => socket.end(Buffer.from([0, 255, 16, 128])))

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_BINARY_RESPONSE',
    )
    await allAcceptedSocketsClose(server)
  })

  it('rejects an oversized response with a fixed code and closes the socket', async () => {
    const privateValue = 'x'.repeat(1_025)
    const server = await listenNet((socket) => socket.end(privateValue))

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_RESPONSE_TOO_LARGE',
      [privateValue],
    )
    await allAcceptedSocketsClose(server)
  })

  it('reports a fixed stage timeout for a silent listener and closes every connection', async () => {
    const server = await listenNet((socket) => socket.on('data', () => undefined))

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_STAGE_TIMEOUT',
    )
    expect(server.sockets.size).toBe(3)
    await allAcceptedSocketsClose(server)
  })

  it('enforces an independent fixed overall timeout and closes the active socket', async () => {
    const server = await listenNet(() => undefined)
    const budgets = Object.freeze({
      ...standardBudgets,
      stageTimeoutMs: 200,
      overallTimeoutMs: 30,
    })

    await expectFixedError(
      classifyLoopback(frozenInput(server.port, { budgets })),
      'WECHAT_STANDARD_PROTOCOL_TIMEOUT',
    )
    await allAcceptedSocketsClose(server)
  })

  it('settles independently on cancellation and closes the active socket', async () => {
    const server = await listenNet(() => undefined)
    const controller = new AbortController()
    const action = classifyLoopback(frozenInput(server.port, { signal: controller.signal }))

    await vi.waitFor(() => expect(server.sockets.size).toBe(1))
    controller.abort(new Error('private abort reason'))

    await expectFixedError(action, 'WECHAT_STANDARD_PROTOCOL_ABORTED', ['private abort reason'])
    await allAcceptedSocketsClose(server)
  })

  it('enforces the connection budget before a third stage and never retries', async () => {
    const server = await listenNet((socket) => socket.on('data', () => socket.end()))
    const budgets = Object.freeze({ ...standardBudgets, maxConnections: 2 })

    await expectFixedError(
      classifyLoopback(frozenInput(server.port, { budgets })),
      'WECHAT_STANDARD_PROTOCOL_CONNECTION_BUDGET_EXHAUSTED',
    )
    expect(server.sockets.size).toBe(2)
    await allAcceptedSocketsClose(server)
  })

  it('uses each of the three stages once and returns NOT PROVEN without retries', async () => {
    const server = await listenNet((socket) => socket.on('data', () => socket.end()))

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_NOT_PROVEN',
    )
    expect(server.sockets.size).toBe(3)
    await allAcceptedSocketsClose(server)
  })

  it('rejects malformed HTTP without reflecting response bytes', async () => {
    const privateValue = 'private malformed header value'
    const server = await listenNet((socket) => {
      socket.on('data', (chunk) => {
        if (chunk[0] === 22) socket.destroy()
        else if (chunk.toString('ascii').startsWith('OPTIONS ')) {
          socket.end(`HTTP/1.1 200 OK\r\n${privateValue}\r\n\r\n`)
        }
      })
    })

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_MALFORMED_RESPONSE',
      [privateValue],
    )
    await allAcceptedSocketsClose(server)
  })

  it('rejects multiple HTTP response attempts with a fixed code', async () => {
    const privateValue = 'private second response'
    const server = await listenNet((socket) => {
      socket.on('data', (chunk) => {
        if (chunk[0] === 22) socket.destroy()
        else if (chunk.toString('ascii').startsWith('OPTIONS ')) {
          socket.end([
            'HTTP/1.1 204 No Content\r\nConnection: keep-alive\r\n\r\n',
            `HTTP/1.1 500 ${privateValue}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n`,
          ].join(''))
        }
      })
    })

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_MULTIPLE_RESPONSES',
      [privateValue],
    )
    await allAcceptedSocketsClose(server)
  })

  it('does not reflect reset system errors and still spends no more than three attempts', async () => {
    const server = await listenNet((socket) => socket.destroy())

    await expectFixedError(
      classifyLoopback(frozenInput(server.port)),
      'WECHAT_STANDARD_PROTOCOL_NOT_PROVEN',
      [String(server.port), 'ECONNRESET', 'EPIPE'],
    )
    expect(server.sockets.size).toBe(3)
    await allAcceptedSocketsClose(server)
  })

  it('bounds certificate generation and removes its temporary directory after runner failure', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'ominime-loopback-cert-regression-'))
    const privateFailure = new Error('private openssl failure')
    const runner = vi.fn(async (_file: string, _args: string[], options: object) => {
      expect(options).toMatchObject({
        encoding: 'utf8',
        maxBuffer: 16_384,
        timeout: 5_000,
        killSignal: 'SIGKILL',
      })
      throw privateFailure
    })
    const removeTemporaryDirectory = vi.fn(async (target: string, options: object) => {
      await rm(target, options)
    })
    let outcome: any

    try {
      try {
        outcome = await generateTestCertificate({
          runner,
          makeTemporaryDirectory: async () => directory,
          removeTemporaryDirectory,
        })
      } catch (error) {
        outcome = error
      }

      expect(outcome).toBe(privateFailure)
      expect(runner).toHaveBeenCalledTimes(1)
      expect(removeTemporaryDirectory).toHaveBeenCalledWith(
        directory,
        { recursive: true, force: true },
      )
      await expect(access(directory)).rejects.toMatchObject({ code: 'ENOENT' })
    } finally {
      if (typeof outcome?.cleanup === 'function') await outcome.cleanup()
      await rm(directory, { recursive: true, force: true })
    }
  })

  it('retries a failed certificate cleanup and shares one in-flight successful removal', async () => {
    const directory = await mkdtemp(join(tmpdir(), 'ominime-loopback-cert-retry-'))
    const privateFailure = new Error('private first cleanup failure')
    const runner = vi.fn(async (_file: string, args: string[]) => {
      const keyPath = args[args.indexOf('-keyout') + 1]
      const certPath = args[args.indexOf('-out') + 1]
      await Promise.all([
        writeFile(keyPath, 'synthetic-key-material', 'utf8'),
        writeFile(certPath, 'synthetic-cert-material', 'utf8'),
      ])
    })
    let removalAttempts = 0
    let releaseRetry = () => undefined
    const retryGate = new Promise<void>((resolve) => { releaseRetry = resolve })
    const removeTemporaryDirectory = vi.fn(async (target: string, options: object) => {
      removalAttempts += 1
      if (removalAttempts === 1) throw privateFailure
      await retryGate
      await rm(target, options)
    })
    const generated = await generateTestCertificate({
      runner,
      makeTemporaryDirectory: async () => directory,
      removeTemporaryDirectory,
    })
    let retries: Promise<unknown>[] = []

    try {
      await expect(generated.cleanup()).rejects.toBe(privateFailure)
      await expect(access(directory)).resolves.toBeUndefined()

      retries = [generated.cleanup(), generated.cleanup()]
      await vi.waitFor(() => expect(removeTemporaryDirectory).toHaveBeenCalledTimes(2), {
        timeout: 250,
      })
      releaseRetry()
      await Promise.all(retries)

      await expect(access(directory)).rejects.toMatchObject({ code: 'ENOENT' })
      await generated.cleanup()
      expect(removeTemporaryDirectory).toHaveBeenCalledTimes(2)
    } finally {
      releaseRetry()
      await Promise.allSettled(retries)
      await rm(directory, { recursive: true, force: true })
    }
  })
})
