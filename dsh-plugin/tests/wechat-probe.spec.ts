import { execFile, execFileSync } from 'node:child_process'
import fs from 'node:fs'
import {
  chmodSync,
  constants,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { syncBuiltinESMExports } from 'node:module'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { promisify } from 'node:util'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  WECHAT_ADAPTER_VERSION,
  WECHAT_SYNTHETIC_ADAPTER_VERSION,
  resolveWechatSourcePaths,
} from '../src/connectors/wechat/paths.ts'
import {
  createWechatFailureReport,
  probeWechatSource,
  type WechatProbeReport,
} from '../src/connectors/wechat/probe.ts'
import { runWechatProbeCli } from '../src/connectors/wechat/cli.ts'
import {
  withTestOnlyNonAtomicWechatSnapshot,
  type TestOnlyWechatSnapshotIo,
} from '../src/connectors/wechat/snapshot.ts'

const roots: string[] = []
const execFileAsync = promisify(execFile)

afterEach(() => {
  while (roots.length > 0) rmSync(roots.pop()!, { recursive: true, force: true })
})

function createSqliteSource({
  withValues = true,
}: {
  withValues?: boolean
} = {}) {
  const temporaryRoot = mkdtempSync(join(realpathSync(tmpdir()), 'ominime-wechat-probe-'))
  roots.push(temporaryRoot)
  const containerRoot = join(temporaryRoot, 'container')
  const accountDirectory = 'invented-account'
  const database = join(
    containerRoot,
    accountDirectory,
    'db_storage',
    'message',
    'message_0.db',
  )
  mkdirSync(join(database, '..'), { recursive: true })
  const statements = [
    'CREATE TABLE accounts (self_participant_id TEXT NOT NULL)',
    'CREATE TABLE participants (conversation_id TEXT NOT NULL, participant_id TEXT NOT NULL)',
    `CREATE TABLE messages (
      conversation_id TEXT NOT NULL,
      message_id TEXT NOT NULL,
      final_text TEXT,
      direction TEXT NOT NULL,
      source_timestamp INTEGER NOT NULL,
      source_order INTEGER NOT NULL,
      change_sequence INTEGER NOT NULL
    )`,
  ]
  if (withValues) {
    statements.push(
      "INSERT INTO accounts VALUES ('invented-private-account-value')",
      "INSERT INTO participants VALUES ('invented-private-conversation-value', 'invented-private-participant-value')",
      "INSERT INTO messages VALUES ('invented-private-conversation-value', 'invented-private-message-value', 'invented private message body', 'self', 1, 1, 1)",
    )
  }
  execFileSync('/usr/bin/sqlite3', [database, statements.join(';')], { stdio: 'ignore' })
  chmodSync(database, 0o400)
  const paths = resolveWechatSourcePaths({
    containerRoot,
    accountDirectory,
    adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
  })
  return { temporaryRoot, database, paths }
}

const testOnlySnapshotProvider = withTestOnlyNonAtomicWechatSnapshot

const expectedMappings = {
  sourceAccountIdentity: 'accounts.self_participant_id',
  conversationIdentity: 'messages.conversation_id',
  participantIdentity: 'participants.participant_id',
  stableMessageIdentity: 'messages.message_id',
  finalMessageText: 'messages.final_text',
  authoritativeDirectionOrSender: 'messages.direction',
  timestampOrOrdering: 'messages.source_timestamp,messages.source_order',
  incrementalChangeDetection: 'messages.change_sequence',
}

const allCapabilities = {
  sourceAccountIdentity: true,
  conversationAndParticipantIdentity: true,
  stableMessageIdentity: true,
  finalMessageText: true,
  authoritativeDirectionOrSender: true,
  timestampOrOrdering: true,
  incrementalChangeDetection: true,
}

const syntheticMetadataOutput = JSON.stringify([
  ['accounts', 'self_participant_id'],
  ['messages', 'change_sequence'],
  ['messages', 'conversation_id'],
  ['messages', 'direction'],
  ['messages', 'final_text'],
  ['messages', 'message_id'],
  ['messages', 'source_order'],
  ['messages', 'source_timestamp'],
  ['participants', 'conversation_id'],
  ['participants', 'participant_id'],
].map(([table_name, column_name]) => ({ table_name, column_name, present: 1 })))

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

