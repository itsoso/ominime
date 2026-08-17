import fs from 'node:fs'
import {
  chmodSync,
  constants,
  existsSync,
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  realpathSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { syncBuiltinESMExports } from 'node:module'
import { tmpdir } from 'node:os'
import { basename, join } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { runKimProbeCli } from '../src/connectors/kim/cli.ts'
import {
  KIM_ADAPTER_VERSION,
  KIM_SYNTHETIC_ADAPTER_VERSION,
  KIM_SYNTHETIC_APP_VERSION,
  resolveKimSourcePaths,
} from '../src/connectors/kim/paths.ts'
import {
  createKimFailureReport,
  KimStoreReader,
  probeKimSource,
  type KimProbeReport,
  type KimStoreRangeReader,
} from '../src/connectors/kim/probe.ts'
import {
  KIM_SNAPSHOT_HARD_MAXIMUM_BYTES,
  withTestOnlyNonAtomicKimSnapshot,
  type TestOnlyKimSnapshotIo,
} from '../src/connectors/kim/snapshot.ts'

const roots: string[] = []
const magic = Buffer.from('OMKIMDB1')

afterEach(() => {
  while (roots.length > 0) rmSync(roots.pop()!, { recursive: true, force: true })
})

const metadataFields = [
  'profile.selfMemberId',
  'threads.threadId',
  'members.memberId',
  'messages.messageId',
  'messages.finalText',
  'messages.senderMemberId',
  'messages.sentAt',
  'messages.sequence',
  'changes.changeToken',
]

function encodeStore({
  headerVersion = 1,
  appVersion = KIM_SYNTHETIC_APP_VERSION,
  fields = metadataFields,
  trailing = 'invented private message body and participant name',
}: {
  headerVersion?: number
  appVersion?: string
  fields?: readonly string[]
  trailing?: string
} = {}): Buffer {
  const metadata = Buffer.from(JSON.stringify({ appVersion, fields }), 'utf8')
  const prefix = Buffer.alloc(14)
  magic.copy(prefix, 0)
  prefix.writeUInt16BE(headerVersion, 8)
  prefix.writeUInt32BE(metadata.length, 10)
  return Buffer.concat([prefix, metadata, Buffer.from(trailing, 'utf8')])
}

function encodeRawMetadata(metadata: Buffer, trailing = 'invented private message body'): Buffer {
  const prefix = Buffer.alloc(14)
  magic.copy(prefix, 0)
  prefix.writeUInt16BE(1, 8)
  prefix.writeUInt32BE(metadata.length, 10)
  return Buffer.concat([prefix, metadata, Buffer.from(trailing, 'utf8')])
}

function createKimSource(storeBytes = encodeStore()) {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'ominime-kim-probe-'))
  roots.push(root)
  const containerRoot = join(root, 'container')
  const profileDirectory = 'invented-profile'
  const store = join(containerRoot, profileDirectory, 'storage', 'chat', 'records.kimstore')
  mkdirSync(join(store, '..'), { recursive: true })
  writeFileSync(store, storeBytes, { mode: constants.S_IRUSR })
  const paths = resolveKimSourcePaths({
    containerRoot,
    profileDirectory,
    adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
    appVersion: KIM_SYNTHETIC_APP_VERSION,
  })
  return { root, store, paths }
}

const expectedMappings = {
  sourceAccountIdentity: 'profile.selfMemberId',
  conversationIdentity: 'threads.threadId',
  participantIdentity: 'members.memberId',
  stableMessageIdentity: 'messages.messageId',
  finalMessageText: 'messages.finalText',
  authoritativeDirectionOrSender: 'messages.senderMemberId',
  timestampOrOrdering: 'messages.sentAt,messages.sequence',
  incrementalChangeDetection: 'changes.changeToken',
}

const completeCapabilities = {
  sourceAccountIdentity: true,
  conversationAndParticipantIdentity: true,
  stableMessageIdentity: true,
  finalMessageText: true,
  authoritativeDirectionOrSender: true,
  timestampOrOrdering: true,
  incrementalChangeDetection: true,
}

