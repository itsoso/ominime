import { execFile } from 'node:child_process'
import { constants } from 'node:fs'
import { open } from 'node:fs/promises'
import { SourceIncompatibleError } from '../contract.ts'
import {
  WECHAT_ADAPTER_VERSION,
  WECHAT_LEGACY_ADAPTER_VERSION,
  WECHAT_SOURCE,
  WECHAT_SYNTHETIC_ADAPTER_VERSION,
  isWechatLiveAdapterVersion,
  type WechatSourcePaths,
} from './paths.ts'
import {
  type WechatSnapshot,
  type WechatSnapshotOptions,
} from './snapshot.ts'

const TRUSTED_SQLITE_PATH = '/usr/bin/sqlite3'
const DEFAULT_SQLITE_TIMEOUT_MS = 2_000
const MAXIMUM_SQLITE_TIMEOUT_MS = 10_000
const DEFAULT_SQLITE_OUTPUT_BYTES = 64 * 1024
const MAXIMUM_SQLITE_OUTPUT_BYTES = 1024 * 1024

export interface WechatProbeCapabilities {
  readonly sourceAccountIdentity: boolean
  readonly conversationAndParticipantIdentity: boolean
  readonly stableMessageIdentity: boolean
  readonly finalMessageText: boolean
  readonly authoritativeDirectionOrSender: boolean
  readonly timestampOrOrdering: boolean
  readonly incrementalChangeDetection: boolean
}

export interface WechatFieldMappings {
  readonly sourceAccountIdentity: string | null
  readonly conversationIdentity: string | null
  readonly participantIdentity: string | null
  readonly stableMessageIdentity: string | null
  readonly finalMessageText: string | null
  readonly authoritativeDirectionOrSender: string | null
  readonly timestampOrOrdering: string | null
  readonly incrementalChangeDetection: string | null
}

export interface WechatProbeReport {
  readonly adapterVersion: string
  readonly capabilities: Readonly<WechatProbeCapabilities>
  readonly fieldMappings: Readonly<WechatFieldMappings>
  readonly failureCodes: readonly string[]
}

export type WechatSqliteRunner = (
  command: string,
  args: readonly string[],
  options: Readonly<WechatSqliteRunnerOptions>,
) => Promise<string>

export interface WechatSqliteRunnerOptions {
  readonly signal: AbortSignal
  readonly timeoutMs: number
  readonly maximumOutputBytes: number
}

export type TestOnlyNonAtomicWechatSnapshotProvider = <T>(
  paths: WechatSourcePaths,
  action: (snapshot: Readonly<WechatSnapshot>) => Promise<T> | T,
  options?: WechatSnapshotOptions,
) => Promise<T>

interface MetadataRow {
  readonly table_name: string
  readonly column_name: string
  readonly present: number
}

const mappings: Readonly<WechatFieldMappings> = Object.freeze({
  sourceAccountIdentity: 'accounts.self_participant_id',
  conversationIdentity: 'messages.conversation_id',
  participantIdentity: 'participants.participant_id',
  stableMessageIdentity: 'messages.message_id',
  finalMessageText: 'messages.final_text',
  authoritativeDirectionOrSender: 'messages.direction',
  timestampOrOrdering: 'messages.source_timestamp,messages.source_order',
  incrementalChangeDetection: 'messages.change_sequence',
})

const requiredColumns = Object.freeze([
  ['accounts', 'self_participant_id'],
  ['participants', 'conversation_id'],
  ['participants', 'participant_id'],
  ['messages', 'conversation_id'],
  ['messages', 'message_id'],
  ['messages', 'final_text'],
  ['messages', 'direction'],
  ['messages', 'source_timestamp'],
  ['messages', 'source_order'],
  ['messages', 'change_sequence'],
] as const)

const metadataSql = `
WITH required(table_name, column_name) AS (
  VALUES ${requiredColumns.map(([table, column]) => `('${table}', '${column}')`).join(', ')}
)
SELECT required.table_name, required.column_name,
       CASE WHEN EXISTS (
         SELECT 1 FROM pragma_table_info(required.table_name)
         WHERE name = required.column_name
       ) THEN 1 ELSE 0 END AS present
FROM required
ORDER BY required.table_name, required.column_name;
`.trim()

const emptyCapabilities: Readonly<WechatProbeCapabilities> = Object.freeze({
  sourceAccountIdentity: false,
  conversationAndParticipantIdentity: false,
  stableMessageIdentity: false,
  finalMessageText: false,
  authoritativeDirectionOrSender: false,
  timestampOrOrdering: false,
  incrementalChangeDetection: false,
})

const completeCapabilities: Readonly<WechatProbeCapabilities> = Object.freeze({
  sourceAccountIdentity: true,
  conversationAndParticipantIdentity: true,
  stableMessageIdentity: true,
  finalMessageText: true,
  authoritativeDirectionOrSender: true,
  timestampOrOrdering: true,
  incrementalChangeDetection: true,
})

const emptyMappings: Readonly<WechatFieldMappings> = Object.freeze({
  sourceAccountIdentity: null,
  conversationIdentity: null,
  participantIdentity: null,
  stableMessageIdentity: null,
  finalMessageText: null,
  authoritativeDirectionOrSender: null,
  timestampOrOrdering: null,
  incrementalChangeDetection: null,
})

