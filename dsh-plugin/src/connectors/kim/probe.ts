import { constants } from 'node:fs'
import { open } from 'node:fs/promises'
import { SourceIncompatibleError } from '../contract.ts'
import {
  KIM_ADAPTER_VERSION,
  KIM_SOURCE,
  KIM_SYNTHETIC_ADAPTER_VERSION,
  KIM_SYNTHETIC_APP_VERSION,
  isKimLiveAdapterVersion,
  type KimSourcePaths,
} from './paths.ts'
import type { KimSnapshot, KimSnapshotOptions } from './snapshot.ts'

const STORE_MAGIC = Buffer.from('OMKIMDB1')
const STORE_PREFIX_BYTES = 14
const STORE_HEADER_VERSION = 1
const MAXIMUM_METADATA_BYTES = 16 * 1024

export interface KimProbeCapabilities {
  readonly sourceAccountIdentity: boolean
  readonly conversationAndParticipantIdentity: boolean
  readonly stableMessageIdentity: boolean
  readonly finalMessageText: boolean
  readonly authoritativeDirectionOrSender: boolean
  readonly timestampOrOrdering: boolean
  readonly incrementalChangeDetection: boolean
}

export interface KimFieldMappings {
  readonly sourceAccountIdentity: string | null
  readonly conversationIdentity: string | null
  readonly participantIdentity: string | null
  readonly stableMessageIdentity: string | null
  readonly finalMessageText: string | null
  readonly authoritativeDirectionOrSender: string | null
  readonly timestampOrOrdering: string | null
  readonly incrementalChangeDetection: string | null
}

export interface KimProbeReport {
  readonly adapterVersion: string
  readonly capabilities: Readonly<KimProbeCapabilities>
  readonly fieldMappings: Readonly<KimFieldMappings>
  readonly failureCodes: readonly string[]
}

export interface KimStoreMetadata {
  readonly appVersion: string
  readonly fields: readonly string[]
}

export interface KimStoreRangeReader {
  readExact(
    path: string,
    position: number,
    length: number,
    signal: AbortSignal,
  ): Promise<Buffer>
}

export type TestOnlyNonAtomicKimSnapshotProvider = <T>(
  paths: KimSourcePaths,
  action: (snapshot: Readonly<KimSnapshot>) => Promise<T> | T,
  options?: KimSnapshotOptions,
) => Promise<T>

const requiredFields = Object.freeze([
  'profile.selfMemberId',
  'threads.threadId',
  'members.memberId',
  'messages.messageId',
  'messages.finalText',
  'messages.senderMemberId',
  'messages.sentAt',
  'messages.sequence',
  'changes.changeToken',
])

const canonicalMetadataBytes = Buffer.from(JSON.stringify({
  appVersion: KIM_SYNTHETIC_APP_VERSION,
  fields: requiredFields,
}), 'utf8')

const mappings: Readonly<KimFieldMappings> = Object.freeze({
  sourceAccountIdentity: 'profile.selfMemberId',
  conversationIdentity: 'threads.threadId',
  participantIdentity: 'members.memberId',
  stableMessageIdentity: 'messages.messageId',
  finalMessageText: 'messages.finalText',
  authoritativeDirectionOrSender: 'messages.senderMemberId',
  timestampOrOrdering: 'messages.sentAt,messages.sequence',
  incrementalChangeDetection: 'changes.changeToken',
})

const emptyMappings: Readonly<KimFieldMappings> = Object.freeze({
  sourceAccountIdentity: null,
  conversationIdentity: null,
  participantIdentity: null,
  stableMessageIdentity: null,
  finalMessageText: null,
  authoritativeDirectionOrSender: null,
  timestampOrOrdering: null,
  incrementalChangeDetection: null,
})

const emptyCapabilities: Readonly<KimProbeCapabilities> = Object.freeze({
  sourceAccountIdentity: false,
  conversationAndParticipantIdentity: false,
  stableMessageIdentity: false,
  finalMessageText: false,
  authoritativeDirectionOrSender: false,
  timestampOrOrdering: false,
  incrementalChangeDetection: false,
})

