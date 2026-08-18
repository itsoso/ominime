import { spawn, type ChildProcessWithoutNullStreams, type SpawnOptionsWithoutStdio } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

import {
  ChatkimClient,
  ChatkimClientError,
  type ChatkimSpawn,
} from '../src/chatkim/client.ts'

const fixture = fileURLToPath(new URL('./fixtures/chatkim/fake-reader.mjs', import.meta.url))
const executable = Object.freeze({ binaryPath: '/safe/chatkimv2', sha256: 'a'.repeat(64) })

interface TestClient {
  client: ChatkimClient
  spawns: Array<{ file: string, args: readonly string[], options: SpawnOptionsWithoutStdio }>
}

function testClient(mode = 'normal', overrides: { timeoutMs?: number, maxResponseBytes?: number } = {}): TestClient {
  const spawns: TestClient['spawns'] = []
  const spawnProcess: ChatkimSpawn = (file, args, options) => {
    spawns.push({ file, args: [...args], options })
    return spawn(process.execPath, [fixture, ...args], {
      ...options,
      env: { ...options.env, FAKE_CHATKIM_MODE: mode },
      stdio: ['pipe', 'pipe', 'pipe'],
    }) as ChildProcessWithoutNullStreams
  }
  return {
    client: new ChatkimClient({
      executable,
      timeoutMs: overrides.timeoutMs ?? 1_000,
      maxResponseBytes: overrides.maxResponseBytes ?? 8_192,
      home: '/safe/home',
      language: 'C.UTF-8',
      spawnProcess,
    }),
    spawns,
  }
}

describe('bounded chatkim MCP client', () => {
  it('initializes once and returns structured tool content through a minimal child environment', async () => {
    const { client, spawns } = testClient()
    const first = await client.callTool('get_current_user', {})
    const second = await client.callTool('list_conversations', { limit: 2 })

    expect(first).toEqual({ operation: 'get_current_user', arguments: {}, body: 'SYNTHETIC-CHAT-BODY' })
    expect(second).toEqual({ operation: 'list_conversations', arguments: { limit: 2 }, body: 'SYNTHETIC-CHAT-BODY' })
    expect(spawns).toHaveLength(1)
    expect(spawns[0]?.file).toBe('/safe/chatkimv2')
    expect(spawns[0]?.args).toEqual(['mcp'])
    expect(spawns[0]?.options.shell).toBe(false)
    expect(spawns[0]?.options.env).toEqual({ HOME: '/safe/home', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' })
    expect(spawns[0]?.options.env).not.toHaveProperty('CHATKIM_KEY')
    expect(spawns[0]?.options.env).not.toHaveProperty('HTTPS_PROXY')
    await client.dispose()
  })

  it.each([
    ['malformed', 'CHATKIM_PROTOCOL_INVALID'],
    ['wrong-id', 'CHATKIM_PROTOCOL_INVALID'],
    ['unexpected', 'CHATKIM_PROTOCOL_INVALID'],
    ['reader-error', 'CHATKIM_READER_REJECTED'],
    ['exit', 'CHATKIM_PROCESS_EXITED'],
  ])('fails closed for %s without echoing child data', async (mode, code) => {
    const { client } = testClient(mode)
    const error = await client.callTool('get_current_user', {}).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ChatkimClientError)
    expect(error).toMatchObject({ code })
    expect(String(error)).not.toContain('SYNTHETIC')
    await client.dispose()
  })

  it('drains but never exposes child stderr', async () => {
    const { client } = testClient('stderr')
    await expect(client.callTool('get_current_user', {})).resolves.toMatchObject({
      operation: 'get_current_user',
    })
    await client.dispose()
  })

  it('discards a process after a structurally invalid tool result', async () => {
    const { client, spawns } = testClient('unexpected')
    await expect(client.callTool('get_current_user', {})).rejects.toMatchObject({
      code: 'CHATKIM_PROTOCOL_INVALID',
    })
    await expect(client.callTool('get_current_user', {})).rejects.toMatchObject({
      code: 'CHATKIM_PROTOCOL_INVALID',
    })
    expect(spawns).toHaveLength(2)
    await client.dispose()
  })

  it('kills the child when one response exceeds the byte budget', async () => {
    const { client } = testClient('overflow', { maxResponseBytes: 512 })
    await expect(client.callTool('get_current_user', {})).rejects.toMatchObject({
      code: 'CHATKIM_RESPONSE_TOO_LARGE',
    })
    await client.dispose()
  })

  it('kills the child on timeout', async () => {
    const { client } = testClient('hang', { timeoutMs: 30 })
    await expect(client.callTool('get_current_user', {})).rejects.toMatchObject({
      code: 'CHATKIM_TIMEOUT',
    })
    await client.dispose()
  })

  it('kills the child on cancellation and returns a fixed error', async () => {
    const { client } = testClient('hang')
    const controller = new AbortController()
    const pending = client.callTool('get_current_user', {}, controller.signal)
    controller.abort(new Error('SYNTHETIC-PRIVATE-ABORT'))
    const error = await pending.catch((caught: unknown) => caught)
    expect(error).toMatchObject({ code: 'CHATKIM_ABORTED' })
    expect(String(error)).not.toContain('SYNTHETIC')
    await client.dispose()
  })

  it('disposes idempotently and rejects later work', async () => {
    const { client } = testClient()
    await client.callTool('get_current_user', {})
    await Promise.all([client.dispose(), client.dispose()])
    await expect(client.callTool('get_current_user', {})).rejects.toMatchObject({
      code: 'CHATKIM_DISPOSED',
    })
  })
})