function expectRedacted(report: WechatProbeReport): void {
  const serialized = JSON.stringify(report)
  for (const privateValue of [
    'invented-private-account-value',
    'invented-private-conversation-value',
    'invented-private-participant-value',
    'invented-private-message-value',
    'invented private message body',
  ]) {
    expect(serialized).not.toContain(privateValue)
  }
}

describe('WeChat read-only snapshot probe', () => {
  it('sanitizes caller-supplied failure and adapter values before serialization', () => {
    const report = createWechatFailureReport(
      'invented private failure value',
      'invented private adapter value',
    )

    expect(report.failureCodes).toEqual(['WECHAT_PROBE_FAILED'])
    expect(report.adapterVersion).toBe(WECHAT_ADAPTER_VERSION)
    expect(JSON.stringify(report)).not.toContain('invented private')
  })

  it('proves the seven capabilities from SQLite table and column metadata only', async () => {
    const source = createSqliteSource()
    const report = await probeWechatSource({
      paths: source.paths,
      redact: true,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
    })

    expect(report).toEqual({
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
      capabilities: allCapabilities,
      fieldMappings: expectedMappings,
      failureCodes: [],
    })
    expectRedacted(report)
  })

  it('performs zero live filesystem access when atomic open is unavailable', async () => {
    const original = {
      lstatSync: fs.lstatSync,
      opendirSync: fs.opendirSync,
      realpathSync: fs.realpathSync,
    }
    const lstatSpy = vi.fn(original.lstatSync)
    const opendirSpy = vi.fn(original.opendirSync)
    const realpathSpy = vi.fn(original.realpathSync)
    fs.lstatSync = lstatSpy as typeof fs.lstatSync
    fs.opendirSync = opendirSpy as typeof fs.opendirSync
    fs.realpathSync = realpathSpy as typeof fs.realpathSync
    syncBuiltinESMExports()
    let openCalls = 0
    const privateRoot = '/invented-private-live-root'
    const livePaths = {
      containerRoot: privateRoot,
      accountDirectory: 'invented-private-account',
      accountRoot: `${privateRoot}/invented-private-account`,
      sourceDirectory: `${privateRoot}/invented-private-account/db_storage/message`,
      adapterVersion: WECHAT_ADAPTER_VERSION,
      databaseRelativePath: 'db_storage/message/message_0.db',
      database: `${privateRoot}/invented-private-account/db_storage/message/message_0.db`,
      wal: `${privateRoot}/invented-private-account/db_storage/message/message_0.db-wal`,
      shm: `${privateRoot}/invented-private-account/db_storage/message/message_0.db-shm`,
    } as const

    try {
      const probeReport = await probeWechatSource({
        paths: livePaths,
        redact: true,
        testOnlyNonAtomicSnapshotProvider: async () => {
          openCalls += 1
          throw new Error('must not open')
        },
      })
      expect(probeReport.failureCodes).toEqual(['WECHAT_ATOMIC_OPEN_UNAVAILABLE'])

      const output: string[] = []
      expect(await runWechatProbeCli({
        argv: ['--redact'],
        env: {
          OMINIME_WECHAT_CONTAINER_ROOT: privateRoot,
          OMINIME_WECHAT_ACCOUNT_DIRECTORY: 'invented-private-account',
        },
        homeDirectory: privateRoot,
        write: text => output.push(text),
      })).toBe(2)
      expect(JSON.parse(output.join('')).failureCodes).toEqual(['WECHAT_ATOMIC_OPEN_UNAVAILABLE'])
      expect(output.join('')).not.toContain('invented-private')
    } finally {
      fs.lstatSync = original.lstatSync
      fs.opendirSync = original.opendirSync
      fs.realpathSync = original.realpathSync
      syncBuiltinESMExports()
    }

    expect(lstatSpy).toHaveBeenCalledTimes(0)
    expect(opendirSpy).toHaveBeenCalledTimes(0)
    expect(realpathSpy).toHaveBeenCalledTimes(0)
    expect(openCalls).toBe(0)
  })

  it('requires explicit redaction before touching the source', async () => {
    const source = createSqliteSource()
    const before = lstatSync(source.database)

    await expect(probeWechatSource({
      paths: source.paths,
      redact: false,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
    })).rejects.toMatchObject({
      code: 'SOURCE_INCOMPATIBLE',
      metadata: { reason: 'WECHAT_REDACTION_REQUIRED' },
    })

    const after = lstatSync(source.database)
    expect(after.mtimeMs).toBe(before.mtimeMs)
    expect(after.ctimeMs).toBe(before.ctimeMs)
  })

  it('accepts the package-manager argument separator only before --redact', async () => {
    const output: string[] = []
    const code = await runWechatProbeCli({
      argv: ['--', '--redact'],
      env: {
        OMINIME_WECHAT_CONTAINER_ROOT: '/invented-private-live-root',
        OMINIME_WECHAT_ACCOUNT_DIRECTORY: 'invented-private-account',
      },
      write: text => output.push(text),
    })

    expect(code).toBe(2)
    expect(JSON.parse(output.join(''))).toMatchObject({
      failureCodes: ['WECHAT_ATOMIC_OPEN_UNAVAILABLE'],
    })
    expect(output.join('')).not.toContain('invented-private')

    const rejected: string[] = []
    expect(await runWechatProbeCli({
      argv: ['--redact', '--unexpected'],
      env: {},
      write: text => rejected.push(text),
    })).toBe(2)
    expect(JSON.parse(rejected.join('')).failureCodes).toEqual(['WECHAT_REDACTION_REQUIRED'])
  })

  it('copies only the explicit database, WAL, and SHM whitelist', async () => {
    const source = createSqliteSource()
    writeFileSync(source.paths.wal, 'synthetic wal')
    writeFileSync(source.paths.shm, 'synthetic shm')
    writeFileSync(join(source.paths.sourceDirectory, 'invented-secret.txt'), 'must not copy')

    let snapshotDirectory = ''
    await withTestOnlyNonAtomicWechatSnapshot(source.paths, async snapshot => {
      snapshotDirectory = snapshot.directory
      expect(readdirSync(snapshot.directory).sort()).toEqual([
        basename(source.paths.database),
        basename(source.paths.shm),
        basename(source.paths.wal),
      ].sort())
    }, { temporaryParent: source.temporaryRoot })

    expect(existsSync(snapshotDirectory)).toBe(false)
  })

  it('supports absent sidecars but rejects SHM without WAL', async () => {
    const source = createSqliteSource()
    await expect(withTestOnlyNonAtomicWechatSnapshot(source.paths, async snapshot => {
      expect(snapshot.wal).toBeNull()
      expect(snapshot.shm).toBeNull()
    }, { temporaryParent: source.temporaryRoot })).resolves.toBeUndefined()

    writeFileSync(source.paths.shm, 'synthetic shm')
    await expect(withTestOnlyNonAtomicWechatSnapshot(source.paths, async () => undefined, {
      temporaryParent: source.temporaryRoot,
    })).rejects.toMatchObject({
      metadata: { reason: 'WECHAT_SNAPSHOT_INCONSISTENT' },
    })
  })

  it('cleans the task-owned snapshot after success, failure, and abort', async () => {
    const source = createSqliteSource()
    const created: string[] = []

    await withTestOnlyNonAtomicWechatSnapshot(source.paths, async snapshot => {
      created.push(snapshot.directory)
      expect(existsSync(snapshot.directory)).toBe(true)
    }, { temporaryParent: source.temporaryRoot })

    await expect(withTestOnlyNonAtomicWechatSnapshot(source.paths, async snapshot => {
      created.push(snapshot.directory)
      throw new Error('invented action failure')
    }, { temporaryParent: source.temporaryRoot })).rejects.toThrow('invented action failure')

    const controller = new AbortController()
    controller.abort()
    await expect(withTestOnlyNonAtomicWechatSnapshot(source.paths, async snapshot => {
      created.push(snapshot.directory)
    }, {
      signal: controller.signal,
      temporaryParent: source.temporaryRoot,
    })).rejects.toMatchObject({ name: 'AbortError' })

    expect(created.every(directory => !existsSync(directory))).toBe(true)
    expect(readdirSync(source.temporaryRoot).filter(name => name.startsWith('ominime-wechat-snapshot-'))).toEqual([])
  })

  it('opens the source read-only and never changes source mode, mtime, or ctime', async () => {
    const source = createSqliteSource()
    const before = lstatSync(source.database)

    await withTestOnlyNonAtomicWechatSnapshot(source.paths, async snapshot => {
      expect(lstatSync(snapshot.database).mode & 0o777).toBe(0o600)
    }, { temporaryParent: source.temporaryRoot })

    const after = lstatSync(source.database)
    expect(after.mode).toBe(before.mode)
    expect(after.mtimeMs).toBe(before.mtimeMs)
    expect(after.ctimeMs).toBe(before.ctimeMs)
  })

  it('rejects short reads and zero-byte writes with fixed errors', async () => {
    const source = createSqliteSource()
    const stats = lstatSync(source.database, { bigint: true })
    const snapshotDirectories = () => readdirSync(source.temporaryRoot)
      .filter(name => name.startsWith('ominime-wechat-snapshot-'))

    const ioFor = (mode: 'short-read' | 'zero-write'): TestOnlyWechatSnapshotIo => ({
      open: (async (path: string) => path === source.database
        ? {
            stat: async () => stats,
            read: async (buffer: Buffer) => mode === 'short-read'
              ? { buffer, bytesRead: 0 }
              : { buffer, bytesRead: 1 },
            close: async () => undefined,
          }
        : {
            write: async (buffer: Buffer) => ({
              buffer,
              bytesWritten: mode === 'zero-write' ? 0 : buffer.length,
            }),
            sync: async () => undefined,
            close: async () => undefined,
          }) as TestOnlyWechatSnapshotIo['open'],
    })

    await expect(withTestOnlyNonAtomicWechatSnapshot(source.paths, async () => undefined, {
      temporaryParent: source.temporaryRoot,
      testOnlyIo: ioFor('short-read'),
    })).rejects.toMatchObject({ metadata: { reason: 'WECHAT_SNAPSHOT_SHORT_READ' } })
    expect(snapshotDirectories()).toEqual([])

    await expect(withTestOnlyNonAtomicWechatSnapshot(source.paths, async () => undefined, {
      temporaryParent: source.temporaryRoot,
      testOnlyIo: ioFor('zero-write'),
    })).rejects.toMatchObject({ metadata: { reason: 'WECHAT_SNAPSHOT_SHORT_WRITE' } })
    expect(snapshotDirectories()).toEqual([])
  })

  it('attempts every close and exposes close failures without losing the primary error', async () => {
    const source = createSqliteSource()
    const stats = lstatSync(source.database, { bigint: true })
    const closeCalls: string[] = []
    const testOnlyIo: TestOnlyWechatSnapshotIo = {
      open: (async (path: string, flags: number) => path === source.database
        ? {
            stat: async () => stats,
            read: async (buffer: Buffer) => ({ buffer, bytesRead: 0 }),
            close: async () => {
              closeCalls.push('source')
              throw new Error('invented source close detail')
            },
          }
        : {
            write: async (buffer: Buffer) => ({ buffer, bytesWritten: buffer.length }),
            sync: async () => undefined,
            close: async () => {
              closeCalls.push(`destination-${flags === constants.O_RDONLY ? 'unexpected' : 'write'}`)
              throw new Error('invented destination close detail')
            },
          }) as TestOnlyWechatSnapshotIo['open'],
    }

    let error: unknown
    try {
      await withTestOnlyNonAtomicWechatSnapshot(source.paths, async () => undefined, {
        temporaryParent: source.temporaryRoot,
        testOnlyIo,
      })
    } catch (candidate) {
      error = candidate
    }

    expect(error).toBeInstanceOf(AggregateError)
    expect(error).toMatchObject({ message: 'WECHAT_SNAPSHOT_CLOSE_FAILED' })
    expect((error as AggregateError).errors.map(candidate => candidate.metadata.reason)).toEqual([
      'WECHAT_SNAPSHOT_SHORT_READ',
      'WECHAT_SNAPSHOT_CLOSE_FAILED',
    ])
    expect(JSON.stringify(error)).not.toContain('invented source close detail')
    expect(JSON.stringify(error)).not.toContain('invented destination close detail')
    expect(closeCalls.sort()).toEqual(['destination-write', 'source'])
    expect(readdirSync(source.temporaryRoot)
      .filter(name => name.startsWith('ominime-wechat-snapshot-'))).toEqual([])
  })

  it('preserves abort identity when copy abort and both closes fail', async () => {
    const source = createSqliteSource()
    const stats = lstatSync(source.database, { bigint: true })
    const controller = new AbortController()
    const closeCalls: string[] = []
    const unhandled: unknown[] = []
    const onUnhandled = (reason: unknown) => unhandled.push(reason)
    process.on('unhandledRejection', onUnhandled)
    const privateSourceCloseDetail = `private source close ${source.database}`
    const privateDestinationCloseDetail = `private destination close ${source.paths.accountRoot}`
    const testOnlyIo: TestOnlyWechatSnapshotIo = {
      open: (async (path: string) => path === source.database
        ? {
            stat: async () => stats,
            read: async (buffer: Buffer) => {
              controller.abort()
              return { buffer, bytesRead: 1 }
            },
            close: async () => {
              closeCalls.push('source')
              throw new Error(privateSourceCloseDetail)
            },
          }
        : {
            write: async (buffer: Buffer) => ({ buffer, bytesWritten: buffer.length }),
            sync: async () => undefined,
            close: async () => {
              closeCalls.push('destination')
              throw new Error(privateDestinationCloseDetail)
            },
          }) as TestOnlyWechatSnapshotIo['open'],
    }

    try {
      let error: unknown
      try {
        await probeWechatSource({
          paths: source.paths,
          redact: true,
          signal: controller.signal,
          temporaryParent: source.temporaryRoot,
          testOnlyNonAtomicSnapshotProvider: async (paths, action, options) =>
            await withTestOnlyNonAtomicWechatSnapshot(paths, action, { ...options, testOnlyIo }),
        })
      } catch (candidate) {
        error = candidate
      }

      expect(error).toBeInstanceOf(AggregateError)
      expect(error).toMatchObject({ name: 'AbortError', message: 'WECHAT_SNAPSHOT_CLOSE_FAILED' })
      expect((error as AggregateError).errors).toHaveLength(2)
      expect((error as AggregateError).errors[0]).toMatchObject({ name: 'AbortError' })
      expect((error as AggregateError).errors[1]).toMatchObject({
        metadata: { reason: 'WECHAT_SNAPSHOT_CLOSE_FAILED' },
      })
      expect(closeCalls.sort()).toEqual(['destination', 'source'])
      expect(JSON.stringify(error)).not.toContain(privateSourceCloseDetail)
      expect(JSON.stringify(error)).not.toContain(privateDestinationCloseDetail)
      expect(String(error)).not.toContain(source.database)
      expect(String(error)).not.toContain(source.paths.accountRoot)
      expect(readdirSync(source.temporaryRoot)
        .filter(name => name.startsWith('ominime-wechat-snapshot-'))).toEqual([])
      await new Promise<void>(resolve => setImmediate(resolve))
      expect(unhandled).toEqual([])
    } finally {
      process.off('unhandledRejection', onUnhandled)
    }
  })

  it('rejects encrypted or unknown headers without invoking SQLite', async () => {
    const source = createSqliteSource()
    chmodSync(source.database, 0o600)
    writeFileSync(source.database, 'invented encrypted bytes')
    chmodSync(source.database, 0o400)
    let runnerCalls = 0

    const report = await probeWechatSource({
      paths: source.paths,
      redact: true,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
      sqliteRunner: async () => {
        runnerCalls += 1
        return ''
      },
    })

    expect(report.failureCodes).toEqual(['WECHAT_SOURCE_NOT_SQLITE'])
    expect(Object.values(report.capabilities)).toEqual(Array(7).fill(false))
    expect(runnerCalls).toBe(0)
    expectRedacted(report)
  })

  it('fails closed on an unknown schema without selecting message values', async () => {
    const source = createSqliteSource({ withValues: false })
    chmodSync(source.database, 0o600)
    execFileSync('/usr/bin/sqlite3', [source.database, 'ALTER TABLE messages RENAME COLUMN direction TO guessed_sender'], {
      stdio: 'ignore',
    })
    chmodSync(source.database, 0o400)
    const sqlSeen: string[] = []
    const runner = async (command: string, args: readonly string[]) => {
      sqlSeen.push(args.at(-1) ?? '')
      expect(command).toBe('/usr/bin/sqlite3')
      const result = await execFileAsync(command, [...args], { encoding: 'utf8' })
      return result.stdout
    }

    const report = await probeWechatSource({
      paths: source.paths,
      redact: true,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
      sqliteRunner: runner,
    })

    expect(report.failureCodes).toEqual(['WECHAT_SCHEMA_UNKNOWN'])
    expect(Object.values(report.capabilities)).toEqual(Array(7).fill(false))
    expect(sqlSeen.length).toBeGreaterThan(0)
    expect(sqlSeen.every(sql => !/SELECT\s+.+\s+FROM\s+(accounts|participants|messages)/i.test(sql))).toBe(true)
    expect(sqlSeen.every(sql => !/final_text|self_participant_id/i.test(sql) || /pragma|sqlite_schema/i.test(sql))).toBe(true)
  })

  it('runs SQLite asynchronously without blocking the event loop', async () => {
    const source = createSqliteSource()
    const started = deferred<void>()
    const output = deferred<string>()
    const probe = probeWechatSource({
      paths: source.paths,
      redact: true,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
      sqliteRunner: async (command, _args, options) => {
        expect(command).toBe('/usr/bin/sqlite3')
        expect(options.timeoutMs).toBeGreaterThan(0)
        expect(options.maximumOutputBytes).toBeGreaterThan(0)
        started.resolve()
        return output.promise
      },
    })

    await started.promise
    let eventLoopTicked = false
    await new Promise<void>(resolve => setTimeout(() => {
      eventLoopTicked = true
      resolve()
    }, 0))
    expect(eventLoopTicked).toBe(true)
    output.resolve(syntheticMetadataOutput)
    await expect(probe).resolves.toMatchObject({ failureCodes: [] })
  })

  it('propagates caller abort promptly and maps runner timeout to a fixed code', async () => {
    const source = createSqliteSource()
    const createAbortAwareRunner = (started: ReturnType<typeof deferred<void>>) =>
      async (_command: string, _args: readonly string[], options: { signal: AbortSignal }) => {
        started.resolve()
        return await new Promise<string>((_resolve, reject) => {
          const rejectAbort = () => reject(options.signal.reason)
          if (options.signal.aborted) rejectAbort()
          else options.signal.addEventListener('abort', rejectAbort, { once: true })
        })
      }

    const controller = new AbortController()
    const abortStarted = deferred<void>()
    const abortProbe = probeWechatSource({
      paths: source.paths,
      redact: true,
      signal: controller.signal,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
      sqliteRunner: createAbortAwareRunner(abortStarted),
    })
    await abortStarted.promise
    const abortStart = Date.now()
    controller.abort()
    await expect(abortProbe).rejects.toMatchObject({ name: 'AbortError' })
    expect(Date.now() - abortStart).toBeLessThan(250)

    const timeoutStarted = deferred<void>()
    const timeoutReport = await probeWechatSource({
      paths: source.paths,
      redact: true,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
      sqliteRunner: createAbortAwareRunner(timeoutStarted),
      sqliteTimeoutMs: 20,
    })
    expect(timeoutReport.failureCodes).toEqual(['WECHAT_SQLITE_TIMEOUT'])
    expectRedacted(timeoutReport)
  })

  it('rejects oversized SQLite metadata output with a fixed redacted code', async () => {
    const source = createSqliteSource()
    const report = await probeWechatSource({
      paths: source.paths,
      redact: true,
      temporaryParent: source.temporaryRoot,
      testOnlyNonAtomicSnapshotProvider: testOnlySnapshotProvider,
      sqliteMaximumOutputBytes: 32,
      sqliteRunner: async () => 'invented private oversized output'.repeat(4),
    })

    expect(report.failureCodes).toEqual(['WECHAT_SQLITE_OUTPUT_LIMIT_EXCEEDED'])
    expect(JSON.stringify(report)).not.toContain('invented private')
  })
})