const completeCapabilities: Readonly<KimProbeCapabilities> = Object.freeze({
  sourceAccountIdentity: true,
  conversationAndParticipantIdentity: true,
  stableMessageIdentity: true,
  finalMessageText: true,
  authoritativeDirectionOrSender: true,
  timestampOrOrdering: true,
  incrementalChangeDetection: true,
})

const knownFailureCodes = new Set([
  'KIM_ADAPTER_UNKNOWN',
  'KIM_APP_VERSION_UNKNOWN',
  'KIM_ATOMIC_OPEN_UNAVAILABLE',
  'KIM_CONTAINER_UNRESOLVED',
  'KIM_DISCOVERY_LIMIT_EXCEEDED',
  'KIM_DISCOVERY_LIMIT_INVALID',
  'KIM_FILE_UNRECOGNIZED',
  'KIM_PATH_ESCAPE',
  'KIM_PROBE_FAILED',
  'KIM_PROFILE_AMBIGUOUS',
  'KIM_PROFILE_UNRESOLVED',
  'KIM_REDACTION_REQUIRED',
  'KIM_SNAPSHOT_CLOSE_FAILED',
  'KIM_SNAPSHOT_COPY_FAILED',
  'KIM_SNAPSHOT_FINAL_LENGTH_MISMATCH',
  'KIM_SNAPSHOT_INCONSISTENT',
  'KIM_SNAPSHOT_LIMIT_EXCEEDED',
  'KIM_SNAPSHOT_LIMIT_INVALID',
  'KIM_SNAPSHOT_SHORT_READ',
  'KIM_SNAPSHOT_SHORT_WRITE',
  'KIM_SOURCE_ENTRY_INVALID',
  'KIM_SOURCE_MISSING',
  'KIM_SOURCE_MUTATED',
  'KIM_SOURCE_PERMISSION_DENIED',
  'KIM_SOURCE_UNAVAILABLE',
  'KIM_STORE_HEADER_UNKNOWN',
  'KIM_STORE_METADATA_INVALID',
  'KIM_STORE_METADATA_LIMIT_EXCEEDED',
  'KIM_STORE_METADATA_NONCANONICAL',
  'KIM_STORE_READ_FAILED',
  'KIM_STORE_VERSION_UNKNOWN',
  'KIM_SYMLINK_REJECTED',
  'KIM_WRITABLE_SOURCE_OPEN_REJECTED',
])

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

function safeAdapterVersion(candidate: string): string {
  return candidate === KIM_ADAPTER_VERSION || candidate === KIM_SYNTHETIC_ADAPTER_VERSION
    ? candidate
    : KIM_ADAPTER_VERSION
}

function safeFailureCode(candidate: string): string {
  return knownFailureCodes.has(candidate) ? candidate : 'KIM_PROBE_FAILED'
}

export function createKimFailureReport(
  failureCode: string,
  adapterVersion = KIM_ADAPTER_VERSION,
): KimProbeReport {
  return Object.freeze({
    adapterVersion: safeAdapterVersion(adapterVersion),
    capabilities: emptyCapabilities,
    fieldMappings: emptyMappings,
    failureCodes: Object.freeze([safeFailureCode(failureCode)]),
  })
}

function createSuccessReport(): KimProbeReport {
  return Object.freeze({
    adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
    capabilities: completeCapabilities,
    fieldMappings: mappings,
    failureCodes: Object.freeze([]),
  })
}

const nodeRangeReader: KimStoreRangeReader = {
  async readExact(path, position, length, signal) {
    signal.throwIfAborted()
    let handle: Awaited<ReturnType<typeof open>> | undefined
    let primaryError: unknown
    let result: Buffer | undefined
    try {
      handle = await open(path, constants.O_RDONLY | (constants.O_NOFOLLOW ?? 0))
      const buffer = Buffer.alloc(length)
      let offset = 0
      while (offset < length) {
        signal.throwIfAborted()
        const { bytesRead } = await handle.read(buffer, offset, length - offset, position + offset)
        if (bytesRead === 0) break
        offset += bytesRead
      }
      result = buffer.subarray(0, offset)
    } catch (error) {
      primaryError = (error as Error).name === 'AbortError'
        ? error
        : incompatibleError('KIM_STORE_READ_FAILED')
    }
    if (handle !== undefined) {
      const closeResult = await Promise.allSettled([handle.close()])
      if (closeResult[0]?.status === 'rejected') {
        const closeError = incompatibleError('KIM_STORE_READ_FAILED')
        if ((primaryError as Error | undefined)?.name === 'AbortError') {
          const aggregate = new AggregateError([primaryError, closeError], 'KIM_STORE_READ_FAILED')
          aggregate.name = 'AbortError'
          throw aggregate
        }
        throw new AggregateError(
          primaryError === undefined ? [closeError] : [primaryError, closeError],
          'KIM_STORE_READ_FAILED',
        )
      }
    }
    if (primaryError !== undefined) throw primaryError
    return result!
  },
}