const knownFailureCodes = new Set([
  'WECHAT_ACCOUNT_AMBIGUOUS',
  'WECHAT_ACCOUNT_UNRESOLVED',
  'WECHAT_ADAPTER_UNKNOWN',
  'WECHAT_ATOMIC_OPEN_UNAVAILABLE',
  'WECHAT_CONFIGURATION_INCOMPLETE',
  'WECHAT_CONTAINER_UNRESOLVED',
  'WECHAT_DISCOVERY_LIMIT_EXCEEDED',
  'WECHAT_DISCOVERY_LIMIT_INVALID',
  'WECHAT_FILE_UNRECOGNIZED',
  'WECHAT_PATH_ESCAPE',
  'WECHAT_PROBE_FAILED',
  'WECHAT_REDACTION_REQUIRED',
  'WECHAT_SCHEMA_UNKNOWN',
  'WECHAT_SNAPSHOT_COPY_FAILED',
  'WECHAT_SNAPSHOT_CLOSE_FAILED',
  'WECHAT_SNAPSHOT_INCONSISTENT',
  'WECHAT_SNAPSHOT_LIMIT_EXCEEDED',
  'WECHAT_SNAPSHOT_LIMIT_INVALID',
  'WECHAT_SNAPSHOT_SHORT_READ',
  'WECHAT_SNAPSHOT_SHORT_WRITE',
  'WECHAT_SOURCE_ENTRY_INVALID',
  'WECHAT_SOURCE_MISSING',
  'WECHAT_SOURCE_MUTATED',
  'WECHAT_SOURCE_NOT_FOUND',
  'WECHAT_SOURCE_NOT_SQLITE',
  'WECHAT_SOURCE_PERMISSION_DENIED',
  'WECHAT_SOURCE_UNAVAILABLE',
  'WECHAT_SQLITE_METADATA_UNAVAILABLE',
  'WECHAT_SQLITE_LIMIT_INVALID',
  'WECHAT_SQLITE_OUTPUT_LIMIT_EXCEEDED',
  'WECHAT_SQLITE_TIMEOUT',
  'WECHAT_SYMLINK_REJECTED',
  'WECHAT_WRITABLE_SOURCE_OPEN_REJECTED',
])

function safeFailureCode(candidate: string): string {
  return knownFailureCodes.has(candidate) ? candidate : 'WECHAT_PROBE_FAILED'
}