function expectRedacted(report: KimProbeReport): void {
  const serialized = JSON.stringify(report)
  expect(serialized).not.toContain('invented private')
  expect(serialized).not.toContain('/ominime-kim-probe-')
}

describe('Kim structured-store probe', () => {
  it('keeps the production connector disabled without test-only exports', async () => {
    const entry = await import('../src/connectors/kim/index.ts')
    expect(entry.KIM_PRODUCTION_CONNECTOR_ENABLED).toBe(false)
    expect(Object.keys(entry).some(name => /synthetic|testonly|snapshot|provider/i.test(name))).toBe(false)
  })

  it('documents the invented fixture contract without source data', () => {
    const manifest = JSON.parse(readFileSync(
      new URL('./fixtures/kim/synthetic-manifest.json', import.meta.url),
      'utf8',
    ))
    expect(manifest).toEqual({
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
      storeRelativePath: 'storage/chat/records.kimstore',
      header: { magic: 'OMKIMDB1', version: 1, metadataEncoding: 'canonical-json-field-names-only' },
      fields: metadataFields,
      dataClassification: 'invented-only',
    })
  })

  it('sanitizes arbitrary failure and adapter values', () => {
    const report = createKimFailureReport('invented private code', 'invented private adapter')
    expect(report.failureCodes).toEqual(['KIM_PROBE_FAILED'])
    expect(report.adapterVersion).toBe(KIM_ADAPTER_VERSION)
    expectRedacted(report)
  })

  it('proves seven capabilities from bounded header metadata without reading body values', async () => {
    const source = createKimSource()
    const report = await probeKimSource({
      paths: source.paths,
      redact: true,
      temporaryParent: source.root,
      testOnlyNonAtomicSnapshotProvider: withTestOnlyNonAtomicKimSnapshot,
    })
    expect(report).toEqual({
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      capabilities: completeCapabilities,
      fieldMappings: expectedMappings,
      failureCodes: [],
    })
    expectRedacted(report)
  })

  it('reads exactly the fixed prefix and declared metadata ranges, never the trailing body', async () => {
    const bytes = encodeStore({ trailing: 'throw-if-reader-reaches-this-private-body' })
    const canonicalMetadataBytes = Buffer.from(JSON.stringify({
      appVersion: KIM_SYNTHETIC_APP_VERSION,
      fields: metadataFields,
    }), 'utf8')
    const bodyStart = 14 + canonicalMetadataBytes.length
    const reads: Array<{ position: number; length: number }> = []
    const rangeReader: KimStoreRangeReader = {
      async readExact(_path, position, length, signal) {
        signal.throwIfAborted()
        reads.push({ position, length })
        if (position + length > bodyStart) throw new Error('reader reached private body')
        return bytes.subarray(position, position + length)
      },
    }
    const reader = new KimStoreReader(rangeReader)

    const metadata = await reader.inspect(Object.freeze({
      directory: '/invented-task-snapshot',
      store: '/invented-task-snapshot/records.kimstore',
      journal: null,
      sharedMemory: null,
    }), new AbortController().signal)

    expect(metadata).toEqual({
      appVersion: KIM_SYNTHETIC_APP_VERSION,
      fields: metadataFields,
    })
    expect(reads).toEqual([
      { position: 0, length: 14 },
      { position: 14, length: canonicalMetadataBytes.length },
    ])
    expect(Math.max(...reads.map(read => read.position + read.length))).toBe(bodyStart)
  })

  it('performs zero Kim filesystem access for live adapters', async () => {
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
    let snapshotCalls = 0
    const privateRoot = '/invented-private-kim-root'
    const livePaths = {
      containerRoot: privateRoot,
      profileDirectory: 'invented-private-profile',
      profileRoot: `${privateRoot}/invented-private-profile`,
      sourceDirectory: `${privateRoot}/invented-private-profile/unknown`,
      adapterVersion: KIM_ADAPTER_VERSION,
      appVersion: 'invented-private-version',
      storeRelativePath: 'unknown',
      store: `${privateRoot}/invented-private-profile/unknown`,
      journal: `${privateRoot}/invented-private-profile/unknown-journal`,
      sharedMemory: `${privateRoot}/invented-private-profile/unknown-shared`,
    } as const

    try {
      const report = await probeKimSource({
        paths: livePaths,
        redact: true,
        testOnlyNonAtomicSnapshotProvider: async () => {
          snapshotCalls += 1
          throw new Error('must not open')
        },
      })
      expect(report.failureCodes).toEqual(['KIM_ATOMIC_OPEN_UNAVAILABLE'])

      const output: string[] = []
      expect(await runKimProbeCli({
        argv: ['--redact'],
        env: { OMINIME_KIM_ROOT: privateRoot },
        homeDirectory: privateRoot,
        write: text => output.push(text),
      })).toBe(2)
      expect(JSON.parse(output.join('')).failureCodes).toEqual(['KIM_ATOMIC_OPEN_UNAVAILABLE'])
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
    expect(snapshotCalls).toBe(0)
  })

  it('requires exactly --redact before touching source data', async () => {
    const source = createKimSource()
    const before = lstatSync(source.store)
    await expect(probeKimSource({
      paths: source.paths,
      redact: false,
      temporaryParent: source.root,
      testOnlyNonAtomicSnapshotProvider: withTestOnlyNonAtomicKimSnapshot,
    })).rejects.toMatchObject({ metadata: { reason: 'KIM_REDACTION_REQUIRED' } })
    const after = lstatSync(source.store)
    expect(after.mtimeMs).toBe(before.mtimeMs)
    expect(after.ctimeMs).toBe(before.ctimeMs)

    const accepted: string[] = []
    expect(await runKimProbeCli({ argv: ['--', '--redact'], write: text => accepted.push(text) })).toBe(2)
    expect(JSON.parse(accepted.join('')).failureCodes).toEqual(['KIM_ATOMIC_OPEN_UNAVAILABLE'])
    const rejected: string[] = []
    expect(await runKimProbeCli({ argv: ['--redact', '--unexpected'], write: text => rejected.push(text) })).toBe(2)
    expect(JSON.parse(rejected.join('')).failureCodes).toEqual(['KIM_REDACTION_REQUIRED'])
  })

  it('copies only the explicit Kim store bundle whitelist', async () => {
    const source = createKimSource()
    writeFileSync(source.paths.journal, 'invented journal')
    writeFileSync(source.paths.sharedMemory, 'invented shared state')
    writeFileSync(join(source.paths.sourceDirectory, 'invented-secret.txt'), 'must not copy')
    let directory = ''
    await withTestOnlyNonAtomicKimSnapshot(source.paths, async snapshot => {
      directory = snapshot.directory
      expect(readdirSync(snapshot.directory).sort()).toEqual([
        basename(source.paths.store),
        basename(source.paths.journal),
        basename(source.paths.sharedMemory),
      ].sort())
    }, { temporaryParent: source.root })
    expect(existsSync(directory)).toBe(false)
  })

  it('supports no sidecars and rejects shared memory without its journal', async () => {
    const source = createKimSource()
    await expect(withTestOnlyNonAtomicKimSnapshot(source.paths, async snapshot => {
      expect(snapshot.journal).toBeNull()
      expect(snapshot.sharedMemory).toBeNull()
    }, { temporaryParent: source.root })).resolves.toBeUndefined()
    writeFileSync(source.paths.sharedMemory, 'invented shared state')
    await expect(withTestOnlyNonAtomicKimSnapshot(source.paths, async () => undefined, {
      temporaryParent: source.root,
    })).rejects.toMatchObject({ metadata: { reason: 'KIM_SNAPSHOT_INCONSISTENT' } })
  })

  it('cleans snapshot directories after success, action failure, and abort', async () => {
    const source = createKimSource()
    const seen: string[] = []
    await withTestOnlyNonAtomicKimSnapshot(source.paths, async snapshot => {
      seen.push(snapshot.directory)
      expect(existsSync(snapshot.directory)).toBe(true)
    }, { temporaryParent: source.root })
    await expect(withTestOnlyNonAtomicKimSnapshot(source.paths, async snapshot => {
      seen.push(snapshot.directory)
      throw new Error('invented action failure')
    }, { temporaryParent: source.root })).rejects.toThrow('invented action failure')
    const controller = new AbortController()
    controller.abort()
    await expect(withTestOnlyNonAtomicKimSnapshot(source.paths, async snapshot => {
      seen.push(snapshot.directory)
    }, { signal: controller.signal, temporaryParent: source.root })).rejects.toMatchObject({ name: 'AbortError' })
    expect(seen.every(directory => !existsSync(directory))).toBe(true)
    expect(readdirSync(source.root).filter(name => name.startsWith('ominime-kim-snapshot-'))).toEqual([])
  })

  it('preserves source mode and timestamps while creating owner-only copies', async () => {
    const source = createKimSource()
    const before = lstatSync(source.store)
    await withTestOnlyNonAtomicKimSnapshot(source.paths, async snapshot => {
      expect(lstatSync(snapshot.store).mode & 0o777).toBe(0o600)
    }, { temporaryParent: source.root })
    const after = lstatSync(source.store)
    expect(after.mode).toBe(before.mode)
    expect(after.mtimeMs).toBe(before.mtimeMs)
    expect(after.ctimeMs).toBe(before.ctimeMs)
  })

  it('rejects invalid hard limits, short reads, zero writes, and wrong final lengths', async () => {
    const source = createKimSource()
    for (const maximumBytes of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY,
      KIM_SNAPSHOT_HARD_MAXIMUM_BYTES + 1]) {
      await expect(withTestOnlyNonAtomicKimSnapshot(source.paths, async () => undefined, {
        maximumBytes,
        temporaryParent: source.root,
      })).rejects.toMatchObject({ metadata: { reason: 'KIM_SNAPSHOT_LIMIT_INVALID' } })
    }

    const stats = lstatSync(source.store, { bigint: true })
    const ioFor = (mode: 'short-read' | 'zero-write' | 'wrong-length'): TestOnlyKimSnapshotIo => ({
      open: (async (path: string) => path === source.store
        ? {
            stat: async () => stats,
            read: async (buffer: Buffer, _offset: number, length: number) => mode === 'short-read'
              ? { buffer, bytesRead: 0 }
              : { buffer, bytesRead: length },
            close: async () => undefined,
          }
        : {
            stat: async () => ({
              dev: stats.dev,
              ino: stats.ino,
              size: mode === 'wrong-length' ? 0n : stats.size,
              mtimeNs: stats.mtimeNs,
              ctimeNs: stats.ctimeNs,
              isFile: () => true,
            }),
            write: async (buffer: Buffer, _offset: number, length: number) => ({
              buffer,
              bytesWritten: mode === 'zero-write' ? 0 : length,
            }),
            sync: async () => undefined,
            close: async () => undefined,
          }) as TestOnlyKimSnapshotIo['open'],
    })
    for (const [mode, reason] of [
      ['short-read', 'KIM_SNAPSHOT_SHORT_READ'],
      ['zero-write', 'KIM_SNAPSHOT_SHORT_WRITE'],
      ['wrong-length', 'KIM_SNAPSHOT_FINAL_LENGTH_MISMATCH'],
    ] as const) {
      await expect(withTestOnlyNonAtomicKimSnapshot(source.paths, async () => undefined, {
        temporaryParent: source.root,
        testOnlyIo: ioFor(mode),
      })).rejects.toMatchObject({ metadata: { reason } })
      expect(readdirSync(source.root).filter(name => name.startsWith('ominime-kim-snapshot-'))).toEqual([])
    }
  })

  it('attempts every close and exposes close failure without leaking details', async () => {
    const source = createKimSource()
    const stats = lstatSync(source.store, { bigint: true })
    const closes: string[] = []
    const testOnlyIo: TestOnlyKimSnapshotIo = {
      open: (async (path: string) => path === source.store
        ? {
            stat: async () => stats,
            read: async (buffer: Buffer) => ({ buffer, bytesRead: 0 }),
            close: async () => { closes.push('source'); throw new Error('invented source detail') },
          }
        : {
            stat: async () => stats,
            write: async (buffer: Buffer) => ({ buffer, bytesWritten: buffer.length }),
            sync: async () => undefined,
            close: async () => { closes.push('destination'); throw new Error('invented destination detail') },
          }) as TestOnlyKimSnapshotIo['open'],
    }
    let error: unknown
    try {
      await withTestOnlyNonAtomicKimSnapshot(source.paths, async () => undefined, {
        temporaryParent: source.root,
        testOnlyIo,
      })
    } catch (candidate) {
      error = candidate
    }
    expect(error).toBeInstanceOf(AggregateError)
    expect(error).toMatchObject({ message: 'KIM_SNAPSHOT_CLOSE_FAILED' })
    expect((error as AggregateError).errors.map(candidate => candidate.metadata.reason)).toEqual([
      'KIM_SNAPSHOT_SHORT_READ',
      'KIM_SNAPSHOT_CLOSE_FAILED',
    ])
    expect(closes.sort()).toEqual(['destination', 'source'])
    expect(JSON.stringify(error)).not.toContain('invented source detail')
    expect(JSON.stringify(error)).not.toContain('invented destination detail')
  })

  it('keeps AbortError identity while preserving close failure evidence', async () => {
    const source = createKimSource()
    const stats = lstatSync(source.store, { bigint: true })
    const controller = new AbortController()
    const closes: string[] = []
    const unhandled: unknown[] = []
    const onUnhandled = (reason: unknown) => unhandled.push(reason)
    process.on('unhandledRejection', onUnhandled)
    const testOnlyIo: TestOnlyKimSnapshotIo = {
      open: (async (path: string) => path === source.store
        ? {
            stat: async () => stats,
            read: async (buffer: Buffer) => {
              controller.abort()
              return { buffer, bytesRead: 1 }
            },
            close: async () => { closes.push('source'); throw new Error('invented source detail') },
          }
        : {
            stat: async () => stats,
            write: async (buffer: Buffer) => ({ buffer, bytesWritten: buffer.length }),
            sync: async () => undefined,
            close: async () => { closes.push('destination'); throw new Error('invented destination detail') },
          }) as TestOnlyKimSnapshotIo['open'],
    }
    try {
      let error: unknown
      try {
        await probeKimSource({
          paths: source.paths,
          redact: true,
          signal: controller.signal,
          temporaryParent: source.root,
          testOnlyNonAtomicSnapshotProvider: async (paths, action, options) => (
            await withTestOnlyNonAtomicKimSnapshot(paths, action, { ...options, testOnlyIo })
          ),
        })
      } catch (candidate) {
        error = candidate
      }
      expect(error).toBeInstanceOf(AggregateError)
      expect(error).toMatchObject({ name: 'AbortError', message: 'KIM_SNAPSHOT_CLOSE_FAILED' })
      expect((error as AggregateError).errors[0]).toMatchObject({ name: 'AbortError' })
      expect((error as AggregateError).errors[1]).toMatchObject({ metadata: { reason: 'KIM_SNAPSHOT_CLOSE_FAILED' } })
      expect(closes.sort()).toEqual(['destination', 'source'])
      await new Promise<void>(resolve => setImmediate(resolve))
      expect(unhandled).toEqual([])
    } finally {
      process.off('unhandledRejection', onUnhandled)
    }
  })

  it('fails closed on unknown header, format version, or noncanonical app and schema metadata', async () => {
    for (const [bytes, failure] of [
      [Buffer.from('short'), 'KIM_STORE_HEADER_UNKNOWN'],
      [Buffer.from('invented encrypted store'), 'KIM_STORE_HEADER_UNKNOWN'],
      [encodeStore({ headerVersion: 2 }), 'KIM_STORE_VERSION_UNKNOWN'],
      [encodeStore({ appVersion: 'invented-unknown-app' }), 'KIM_STORE_METADATA_NONCANONICAL'],
      [encodeStore({ fields: metadataFields.filter(field => field !== 'messages.finalText') }), 'KIM_STORE_METADATA_NONCANONICAL'],
    ] as const) {
      const source = createKimSource(bytes)
      const report = await probeKimSource({
        paths: source.paths,
        redact: true,
        temporaryParent: source.root,
        testOnlyNonAtomicSnapshotProvider: withTestOnlyNonAtomicKimSnapshot,
      })
      expect(report.failureCodes).toEqual([failure])
      expect(Object.values(report.capabilities)).toEqual(Array(7).fill(false))
      expectRedacted(report)
    }
  })

  it('accepts only the unique canonical metadata byte sequence', async () => {
    const fieldsJson = JSON.stringify(metadataFields)
    const appJson = JSON.stringify(KIM_SYNTHETIC_APP_VERSION)
    const variants = [
      Buffer.from(`{"appVersion":${appJson},"appVersion":${appJson},"fields":${fieldsJson}}`),
      Buffer.from(`{"appVersion":${appJson},"fields":${fieldsJson},"fields":${fieldsJson}}`),
      Buffer.concat([Buffer.from(`{"appVersion":${appJson},"fields":["`), Buffer.from([0xff]), Buffer.from('"]}')]),
      Buffer.from(`{"appVersion":${appJson},"fields":${fieldsJson},"unknown":true}`),
      Buffer.from(JSON.stringify({
        appVersion: KIM_SYNTHETIC_APP_VERSION,
        fields: [...metadataFields, 'messages.unknownField'],
      })),
      Buffer.from(JSON.stringify({ appVersion: KIM_SYNTHETIC_APP_VERSION, fields: [...metadataFields].reverse() })),
      Buffer.from(JSON.stringify({ appVersion: KIM_SYNTHETIC_APP_VERSION, fields: [...metadataFields, metadataFields[0]] })),
      Buffer.from(`{ "appVersion": ${appJson}, "fields": ${fieldsJson} }`),
    ]

    for (const metadata of variants) {
      const source = createKimSource(encodeRawMetadata(metadata))
      const report = await probeKimSource({
        paths: source.paths,
        redact: true,
        temporaryParent: source.root,
        testOnlyNonAtomicSnapshotProvider: withTestOnlyNonAtomicKimSnapshot,
      })
      expect(report.failureCodes).toEqual(['KIM_STORE_METADATA_NONCANONICAL'])
      expect(Object.values(report.capabilities)).toEqual(Array(7).fill(false))
      expectRedacted(report)
    }
  })

  it('rejects oversized or malformed header metadata with fixed errors', async () => {
    const oversized = Buffer.alloc(14)
    magic.copy(oversized, 0)
    oversized.writeUInt16BE(1, 8)
    oversized.writeUInt32BE(1024 * 1024, 10)
    const truncated = Buffer.alloc(16)
    magic.copy(truncated, 0)
    truncated.writeUInt16BE(1, 8)
    truncated.writeUInt32BE(10, 10)
    Buffer.from('{}').copy(truncated, 14)
    for (const [bytes, failure] of [
      [oversized, 'KIM_STORE_METADATA_LIMIT_EXCEEDED'],
      [truncated, 'KIM_STORE_METADATA_INVALID'],
      [Buffer.concat([oversized.subarray(0, 10), Buffer.from([0, 0, 0, 4]), Buffer.from('{bad')]), 'KIM_STORE_METADATA_NONCANONICAL'],
    ] as const) {
      const source = createKimSource(bytes)
      const report = await probeKimSource({
        paths: source.paths,
        redact: true,
        temporaryParent: source.root,
        testOnlyNonAtomicSnapshotProvider: withTestOnlyNonAtomicKimSnapshot,
      })
      expect(report.failureCodes).toEqual([failure])
      expectRedacted(report)
    }
  })
})
