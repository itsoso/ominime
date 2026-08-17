import { constants, existsSync, mkdtempSync, rmSync } from 'node:fs'
import { open, lstat } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { SourceIncompatibleError } from '../contract.ts'
import {
  WECHAT_ADAPTER_VERSION,
  WECHAT_SOURCE,
  WECHAT_SYNTHETIC_ADAPTER_VERSION,
  resolveWechatSourcePaths,
  type WechatSourcePaths,
} from './paths.ts'

const DEFAULT_MAXIMUM_SNAPSHOT_BYTES = 512 * 1024 * 1024
const COPY_BUFFER_BYTES = 256 * 1024

export interface WechatSnapshot {
  readonly directory: string
  readonly database: string
  readonly wal: string | null
  readonly shm: string | null
}

export interface WechatSnapshotOptions {
  readonly signal?: AbortSignal
  readonly sourceOpenMode?: 'read-only'
  readonly temporaryParent?: string
  readonly maximumBytes?: number
  readonly testOnlyIo?: TestOnlyWechatSnapshotIo
}

export interface TestOnlyWechatSnapshotFileHandle {
  readonly stat?: (options: { bigint: true }) => Promise<{
    readonly dev: bigint
    readonly ino: bigint
    readonly size: bigint
    readonly mtimeNs: bigint
    readonly ctimeNs: bigint
    isFile(): boolean
  }>
  readonly read?: (
    buffer: Buffer,
    offset: number,
    length: number,
    position: number,
  ) => Promise<{ readonly buffer: Buffer, readonly bytesRead: number }>
  readonly write?: (
    buffer: Buffer,
    offset: number,
    length: number,
    position: number,
  ) => Promise<{ readonly buffer: Buffer, readonly bytesWritten: number }>
  readonly sync?: () => Promise<void>
  readonly close: () => Promise<void>
}

export interface TestOnlyWechatSnapshotIo {
  readonly open: (
    path: string,
    flags: number,
    mode?: number,
  ) => Promise<TestOnlyWechatSnapshotFileHandle>
}

const defaultTestOnlyIo: TestOnlyWechatSnapshotIo = {
  open: async (path, flags, mode) => await open(path, flags, mode) as TestOnlyWechatSnapshotFileHandle,
}

interface FileSignature {
  readonly dev: bigint
  readonly ino: bigint
  readonly size: bigint
  readonly mtimeNs: bigint
  readonly ctimeNs: bigint
}

function incompatibleError(reason: string): SourceIncompatibleError {
  return new SourceIncompatibleError({
    source: WECHAT_SOURCE,
    adapterVersion: WECHAT_ADAPTER_VERSION,
    observedVersion: null,
    reason,
  })
}

function incompatible(reason: string): never {
  throw incompatibleError(reason)
}

class WechatSnapshotAbortError extends AggregateError {
  constructor(primaryError: unknown, closeError: SourceIncompatibleError) {
    super([primaryError, closeError], 'WECHAT_SNAPSHOT_CLOSE_FAILED')
    this.name = 'AbortError'
  }
}

function equalSignature(left: FileSignature, right: FileSignature): boolean {
  return left.dev === right.dev
    && left.ino === right.ino
    && left.size === right.size
    && left.mtimeNs === right.mtimeNs
    && left.ctimeNs === right.ctimeNs
}

async function pathSignature(path: string): Promise<FileSignature> {
  try {
    const stats = await lstat(path, { bigint: true })
    if (stats.isSymbolicLink()) incompatible('WECHAT_SYMLINK_REJECTED')
    if (!stats.isFile()) incompatible('WECHAT_SOURCE_ENTRY_INVALID')
    return {
      dev: stats.dev,
      ino: stats.ino,
      size: stats.size,
      mtimeNs: stats.mtimeNs,
      ctimeNs: stats.ctimeNs,
    }
  } catch (error) {
    if (error instanceof SourceIncompatibleError) throw error
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'EACCES' || code === 'EPERM') incompatible('WECHAT_SOURCE_PERMISSION_DENIED')
    incompatible('WECHAT_SOURCE_MUTATED')
  }
}

async function optionalSignature(path: string): Promise<FileSignature | null> {
  if (!existsSync(path)) return null
  return pathSignature(path)
}

