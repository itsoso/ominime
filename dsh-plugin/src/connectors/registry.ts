import type { Context } from '@deepseek-ai/cordis'
import type {
  ConversationRef,
  SourceHealth,
  SourceHealthError,
} from '../domain/types.ts'
import type { SourceConnector } from './contract.ts'

export type ConnectorResourceDisposer = () => void | Promise<void>

interface ConnectorResource {
  id: string
  connector: SourceConnector
  dispose: ConnectorResourceDisposer
  state: 'active' | 'releasing' | 'failed' | 'released'
  releasePromise: Promise<void> | undefined
}

const CONNECTOR_ID_PATTERN = /^[a-z][a-z0-9-]{0,63}$/
const HEALTH_ERROR_CODE_PATTERN = /^[A-Z][A-Z0-9_]{0,63}$/
const ADAPTER_VERSION_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$/
const CANONICAL_ISO_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/
const HEALTH_STATUSES = new Set(['healthy', 'degraded', 'disabled', 'incompatible'])
const HEALTH_KEYS = [
  'source',
  'status',
  'adapterVersion',
  'checkedAt',
  'lastSuccessfulSyncAt',
  'capabilities',
  'error',
] as const
const CAPABILITY_KEYS = ['edits', 'retractions', 'replyLinks', 'deletes'] as const

function isExactRecord(value: unknown, keys: readonly string[]): value is Record<string, unknown> {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const ownKeys = Reflect.ownKeys(value)
  return ownKeys.length === keys.length
    && ownKeys.every(key => typeof key === 'string' && keys.includes(key))
}

function isCanonicalIsoTimestamp(value: unknown): value is string {
  if (typeof value !== 'string' || !CANONICAL_ISO_PATTERN.test(value)) return false
  const instant = new Date(value)
  return !Number.isNaN(instant.getTime()) && instant.toISOString() === value
}

function invalidHealth(connectorId: string): SourceHealth {
  return Object.freeze({
    source: connectorId,
    status: 'degraded',
    adapterVersion: 'unknown',
    checkedAt: '1970-01-01T00:00:00.000Z',
    lastSuccessfulSyncAt: null,
    capabilities: Object.freeze({
      edits: false,
      retractions: false,
      replyLinks: false,
      deletes: false,
    }),
    error: Object.freeze({ code: 'INVALID_HEALTH_PAYLOAD' }),
  })
}

function sanitizeHealth(connector: SourceConnector, connectorId: string): SourceHealth {
  try {
    const health: unknown = connector.health()
    if (!isExactRecord(health, HEALTH_KEYS)) return invalidHealth(connectorId)
    if (health.source !== connectorId) return invalidHealth(connectorId)
    if (typeof health.status !== 'string' || !HEALTH_STATUSES.has(health.status)) {
      return invalidHealth(connectorId)
    }
    if (typeof health.adapterVersion !== 'string'
      || !ADAPTER_VERSION_PATTERN.test(health.adapterVersion)) {
      return invalidHealth(connectorId)
    }
    if (!isCanonicalIsoTimestamp(health.checkedAt)) return invalidHealth(connectorId)
    if (health.lastSuccessfulSyncAt !== null
      && !isCanonicalIsoTimestamp(health.lastSuccessfulSyncAt)) {
      return invalidHealth(connectorId)
    }
    const rawCapabilities = health.capabilities
    if (!isExactRecord(rawCapabilities, CAPABILITY_KEYS)
      || !CAPABILITY_KEYS.every(key => typeof rawCapabilities[key] === 'boolean')) {
      return invalidHealth(connectorId)
    }
    const rawError = health.error
    if (rawError !== null
      && (!isExactRecord(rawError, ['code'])
        || typeof rawError.code !== 'string'
        || !HEALTH_ERROR_CODE_PATTERN.test(rawError.code))) {
      return invalidHealth(connectorId)
    }

    const capabilities = Object.freeze({
      edits: rawCapabilities.edits as boolean,
      retractions: rawCapabilities.retractions as boolean,
      replyLinks: rawCapabilities.replyLinks as boolean,
      deletes: rawCapabilities.deletes as boolean,
    })
    const error: SourceHealthError | null = rawError === null
      ? null
      : Object.freeze({ code: rawError.code as string })
    return Object.freeze({
      source: connectorId,
      status: health.status as SourceHealth['status'],
      adapterVersion: health.adapterVersion,
      checkedAt: health.checkedAt,
      lastSuccessfulSyncAt: health.lastSuccessfulSyncAt,
      capabilities,
      error,
    })
  } catch {
    return invalidHealth(connectorId)
  }
}

function immutableConnectorSnapshot(connector: SourceConnector, connectorId: string): SourceConnector {
  return Object.freeze({
    id: connectorId,
    discoverAccounts: (signal: AbortSignal) => connector.discoverAccounts(signal),
    discoverConversations: (cursor: string | null, signal: AbortSignal) => (
      connector.discoverConversations(cursor, signal)
    ),
    syncMessages: (ref: ConversationRef, cursor: string | null, signal: AbortSignal) => (
      connector.syncMessages(ref, cursor, signal)
    ),
    backfill: (ref: ConversationRef, boundary: string | null, signal: AbortSignal) => (
      connector.backfill(ref, boundary, signal)
    ),
    health: () => sanitizeHealth(connector, connectorId),
  })
}