function safeAdapterVersion(candidate: string): string {
  return candidate === WECHAT_ADAPTER_VERSION
      || candidate === WECHAT_LEGACY_ADAPTER_VERSION
      || candidate === WECHAT_SYNTHETIC_ADAPTER_VERSION
    ? candidate
    : WECHAT_ADAPTER_VERSION
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

export function createWechatFailureReport(
  failureCode: string,
  adapterVersion = WECHAT_ADAPTER_VERSION,
): WechatProbeReport {
  return Object.freeze({
    adapterVersion: safeAdapterVersion(adapterVersion),
    capabilities: emptyCapabilities,
    fieldMappings: emptyMappings,
    failureCodes: Object.freeze([safeFailureCode(failureCode)]),
  })
}

function createSuccessReport(adapterVersion: string): WechatProbeReport {
  return Object.freeze({
    adapterVersion,
    capabilities: completeCapabilities,
    fieldMappings: mappings,
    failureCodes: Object.freeze([]),
  })
}

async function hasSqliteHeader(database: string, signal: AbortSignal): Promise<boolean> {
  signal.throwIfAborted()
  const handle = await open(database, constants.O_RDONLY)
  try {
    const header = Buffer.alloc(16)
    const { bytesRead } = await handle.read(header, 0, header.length, 0)
    return bytesRead === 16 && header.equals(Buffer.from('SQLite format 3\0'))
  } finally {
    await handle.close()
  }
}

function defaultSqliteRunner(
  command: string,
  args: readonly string[],
  options: Readonly<WechatSqliteRunnerOptions>,
): Promise<string> {
  return new Promise((resolveRunner, rejectRunner) => {
    execFile(command, [...args], {
      encoding: 'utf8',
      maxBuffer: options.maximumOutputBytes,
      signal: options.signal,
      timeout: options.timeoutMs,
      windowsHide: true,
    }, (error, stdout) => {
      if (error === null) {
        resolveRunner(stdout)
        return
      }
      if (error.name === 'AbortError') {
        rejectRunner(error)
        return
      }
      const code = (error as NodeJS.ErrnoException).code
      if ((error as NodeJS.ErrnoException & { killed?: boolean }).killed === true) {
        rejectRunner(incompatibleError('WECHAT_SQLITE_TIMEOUT'))
        return
      }
      if (code === 'ERR_CHILD_PROCESS_STDIO_MAXBUFFER') {
        rejectRunner(incompatibleError('WECHAT_SQLITE_OUTPUT_LIMIT_EXCEEDED'))
        return
      }
      rejectRunner(incompatibleError('WECHAT_SQLITE_METADATA_UNAVAILABLE'))
    })
  })
}

function hasRecognizedMetadata(output: string): boolean {
  let rows: unknown
  try {
    rows = JSON.parse(output)
  } catch {
    return false
  }
  if (!Array.isArray(rows) || rows.length !== requiredColumns.length) return false
  const observed = new Map<string, number>()
  for (const candidate of rows) {
    if (candidate === null || typeof candidate !== 'object' || Array.isArray(candidate)) return false
    const row = candidate as Partial<MetadataRow>
    if (typeof row.table_name !== 'string' || typeof row.column_name !== 'string' || row.present !== 1) {
      return false
    }
    observed.set(`${row.table_name}.${row.column_name}`, row.present)
  }
  return requiredColumns.every(([table, column]) => observed.get(`${table}.${column}`) === 1)
}

export async function probeWechatSource({
  paths,
  redact,
  signal = new AbortController().signal,
  temporaryParent,
  sqliteRunner = defaultSqliteRunner,
  sqliteTimeoutMs = DEFAULT_SQLITE_TIMEOUT_MS,
  sqliteMaximumOutputBytes = DEFAULT_SQLITE_OUTPUT_BYTES,
  testOnlyNonAtomicSnapshotProvider,
}: {
  paths: WechatSourcePaths
  redact: boolean
  signal?: AbortSignal
  temporaryParent?: string
  sqliteRunner?: WechatSqliteRunner
  sqliteTimeoutMs?: number
  sqliteMaximumOutputBytes?: number
  testOnlyNonAtomicSnapshotProvider?: TestOnlyNonAtomicWechatSnapshotProvider
}): Promise<WechatProbeReport> {
  if (redact !== true) incompatible('WECHAT_REDACTION_REQUIRED')
  if (isWechatLiveAdapterVersion(paths.adapterVersion)) {
    return createWechatFailureReport('WECHAT_ATOMIC_OPEN_UNAVAILABLE', paths.adapterVersion)
  }
  if (
    paths.adapterVersion !== WECHAT_SYNTHETIC_ADAPTER_VERSION
    || testOnlyNonAtomicSnapshotProvider === undefined
  ) {
    return createWechatFailureReport('WECHAT_ATOMIC_OPEN_UNAVAILABLE', paths.adapterVersion)
  }
  if (
    !Number.isSafeInteger(sqliteTimeoutMs)
    || sqliteTimeoutMs <= 0
    || sqliteTimeoutMs > MAXIMUM_SQLITE_TIMEOUT_MS
    || !Number.isSafeInteger(sqliteMaximumOutputBytes)
    || sqliteMaximumOutputBytes <= 0
    || sqliteMaximumOutputBytes > MAXIMUM_SQLITE_OUTPUT_BYTES
  ) {
    return createWechatFailureReport('WECHAT_SQLITE_LIMIT_INVALID', paths.adapterVersion)
  }
  try {
    return await testOnlyNonAtomicSnapshotProvider(paths, async snapshot => {
      signal.throwIfAborted()
      if (!await hasSqliteHeader(snapshot.database, signal)) {
        return createWechatFailureReport('WECHAT_SOURCE_NOT_SQLITE', paths.adapterVersion)
      }
      let output: string
      const timeoutSignal = AbortSignal.timeout(sqliteTimeoutMs)
      const runnerSignal = AbortSignal.any([signal, timeoutSignal])
      try {
        output = await sqliteRunner(
          TRUSTED_SQLITE_PATH,
          ['-readonly', '-json', snapshot.database, metadataSql],
          {
            signal: runnerSignal,
            timeoutMs: sqliteTimeoutMs,
            maximumOutputBytes: sqliteMaximumOutputBytes,
          },
        )
      } catch (error) {
        if (signal.aborted) signal.throwIfAborted()
        if (timeoutSignal.aborted) {
          return createWechatFailureReport('WECHAT_SQLITE_TIMEOUT', paths.adapterVersion)
        }
        if (error instanceof SourceIncompatibleError) {
          return createWechatFailureReport(error.metadata.reason, paths.adapterVersion)
        }
        if ((error as Error).name === 'AbortError') throw error
        return createWechatFailureReport('WECHAT_SQLITE_METADATA_UNAVAILABLE', paths.adapterVersion)
      }
      signal.throwIfAborted()
      if (Buffer.byteLength(output, 'utf8') > sqliteMaximumOutputBytes) {
        return createWechatFailureReport('WECHAT_SQLITE_OUTPUT_LIMIT_EXCEEDED', paths.adapterVersion)
      }
      return paths.adapterVersion === WECHAT_SYNTHETIC_ADAPTER_VERSION && hasRecognizedMetadata(output)
        ? createSuccessReport(paths.adapterVersion)
        : createWechatFailureReport('WECHAT_SCHEMA_UNKNOWN', paths.adapterVersion)
    }, { signal, temporaryParent })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    if (error instanceof SourceIncompatibleError) {
      return createWechatFailureReport(error.metadata.reason, paths.adapterVersion)
    }
    return createWechatFailureReport('WECHAT_PROBE_FAILED', paths.adapterVersion)
  }
}
