import {
  spawn,
  type ChildProcessWithoutNullStreams,
  type SpawnOptionsWithoutStdio,
} from 'node:child_process'

import type { ResolvedChatkimExecutable } from './config.ts'

export type ChatkimReaderTool =
  | 'get_current_user'
  | 'list_conversations'
  | 'query_chat_log'
  | 'get_message_context'

export type ChatkimClientErrorCode =
  | 'CHATKIM_ABORTED'
  | 'CHATKIM_DISPOSED'
  | 'CHATKIM_PROCESS_START_FAILED'
  | 'CHATKIM_PROCESS_EXITED'
  | 'CHATKIM_PROTOCOL_INVALID'
  | 'CHATKIM_READER_REJECTED'
  | 'CHATKIM_RESPONSE_TOO_LARGE'
  | 'CHATKIM_TIMEOUT'

export class ChatkimClientError extends Error {
  declare readonly code: ChatkimClientErrorCode

  constructor(code: ChatkimClientErrorCode) {
    super('Kim chat reader request failed')
    this.name = 'ChatkimClientError'
    Object.defineProperty(this, 'code', { enumerable: true, value: code })
  }
}

export type ChatkimSpawn = (
  file: string,
  args: readonly string[],
  options: SpawnOptionsWithoutStdio,
) => ChildProcessWithoutNullStreams

export interface ChatkimClientOptions {
  readonly executable: Readonly<ResolvedChatkimExecutable>
  readonly home: string
  readonly language?: string
  readonly timeoutMs?: number
  readonly maxResponseBytes?: number
  readonly spawnProcess?: ChatkimSpawn
}

interface PendingRequest {
  readonly id: number
  readonly resolve: (value: unknown) => void
  readonly reject: (error: ChatkimClientError) => void
  readonly timer: ReturnType<typeof setTimeout>
  readonly signal: AbortSignal | undefined
  readonly abort: (() => void) | undefined
}

interface ReaderSession {
  readonly child: ChildProcessWithoutNullStreams
  buffer: Buffer
  stderrBytes: number
  pending: PendingRequest | undefined
  initialized: boolean
  closing: boolean
}

const DEFAULT_TIMEOUT_MS = 5_000
const DEFAULT_MAX_RESPONSE_BYTES = 1_048_576