async function copyReadOnlyStableFile({
  source,
  destination,
  expected,
  signal,
  remainingBytes,
  io,
}: {
  source: string
  destination: string
  expected: FileSignature
  signal: AbortSignal
  remainingBytes: number
  io: TestOnlyWechatSnapshotIo
}): Promise<number> {
  signal.throwIfAborted()
  if (expected.size > BigInt(remainingBytes)) incompatible('WECHAT_SNAPSHOT_LIMIT_EXCEEDED')
  let sourceHandle: TestOnlyWechatSnapshotFileHandle | undefined
  let destinationHandle: TestOnlyWechatSnapshotFileHandle | undefined
  let copiedBytes: number | undefined
  let primaryError: unknown
  try {
    const noFollow = constants.O_NOFOLLOW ?? 0
    sourceHandle = await io.open(source, constants.O_RDONLY | noFollow)
    if (sourceHandle.stat === undefined || sourceHandle.read === undefined) {
      incompatible('WECHAT_SNAPSHOT_COPY_FAILED')
    }
    const opened = await sourceHandle.stat({ bigint: true })
    const openedSignature: FileSignature = {
      dev: opened.dev,
      ino: opened.ino,
      size: opened.size,
      mtimeNs: opened.mtimeNs,
      ctimeNs: opened.ctimeNs,
    }
    if (!opened.isFile() || !equalSignature(expected, openedSignature)) {
      incompatible('WECHAT_SOURCE_MUTATED')
    }
    destinationHandle = await io.open(
      destination,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,
      0o600,
    )
    if (destinationHandle.write === undefined || destinationHandle.sync === undefined) {
      incompatible('WECHAT_SNAPSHOT_COPY_FAILED')
    }
    const buffer = Buffer.allocUnsafe(COPY_BUFFER_BYTES)
    let position = 0
    const expectedBytes = Number(expected.size)
    while (position < expectedBytes) {
      signal.throwIfAborted()
      const requested = Math.min(buffer.length, expectedBytes - position)
      const { bytesRead } = await sourceHandle.read(buffer, 0, requested, position)
      if (bytesRead === 0) incompatible('WECHAT_SNAPSHOT_SHORT_READ')
      if (bytesRead < 0 || bytesRead > requested) incompatible('WECHAT_SNAPSHOT_COPY_FAILED')
      let written = 0
      while (written < bytesRead) {
        signal.throwIfAborted()
        const result = await destinationHandle.write(buffer, written, bytesRead - written, position + written)
        if (result.bytesWritten === 0) incompatible('WECHAT_SNAPSHOT_SHORT_WRITE')
        if (result.bytesWritten < 0 || result.bytesWritten > bytesRead - written) {
          incompatible('WECHAT_SNAPSHOT_COPY_FAILED')
        }
        written += result.bytesWritten
      }
      position += bytesRead
      if (position > remainingBytes) incompatible('WECHAT_SNAPSHOT_LIMIT_EXCEEDED')
    }
    if (position !== expectedBytes) incompatible('WECHAT_SNAPSHOT_SHORT_READ')
    await destinationHandle.sync()
    const after = await sourceHandle.stat({ bigint: true })
    const afterSignature: FileSignature = {
      dev: after.dev,
      ino: after.ino,
      size: after.size,
      mtimeNs: after.mtimeNs,
      ctimeNs: after.ctimeNs,
    }
    if (!equalSignature(expected, afterSignature)) incompatible('WECHAT_SOURCE_MUTATED')
    copiedBytes = position
  } catch (error) {
    if (error instanceof SourceIncompatibleError || (error as Error).name === 'AbortError') {
      primaryError = error
    } else {
      const code = (error as NodeJS.ErrnoException).code
      primaryError = code === 'ELOOP'
        ? incompatibleError('WECHAT_SYMLINK_REJECTED')
        : code === 'EACCES' || code === 'EPERM'
          ? incompatibleError('WECHAT_SOURCE_PERMISSION_DENIED')
          : incompatibleError('WECHAT_SNAPSHOT_COPY_FAILED')
    }
  }

  const closeResults = await Promise.allSettled(
    [destinationHandle, sourceHandle]
      .filter((handle): handle is TestOnlyWechatSnapshotFileHandle => handle !== undefined)
      .map(async handle => await handle.close()),
  )
  if (closeResults.some(result => result.status === 'rejected')) {
    const closeError = incompatibleError('WECHAT_SNAPSHOT_CLOSE_FAILED')
    if ((primaryError as Error | undefined)?.name === 'AbortError') {
      throw new WechatSnapshotAbortError(primaryError, closeError)
    }
    throw new AggregateError(
      primaryError === undefined ? [closeError] : [primaryError, closeError],
      'WECHAT_SNAPSHOT_CLOSE_FAILED',
    )
  }
  if (primaryError !== undefined) throw primaryError
  return copiedBytes!
}

