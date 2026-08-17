import { constants, existsSync, mkdtempSync, rmSync } from 'node:fs'
import { lstat, open } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { basename, join, resolve } from 'node:path'
import { SourceIncompatibleError } from '../contract.ts'
import {
  KIM_ADAPTER_VERSION,
  KIM_SOURCE,
  KIM_SYNTHETIC_ADAPTER_VERSION,
  resolveKimSourcePaths,
  type KimSourcePaths,
} from './paths.ts'

export const KIM_SNAPSHOT_HARD_MAXIMUM_BYTES = 512 * 1024 * 1024
const DEFAULT_MAXIMUM_BYTES = KIM_SNAPSHOT_HARD_MAXIMUM_BYTES
const COPY_BUFFER_BYTES = 256 * 1024

export interface KimSnapshot {
  readonly directory: string
  readonly store: string
  readonly journal: string | null
  readonly sharedMemory: string | null
}

export interface KimSnapshotOptions {
  readonly signal?: AbortSignal
  readonly sourceOpenMode?: 'read-only'
  readonly temporaryParent?: string
  readonly maximumBytes?: number
  readonly testOnlyIo?: TestOnlyKimSnapshotIo
}

interface BigIntFileStats {
  readonly dev: bigint
  readonly ino: bigint
  readonly size: bigint
  readonly mtimeNs: bigint
  readonly ctimeNs: bigint
  isFile(): boolean
}

export interface TestOnlyKimSnapshotFileHandle {
  readonly stat?: (options: { bigint: true }) => Promise<BigIntFileStats>
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

export interface TestOnlyKimSnapshotIo {
  readonly open: (
    path: string,
    flags: number,
    mode?: number,
  ) => Promise<TestOnlyKimSnapshotFileHandle>
}

const defaultIo: TestOnlyKimSnapshotIo = {
  open: async (path, flags, mode) => await open(path, flags, mode) as TestOnlyKimSnapshotFileHandle,
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
    source: KIM_SOURCE,
    adapterVersion: KIM_ADAPTER_VERSION,
    observedVersion: null,
    reason,
  })
}

function incompatible(reason: string): never {
  throw incompatibleError(reason)
}

class KimSnapshotAbortError extends AggregateError {
  constructor(primaryError: unknown, closeError: SourceIncompatibleError) {
    super([primaryError, closeError], 'KIM_SNAPSHOT_CLOSE_FAILED')
    this.name = 'AbortError'
  }
}

function signatureOf(stats: BigIntFileStats): FileSignature {
  return {
    dev: stats.dev,
    ino: stats.ino,
    size: stats.size,
    mtimeNs: stats.mtimeNs,
    ctimeNs: stats.ctimeNs,
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
    if (stats.isSymbolicLink()) incompatible('KIM_SYMLINK_REJECTED')
    if (!stats.isFile()) incompatible('KIM_SOURCE_ENTRY_INVALID')
    return signatureOf(stats)
  } catch (error) {
    if (error instanceof SourceIncompatibleError) throw error
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'EACCES' || code === 'EPERM') incompatible('KIM_SOURCE_PERMISSION_DENIED')
    incompatible('KIM_SOURCE_MUTATED')
  }
}

async function optionalSignature(path: string): Promise<FileSignature | null> {
  if (!existsSync(path)) return null
  return pathSignature(path)
}