function defaultSpawn(
  file: string,
  args: readonly string[],
  options: SpawnOptionsWithoutStdio,
): ChildProcessWithoutNullStreams {
  return spawn(file, args, {
    ...options,
    stdio: ['pipe', 'pipe', 'pipe'],
  })
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function clearPending(pending: PendingRequest): void {
  clearTimeout(pending.timer)
  if (pending.signal !== undefined && pending.abort !== undefined) {
    pending.signal.removeEventListener('abort', pending.abort)
  }
}

export class ChatkimClient {
  private readonly executable: Readonly<ResolvedChatkimExecutable>
  private readonly home: string
  private readonly language: string
  private readonly timeoutMs: number
  private readonly maxResponseBytes: number
  private readonly spawnProcess: ChatkimSpawn
  private session: ReaderSession | undefined
  private sequence = 0
  private queue: Promise<void> = Promise.resolve()
  private disposed = false
  private disposal: Promise<void> | undefined

  constructor(options: ChatkimClientOptions) {
    this.executable = options.executable
    this.home = options.home
    this.language = options.language ?? 'C.UTF-8'
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
    this.maxResponseBytes = options.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES
    this.spawnProcess = options.spawnProcess ?? defaultSpawn
  }

  callTool(
    name: ChatkimReaderTool,
    argumentsValue: Readonly<Record<string, unknown>>,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (this.disposed) return Promise.reject(new ChatkimClientError('CHATKIM_DISPOSED'))
    const operation = this.queue.then(async () => {
      if (this.disposed) throw new ChatkimClientError('CHATKIM_DISPOSED')
      if (signal?.aborted === true) throw new ChatkimClientError('CHATKIM_ABORTED')
      const session = this.ensureSession()
      await this.initialize(session, signal)
      const response = await this.request(session, 'tools/call', {
        name,
        arguments: argumentsValue,
      }, signal)
      return this.projectToolResult(session, response)
    })
    this.queue = operation.then(() => undefined, () => undefined)
    return operation
  }

  dispose(): Promise<void> {
    if (this.disposal !== undefined) return this.disposal
    this.disposed = true
    this.disposal = this.closeSession()
    return this.disposal
  }

  private ensureSession(): ReaderSession {
    if (this.session !== undefined) return this.session
    let child: ChildProcessWithoutNullStreams
    try {
      child = this.spawnProcess(this.executable.binaryPath, ['mcp'], {
        shell: false,
        windowsHide: true,
        env: {
          HOME: this.home,
          LANG: this.language,
          LC_ALL: this.language,
        },
      })
    } catch {
      throw new ChatkimClientError('CHATKIM_PROCESS_START_FAILED')
    }
    const session: ReaderSession = {
      child,
      buffer: Buffer.alloc(0),
      stderrBytes: 0,
      pending: undefined,
      initialized: false,
      closing: false,
    }
    this.session = session
    child.stdout.on('data', (chunk: Buffer) => { this.receive(session, chunk) })
    child.stderr.on('data', (chunk: Buffer) => { this.receiveStderr(session, chunk) })
    child.once('error', () => {
      this.failSession(session, new ChatkimClientError('CHATKIM_PROCESS_START_FAILED'))
    })
    child.once('exit', () => {
      this.failSession(session, new ChatkimClientError('CHATKIM_PROCESS_EXITED'), false)
    })
    return session
  }

  private async initialize(session: ReaderSession, signal?: AbortSignal): Promise<void> {
    if (session.initialized) return
    const response = await this.request(session, 'initialize', {
      protocolVersion: '2025-11-25',
      capabilities: {},
      clientInfo: { name: 'ominime-personal-context', version: '0.1.0' },
    }, signal)
    if (!isRecord(response)
      || typeof response.protocolVersion !== 'string'
      || !isRecord(response.serverInfo)) {
      this.failSession(session, new ChatkimClientError('CHATKIM_PROTOCOL_INVALID'))
      throw new ChatkimClientError('CHATKIM_PROTOCOL_INVALID')
    }
    session.child.stdin.write(`${JSON.stringify({
      jsonrpc: '2.0',
      method: 'notifications/initialized',
      params: {},
    })}\n`)
    session.initialized = true
  }

  private request(
    session: ReaderSession,
    method: string,
    params: Readonly<Record<string, unknown>>,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (signal?.aborted === true) {
      this.failSession(session, new ChatkimClientError('CHATKIM_ABORTED'))
      return Promise.reject(new ChatkimClientError('CHATKIM_ABORTED'))
    }
    if (session.pending !== undefined) {
      this.failSession(session, new ChatkimClientError('CHATKIM_PROTOCOL_INVALID'))
      return Promise.reject(new ChatkimClientError('CHATKIM_PROTOCOL_INVALID'))
    }
    const id = ++this.sequence
    return new Promise<unknown>((resolve, reject) => {
      const timer = setTimeout(() => {
        this.failSession(session, new ChatkimClientError('CHATKIM_TIMEOUT'))
      }, this.timeoutMs)
      const abort = signal === undefined
        ? undefined
        : () => { this.failSession(session, new ChatkimClientError('CHATKIM_ABORTED')) }
      const pending: PendingRequest = { id, resolve, reject, timer, signal, abort }
      session.pending = pending
      if (abort !== undefined) signal!.addEventListener('abort', abort, { once: true })
      session.child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`, error => {
        if (error !== null && error !== undefined) {
          this.failSession(session, new ChatkimClientError('CHATKIM_PROCESS_EXITED'))
        }
      })
    })
  }

  private receive(session: ReaderSession, chunk: Buffer): void {
    if (session.closing || this.session !== session) return
    session.buffer = Buffer.concat([session.buffer, chunk])
    if (session.buffer.length > this.maxResponseBytes) {
      this.failSession(session, new ChatkimClientError('CHATKIM_RESPONSE_TOO_LARGE'))
      return
    }
    let newline = session.buffer.indexOf(0x0a)
    while (newline >= 0) {
      const line = session.buffer.subarray(0, newline)
      session.buffer = session.buffer.subarray(newline + 1)
      if (line.length > 0) this.receiveLine(session, line)
      if (session.closing || this.session !== session) return
      newline = session.buffer.indexOf(0x0a)
    }
  }

  private receiveLine(session: ReaderSession, line: Buffer): void {
    const pending = session.pending
    if (pending === undefined) {
      this.failSession(session, new ChatkimClientError('CHATKIM_PROTOCOL_INVALID'))
      return
    }
    let response: unknown
    try {
      response = JSON.parse(line.toString('utf8'))
    } catch {
      this.failSession(session, new ChatkimClientError('CHATKIM_PROTOCOL_INVALID'))
      return
    }
    if (!isRecord(response) || response.jsonrpc !== '2.0' || response.id !== pending.id) {
      this.failSession(session, new ChatkimClientError('CHATKIM_PROTOCOL_INVALID'))
      return
    }
    session.pending = undefined
    clearPending(pending)
    if ('error' in response || !('result' in response)) {
      pending.reject(new ChatkimClientError('CHATKIM_READER_REJECTED'))
      return
    }
    pending.resolve(response.result)
  }

  private receiveStderr(session: ReaderSession, chunk: Buffer): void {
    if (session.closing || this.session !== session) return
    session.stderrBytes += chunk.length
    if (session.stderrBytes > this.maxResponseBytes) {
      this.failSession(session, new ChatkimClientError('CHATKIM_RESPONSE_TOO_LARGE'))
    }
  }

  private projectToolResult(session: ReaderSession, value: unknown): unknown {
    if (!isRecord(value) || typeof value.isError !== 'boolean' || !('structuredContent' in value)) {
      const error = new ChatkimClientError('CHATKIM_PROTOCOL_INVALID')
      this.failSession(session, error)
      throw error
    }
    if (value.isError) throw new ChatkimClientError('CHATKIM_READER_REJECTED')
    return value.structuredContent
  }

  private failSession(
    session: ReaderSession,
    error: ChatkimClientError,
    kill = true,
  ): void {
    if (session.closing) return
    session.closing = true
    if (this.session === session) this.session = undefined
    const pending = session.pending
    session.pending = undefined
    if (pending !== undefined) {
      clearPending(pending)
      pending.reject(error)
    }
    session.child.stdin.destroy()
    if (kill && session.child.exitCode === null) session.child.kill('SIGTERM')
  }

  private async closeSession(): Promise<void> {
    const session = this.session
    if (session === undefined) return
    this.session = undefined
    const pending = session.pending
    session.pending = undefined
    session.closing = true
    if (pending !== undefined) {
      clearPending(pending)
      pending.reject(new ChatkimClientError('CHATKIM_DISPOSED'))
    }
    session.child.stdin.destroy()
    if (session.child.exitCode !== null) return
    await new Promise<void>(resolve => {
      const force = setTimeout(() => {
        if (session.child.exitCode === null) session.child.kill('SIGKILL')
      }, 100)
      session.child.once('exit', () => {
        clearTimeout(force)
        resolve()
      })
      session.child.kill('SIGTERM')
    })
  }
}