function assertSameResolvedPaths(before: WechatSourcePaths, after: WechatSourcePaths): void {
  for (const key of ['database', 'wal', 'shm'] as const) {
    if (before[key] !== after[key]) incompatible('WECHAT_SOURCE_MUTATED')
  }
}

export async function withTestOnlyNonAtomicWechatSnapshot<T>(
  paths: WechatSourcePaths,
  action: (snapshot: Readonly<WechatSnapshot>) => Promise<T> | T,
  {
    signal = new AbortController().signal,
    sourceOpenMode = 'read-only',
    temporaryParent = tmpdir(),
    maximumBytes = DEFAULT_MAXIMUM_SNAPSHOT_BYTES,
    testOnlyIo = defaultTestOnlyIo,
  }: WechatSnapshotOptions = {},
): Promise<T> {
  if (paths.adapterVersion !== WECHAT_SYNTHETIC_ADAPTER_VERSION) {
    incompatible('WECHAT_ATOMIC_OPEN_UNAVAILABLE')
  }
  if (sourceOpenMode !== 'read-only') incompatible('WECHAT_WRITABLE_SOURCE_OPEN_REJECTED')
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes <= 0) incompatible('WECHAT_SNAPSHOT_LIMIT_INVALID')

  const validated = resolveWechatSourcePaths({
    containerRoot: paths.containerRoot,
    accountDirectory: paths.accountDirectory,
    adapterVersion: paths.adapterVersion,
    databaseRelativePath: paths.databaseRelativePath,
  })
  assertSameResolvedPaths(paths, validated)
  const temporaryRoot = mkdtempSync(join(resolve(temporaryParent), 'ominime-wechat-snapshot-'))
  try {
    signal.throwIfAborted()
    const signatures = {
      database: await pathSignature(validated.database),
      wal: await optionalSignature(validated.wal),
      shm: await optionalSignature(validated.shm),
    }
    if (signatures.shm !== null && signatures.wal === null) {
      incompatible('WECHAT_SNAPSHOT_INCONSISTENT')
    }

    let remainingBytes = maximumBytes
    const copied: { database: string; wal: string | null; shm: string | null } = {
      database: join(temporaryRoot, basename(validated.database)),
      wal: null,
      shm: null,
    }
    remainingBytes -= await copyReadOnlyStableFile({
      source: validated.database,
      destination: copied.database,
      expected: signatures.database,
      signal,
      remainingBytes,
      io: testOnlyIo,
    })
    for (const key of ['wal', 'shm'] as const) {
      const signature = signatures[key]
      if (signature === null) continue
      const destination = join(temporaryRoot, basename(validated[key]))
      remainingBytes -= await copyReadOnlyStableFile({
        source: validated[key],
        destination,
        expected: signature,
        signal,
        remainingBytes,
        io: testOnlyIo,
      })
      copied[key] = destination
    }

    const after = resolveWechatSourcePaths({
      containerRoot: paths.containerRoot,
      accountDirectory: paths.accountDirectory,
      adapterVersion: paths.adapterVersion,
      databaseRelativePath: paths.databaseRelativePath,
    })
    assertSameResolvedPaths(validated, after)
    for (const key of ['database', 'wal', 'shm'] as const) {
      const expected = signatures[key]
      const actual = await optionalSignature(after[key])
      if ((expected === null) !== (actual === null)) incompatible('WECHAT_SOURCE_MUTATED')
      if (expected !== null && actual !== null && !equalSignature(expected, actual)) {
        incompatible('WECHAT_SOURCE_MUTATED')
      }
    }
    signal.throwIfAborted()
    return await action(Object.freeze({ directory: temporaryRoot, ...copied }))
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true })
  }
}