async function copyStableReadOnlyFile({
  source,
  destination,
  expected,
  remainingBytes,
  signal,
  io,
}: {
  source: string
  destination: string
  expected: FileSignature
  remainingBytes: number
  signal: AbortSignal
  io: TestOnlyKimSnapshotIo
}): Promise<number> {
  signal.throwIfAborted()
  if (expected.size > BigInt(remainingBytes)) incompatible('KIM_SNAPSHOT_LIMIT_EXCEEDED')
  let sourceHandle: TestOnlyKimSnapshotFileHandle | undefined
  let destinationHandle: TestOnlyKimSnapshotFileHandle | undefined
  let copiedBytes: number | undefined
  let primaryError: unknown
  try {
    sourceHandle = await io.open(source, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
    if (sourceHandle.stat === undefined || sourceHandle.read === undefined) {
      incompatible('KIM_SNAPSHOT_COPY_FAILED')
    }
    const opened = await sourceHandle.stat({ bigint: true })
    if (!opened.isFile() || !equalSignature(expected, signatureOf(opened))) {
      incompatible('KIM_SOURCE_MUTATED')
    }
    destinationHandle = await io.open(
      destination,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,
      0o600,
    )
    if (
      destinationHandle.stat === undefined
      || destinationHandle.write === undefined
      || destinationHandle.sync === undefined
    ) {
      incompatible('KIM_SNAPSHOT_COPY_FAILED')
    }

    const buffer = Buffer.allocUnsafe(COPY_BUFFER_BYTES)
    const expectedBytes = Number(expected.size)
    let position = 0
    while (position < expectedBytes) {
      signal.throwIfAborted()
      const requested = Math.min(buffer.length, expectedBytes - position)
      const { bytesRead } = await sourceHandle.read(buffer, 0, requested, position)
      if (bytesRead === 0) incompatible('KIM_SNAPSHOT_SHORT_READ')
      if (bytesRead < 0 || bytesRead > requested) incompatible('KIM_SNAPSHOT_COPY_FAILED')
      let written = 0
      while (written < bytesRead) {
        signal.throwIfAborted()
        const { bytesWritten } = await destinationHandle.write(
          buffer,
          written,
          bytesRead - written,
          position + written,
        )
        if (bytesWritten === 0) incompatible('KIM_SNAPSHOT_SHORT_WRITE')
        if (bytesWritten < 0 || bytesWritten > bytesRead - written) {
          incompatible('KIM_SNAPSHOT_COPY_FAILED')
        }
        written += bytesWritten
      }
      position += bytesRead
      if (position > remainingBytes) incompatible('KIM_SNAPSHOT_LIMIT_EXCEEDED')
    }
    if (position !== expectedBytes) incompatible('KIM_SNAPSHOT_SHORT_READ')
    await destinationHandle.sync()
    const destinationStats = await destinationHandle.stat({ bigint: true })
    if (!destinationStats.isFile() || destinationStats.size !== expected.size) {
      incompatible('KIM_SNAPSHOT_FINAL_LENGTH_MISMATCH')
    }
    const after = await sourceHandle.stat({ bigint: true })
    if (!equalSignature(expected, signatureOf(after))) incompatible('KIM_SOURCE_MUTATED')
    copiedBytes = position
  } catch (error) {
    if (error instanceof SourceIncompatibleError || (error as Error).name === 'AbortError') {
      primaryError = error
    } else {
      const code = (error as NodeJS.ErrnoException).code
      primaryError = code === 'ELOOP'
        ? incompatibleError('KIM_SYMLINK_REJECTED')
        : code === 'EACCES' || code === 'EPERM'
          ? incompatibleError('KIM_SOURCE_PERMISSION_DENIED')
          : incompatibleError('KIM_SNAPSHOT_COPY_FAILED')
    }
  }

  const closeResults = await Promise.allSettled(
    [destinationHandle, sourceHandle]
      .filter((handle): handle is TestOnlyKimSnapshotFileHandle => handle !== undefined)
      .map(async handle => await handle.close()),
  )
  if (closeResults.some(result => result.status === 'rejected')) {
    const closeError = incompatibleError('KIM_SNAPSHOT_CLOSE_FAILED')
    if ((primaryError as Error | undefined)?.name === 'AbortError') {
      throw new KimSnapshotAbortError(primaryError, closeError)
    }
    throw new AggregateError(
      primaryError === undefined ? [closeError] : [primaryError, closeError],
      'KIM_SNAPSHOT_CLOSE_FAILED',
    )
  }
  if (primaryError !== undefined) throw primaryError
  return copiedBytes!
}

function assertSamePaths(left: KimSourcePaths, right: KimSourcePaths): void {
  for (const key of ['store', 'journal', 'sharedMemory'] as const) {
    if (left[key] !== right[key]) incompatible('KIM_SOURCE_MUTATED')
  }
}

export async function withTestOnlyNonAtomicKimSnapshot<T>(
  paths: KimSourcePaths,
  action: (snapshot: Readonly<KimSnapshot>) => Promise<T> | T,
  {
    signal = new AbortController().signal,
    sourceOpenMode = 'read-only',
    temporaryParent = tmpdir(),
    maximumBytes = DEFAULT_MAXIMUM_BYTES,
    testOnlyIo = defaultIo,
  }: KimSnapshotOptions = {},
): Promise<T> {
  if (paths.adapterVersion !== KIM_SYNTHETIC_ADAPTER_VERSION) {
    incompatible('KIM_ATOMIC_OPEN_UNAVAILABLE')
  }
  if (sourceOpenMode !== 'read-only') incompatible('KIM_WRITABLE_SOURCE_OPEN_REJECTED')
  if (
    !Number.isSafeInteger(maximumBytes)
    || maximumBytes <= 0
    || maximumBytes > KIM_SNAPSHOT_HARD_MAXIMUM_BYTES
  ) {
    incompatible('KIM_SNAPSHOT_LIMIT_INVALID')
  }

  const validated = resolveKimSourcePaths({
    containerRoot: paths.containerRoot,
    profileDirectory: paths.profileDirectory,
    adapterVersion: paths.adapterVersion,
    appVersion: paths.appVersion,
    storeRelativePath: paths.storeRelativePath,
  })
  assertSamePaths(paths, validated)
  const temporaryRoot = mkdtempSync(join(resolve(temporaryParent), 'ominime-kim-snapshot-'))
  try {
    signal.throwIfAborted()
    const signatures = {
      store: await pathSignature(validated.store),
      journal: await optionalSignature(validated.journal),
      sharedMemory: await optionalSignature(validated.sharedMemory),
    }
    if (signatures.sharedMemory !== null && signatures.journal === null) {
      incompatible('KIM_SNAPSHOT_INCONSISTENT')
    }
    let remainingBytes = maximumBytes
    const copied: { store: string; journal: string | null; sharedMemory: string | null } = {
      store: join(temporaryRoot, basename(validated.store)),
      journal: null,
      sharedMemory: null,
    }
    remainingBytes -= await copyStableReadOnlyFile({
      source: validated.store,
      destination: copied.store,
      expected: signatures.store,
      remainingBytes,
      signal,
      io: testOnlyIo,
    })
    for (const key of ['journal', 'sharedMemory'] as const) {
      const signature = signatures[key]
      if (signature === null) continue
      const destination = join(temporaryRoot, basename(validated[key]))
      remainingBytes -= await copyStableReadOnlyFile({
        source: validated[key],
        destination,
        expected: signature,
        remainingBytes,
        signal,
        io: testOnlyIo,
      })
      copied[key] = destination
    }

    const after = resolveKimSourcePaths({
      containerRoot: paths.containerRoot,
      profileDirectory: paths.profileDirectory,
      adapterVersion: paths.adapterVersion,
      appVersion: paths.appVersion,
      storeRelativePath: paths.storeRelativePath,
    })
    assertSamePaths(validated, after)
    for (const key of ['store', 'journal', 'sharedMemory'] as const) {
      const expected = signatures[key]
      const actual = await optionalSignature(after[key])
      if ((expected === null) !== (actual === null)) incompatible('KIM_SOURCE_MUTATED')
      if (expected !== null && actual !== null && !equalSignature(expected, actual)) {
        incompatible('KIM_SOURCE_MUTATED')
      }
    }
    signal.throwIfAborted()
    return await action(Object.freeze({ directory: temporaryRoot, ...copied }))
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true })
  }
}