function defineErrorDetails(
  error: Error,
  code: string,
  metadata: Readonly<Record<string, unknown>>,
): void {
  Object.defineProperties(error, {
    code: { enumerable: true, value: code },
    metadata: { enumerable: true, value: Object.freeze(metadata) },
  })
}

interface ConnectorErrorMetadata {
  connectorId: string
}

export class InvalidConnectorIdError extends Error {
  declare readonly code: 'INVALID_CONNECTOR_ID'
  declare readonly metadata: Readonly<{ reason: 'FORMAT' }>

  constructor() {
    super('source connector ID does not match the required format')
    this.name = 'InvalidConnectorIdError'
    defineErrorDetails(this, 'INVALID_CONNECTOR_ID', { reason: 'FORMAT' })
  }
}

export class DuplicateConnectorError extends Error {
  declare readonly code: 'DUPLICATE_CONNECTOR'
  declare readonly metadata: Readonly<ConnectorErrorMetadata>

  constructor(connectorId: string) {
    super(`source connector ${JSON.stringify(connectorId)} is already registered`)
    this.name = 'DuplicateConnectorError'
    defineErrorDetails(this, 'DUPLICATE_CONNECTOR', { connectorId })
  }
}

export class ConnectorRegistryDisposedError extends Error {
  declare readonly code: 'CONNECTOR_REGISTRY_DISPOSED'
  declare readonly metadata: Readonly<ConnectorErrorMetadata>

  constructor(connectorId: string) {
    super(`cannot register source connector ${JSON.stringify(connectorId)} after registry disposal`)
    this.name = 'ConnectorRegistryDisposedError'
    defineErrorDetails(this, 'CONNECTOR_REGISTRY_DISPOSED', { connectorId })
  }
}

interface ConnectorDisposalFailure {
  connectorId: string
  error: unknown
}

export class ConnectorDisposalError extends AggregateError {
  declare readonly code: 'CONNECTOR_DISPOSAL_FAILED'
  declare readonly metadata: Readonly<{ connectorIds: readonly string[] }>

  constructor(failures: readonly ConnectorDisposalFailure[]) {
    const connectorIds = Object.freeze(failures.map(failure => failure.connectorId))
    super(
      failures.map(failure => failure.error),
      `failed to dispose ${failures.length} source connector resource${failures.length === 1 ? '' : 's'}`,
    )
    this.name = 'ConnectorDisposalError'
    defineErrorDetails(this, 'CONNECTOR_DISPOSAL_FAILED', { connectorIds })
  }
}

export class SourceConnectorRegistry {
  private readonly resources = new Map<string, ConnectorResource>()
  private readonly pendingReleases = new Set<ConnectorResource>()
  private disposed = false
  private disposal: Promise<void> | undefined

  constructor(ctx: Context) {
    ctx.effect(
      () => async () => this.disposeAll(),
      'personal-context: source connector registry',
    )
  }

  register(connector: SourceConnector, dispose: ConnectorResourceDisposer): ConnectorResourceDisposer {
    let connectorId: unknown
    try {
      connectorId = connector.id
    } catch {
      throw new InvalidConnectorIdError()
    }
    if (typeof connectorId !== 'string' || !CONNECTOR_ID_PATTERN.test(connectorId)) {
      throw new InvalidConnectorIdError()
    }
    if (this.disposed) throw new ConnectorRegistryDisposedError(connectorId)
    if (this.resources.has(connectorId)) throw new DuplicateConnectorError(connectorId)

    const resource: ConnectorResource = {
      id: connectorId,
      connector,
      dispose,
      state: 'active',
      releasePromise: undefined,
    }
    this.resources.set(connectorId, resource)
    return async () => {
      try {
        await this.releaseResource(resource)
      } catch (error) {
        throw new ConnectorDisposalError([{ connectorId, error }])
      }
    }
  }

  snapshot(): readonly SourceConnector[] {
    return Object.freeze(
      [...this.resources.values()]
        .filter(resource => resource.state === 'active')
        .map(resource => immutableConnectorSnapshot(resource.connector, resource.id)),
    )
  }

  private disposeAll(): Promise<void> {
    if (this.disposal !== undefined) return this.disposal
    this.disposed = true
    const resources = [...new Set([...this.resources.values(), ...this.pendingReleases])]
    this.disposal = this.releaseAll(resources)
    return this.disposal
  }

  private releaseResource(resource: ConnectorResource): Promise<void> {
    if (resource.releasePromise !== undefined) return resource.releasePromise
    resource.state = 'releasing'
    this.pendingReleases.add(resource)
    const releasePromise = Promise.resolve().then(() => resource.dispose())
    resource.releasePromise = releasePromise
    void releasePromise.then(
      () => {
        resource.state = 'released'
        this.pendingReleases.delete(resource)
        if (this.resources.get(resource.id) === resource) this.resources.delete(resource.id)
      },
      () => {
        resource.state = 'failed'
        this.pendingReleases.delete(resource)
      },
    )
    return releasePromise
  }

  private async releaseAll(resources: readonly ConnectorResource[]): Promise<void> {
    const failures: ConnectorDisposalFailure[] = []
    const results = await Promise.allSettled(resources.map(resource => this.releaseResource(resource)))
    for (const [index, result] of results.entries()) {
      if (result.status === 'rejected') {
        failures.push({ connectorId: resources[index]!.id, error: result.reason })
      }
    }
    if (failures.length > 0) throw new ConnectorDisposalError(failures)
  }
}