export class KimStoreReader {
  constructor(private readonly rangeReader: KimStoreRangeReader = nodeRangeReader) {}

  async inspect(snapshot: Readonly<KimSnapshot>, signal: AbortSignal): Promise<Readonly<KimStoreMetadata>> {
    signal.throwIfAborted()
    const prefix = await this.rangeReader.readExact(snapshot.store, 0, STORE_PREFIX_BYTES, signal)
    if (prefix.length !== STORE_PREFIX_BYTES
      || !prefix.subarray(0, STORE_MAGIC.length).equals(STORE_MAGIC)) {
      incompatible('KIM_STORE_HEADER_UNKNOWN')
    }
    const headerVersion = prefix.readUInt16BE(8)
    if (headerVersion !== STORE_HEADER_VERSION) incompatible('KIM_STORE_VERSION_UNKNOWN')
    const metadataLength = prefix.readUInt32BE(10)
    if (metadataLength === 0 || metadataLength > MAXIMUM_METADATA_BYTES) {
      incompatible('KIM_STORE_METADATA_LIMIT_EXCEEDED')
    }
    const encoded = await this.rangeReader.readExact(
      snapshot.store,
      STORE_PREFIX_BYTES,
      metadataLength,
      signal,
    )
    if (encoded.length !== metadataLength) incompatible('KIM_STORE_METADATA_INVALID')
    if (!encoded.equals(canonicalMetadataBytes)) incompatible('KIM_STORE_METADATA_NONCANONICAL')
    return Object.freeze({
      appVersion: KIM_SYNTHETIC_APP_VERSION,
      fields: Object.freeze([...requiredFields]),
    })
  }
}

export async function probeKimSource({
  paths,
  redact,
  signal = new AbortController().signal,
  temporaryParent,
  testOnlyNonAtomicSnapshotProvider,
}: {
  paths: KimSourcePaths
  redact: boolean
  signal?: AbortSignal
  temporaryParent?: string
  testOnlyNonAtomicSnapshotProvider?: TestOnlyNonAtomicKimSnapshotProvider
}): Promise<KimProbeReport> {
  if (redact !== true) incompatible('KIM_REDACTION_REQUIRED')
  if (isKimLiveAdapterVersion(paths.adapterVersion)) {
    return createKimFailureReport('KIM_ATOMIC_OPEN_UNAVAILABLE', paths.adapterVersion)
  }
  if (
    paths.adapterVersion !== KIM_SYNTHETIC_ADAPTER_VERSION
    || paths.appVersion !== KIM_SYNTHETIC_APP_VERSION
    || testOnlyNonAtomicSnapshotProvider === undefined
  ) {
    return createKimFailureReport(
      paths.appVersion === KIM_SYNTHETIC_APP_VERSION
        ? 'KIM_ATOMIC_OPEN_UNAVAILABLE'
        : 'KIM_APP_VERSION_UNKNOWN',
      paths.adapterVersion,
    )
  }
  try {
    return await testOnlyNonAtomicSnapshotProvider(paths, async snapshot => {
      signal.throwIfAborted()
      await new KimStoreReader().inspect(snapshot, signal)
      signal.throwIfAborted()
      return createSuccessReport()
    }, { signal, temporaryParent })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    if (error instanceof SourceIncompatibleError) {
      return createKimFailureReport(error.metadata.reason, paths.adapterVersion)
    }
    return createKimFailureReport('KIM_PROBE_FAILED', paths.adapterVersion)
  }
}
