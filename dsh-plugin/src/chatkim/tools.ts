import type { Context } from '@deepseek-ai/cordis'

import {
  AccountScopedKimChatGateway,
  type ChatkimProcessGateway,
  KimChatAccountError,
} from './account.ts'
import { ChatkimClient, ChatkimClientError, type ChatkimQueryTool, type ChatkimReaderTool } from './client.ts'
import { ChatkimConfigError, resolveChatkimExecutable } from './config.ts'
import {
  KimChatProjectionError,
  projectContext,
  projectConversations,
  projectCurrentUser,
  projectMessages,
} from './project.ts'

const ADAPTER_VERSION = 'chatkimv2-mcp-v1'
const SAFE_TIME_RANGES = new Set([
  'today',
  'yesterday',
  'this_week',
  'last_week',
  'this_month',
  'last_month',
  'recent_7days',
  'recent_30days',
])
const DATE_RANGE_PATTERN = /^\d{4}-\d{2}-\d{2}(?:~\d{4}-\d{2}-\d{2})?$/
const CURSOR_PATTERN = /^(?:[a-fA-F0-9]{2})+$/

export interface KimChatGateway {
  callTool(
    name: ChatkimQueryTool,
    args: Readonly<Record<string, unknown>>,
    signal?: AbortSignal,
  ): Promise<unknown>
  dispose(): Promise<void>
}

export type KimChatToolErrorCode =
  | 'KIM_CHAT_INVALID_ARGUMENTS'
  | 'KIM_CHAT_RESPONSE_INVALID'
  | 'KIM_CHAT_UNAVAILABLE'
  | ChatkimConfigError['code']
  | ChatkimClientError['code']
  | KimChatAccountError['code']

export class KimChatToolError extends Error {
  declare readonly code: KimChatToolErrorCode

  constructor(code: KimChatToolErrorCode) {
    super('Kim chat tool request failed')
    this.name = 'KimChatToolError'
    Object.defineProperty(this, 'code', { enumerable: true, value: code })
  }
}

interface ToolExecutionLike {
  readonly signal: AbortSignal
}

export interface KimChatToolDefinition {
  readonly name: string
  readonly description: string
  readonly parameters: Record<string, unknown>
  readonly output: {
    readonly schema: Record<string, unknown>
    readonly render: (args: unknown, value: unknown) => Array<{ type: 'text', text: string }>
  }
  readonly timeoutMs: number
  execute(args: unknown, exec: ToolExecutionLike): Promise<unknown>
}

class EnvironmentChatkimProcessGateway implements ChatkimProcessGateway {
  private client: ChatkimClient | undefined
  private clientOpening: Promise<ChatkimClient> | undefined
  private disposed = false

  constructor(private readonly environment: NodeJS.ProcessEnv) {}

  async callTool(
    name: ChatkimReaderTool,
    args: Readonly<Record<string, unknown>>,
    signal?: AbortSignal,
  ): Promise<unknown> {
    if (this.disposed) throw new ChatkimClientError('CHATKIM_DISPOSED')
    const client = await this.getClient(signal)
    return client.callTool(name, args, signal)
  }

  async dispose(): Promise<void> {
    this.disposed = true
    const client = this.client ?? await this.clientOpening?.catch(() => undefined)
    if (client !== undefined) await client.dispose()
  }

  private async getClient(signal?: AbortSignal): Promise<ChatkimClient> {
    if (this.client !== undefined) return this.client
    if (this.clientOpening === undefined) {
      this.clientOpening = this.openClient(signal)
      void this.clientOpening.catch(() => { this.clientOpening = undefined })
    }
    return this.clientOpening
  }

  private async openClient(signal?: AbortSignal): Promise<ChatkimClient> {
    const executable = await resolveChatkimExecutable(this.environment, { signal })
    const home = this.environment.HOME?.trim()
    if (home === undefined || home === '') throw new ChatkimConfigError('CHATKIM_CONFIG_MISSING')
    const client = new ChatkimClient({ executable, home })
    if (this.disposed) {
      await client.dispose()
      throw new ChatkimClientError('CHATKIM_DISPOSED')
    }
    this.client = client
    return client
  }
}

function exactObject(value: unknown, allowedKeys: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
  }
  const object = value as Record<string, unknown>
  if (!Object.keys(object).every(key => allowedKeys.includes(key))) {
    throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
  }
  return object
}

function optionalString(
  object: Record<string, unknown>,
  key: string,
  maximum: number,
): string | undefined {
  const value = object[key]
  if (value === undefined) return undefined
  if (typeof value !== 'string') throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
  const trimmed = value.trim()
  if (trimmed === '' || trimmed.length > maximum || /[\u0000-\u001f\u007f]/.test(trimmed)) {
    throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
  }
  return trimmed
}

function requiredString(object: Record<string, unknown>, key: string, maximum: number): string {
  const value = optionalString(object, key, maximum)
  if (value === undefined) throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
  return value
}

function integer(
  object: Record<string, unknown>,
  key: string,
  fallback: number,
  minimum: number,
  maximum: number,
): number {
  const value = object[key] ?? fallback
  if (typeof value !== 'number' || !Number.isInteger(value) || value < minimum || value > maximum) {
    throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
  }
  return value
}

function mapError(error: unknown): KimChatToolError {
  if (error instanceof KimChatToolError) return error
  if (error instanceof KimChatProjectionError) return new KimChatToolError('KIM_CHAT_RESPONSE_INVALID')
  if (error instanceof ChatkimConfigError || error instanceof ChatkimClientError) {
    return new KimChatToolError(error.code)
  }
  if (error instanceof KimChatAccountError) return new KimChatToolError(error.code)
  return new KimChatToolError('KIM_CHAT_UNAVAILABLE')
}

function unavailableCapabilities() {
  return {
    currentUserIdentity: false,
    conversationIdentity: false,
    stableMessageIdentity: false,
    finalMessageText: false,
    authoritativeSender: false,
    timestampOrdering: false,
    durableIncrementalSync: false,
  }
}

function identityVerifiedCapabilities() {
  return {
    ...unavailableCapabilities(),
    currentUserIdentity: true,
  }
}

function output() {
  return {
    schema: { type: 'object' },
    render: (_args: unknown, value: unknown) => [{ type: 'text' as const, text: JSON.stringify(value) }],
  }
}

async function selfUserId(source: KimChatGateway, signal: AbortSignal): Promise<string> {
  return projectCurrentUser(await source.callTool('get_current_user', {}, signal)).userId
}

export function createEnvironmentKimChatGateway(
  environment: NodeJS.ProcessEnv = process.env,
): KimChatGateway {
  return new AccountScopedKimChatGateway(
    new EnvironmentChatkimProcessGateway(environment),
    environment.OMINIME_CHATKIM_ACCOUNT,
  )
}

export function createKimChatToolDefinitions(source: KimChatGateway): KimChatToolDefinition[] {
  return [
    {
      name: 'kim_chat_status',
      description: 'Check whether the restricted local Kim chat reader is available and read-only.',
      parameters: { type: 'object', properties: {}, additionalProperties: false },
      output: output(),
      timeoutMs: 10_000,
      async execute(args, exec) {
        exactObject(args, [])
        try {
          const proof = projectCurrentUser(await source.callTool('get_current_user', {}, exec.signal))
          return {
            status: 'healthy',
            adapterVersion: ADAPTER_VERSION,
            readOnly: proof.readOnly,
            schemaVerified: proof.schemaVerified,
            capabilities: identityVerifiedCapabilities(),
            error: null,
          }
        } catch (error) {
          const mapped = mapError(error)
          return {
            status: mapped.code === 'CHATKIM_CONFIG_MISSING' ? 'disabled' : 'degraded',
            adapterVersion: ADAPTER_VERSION,
            readOnly: false,
            schemaVerified: false,
            capabilities: unavailableCapabilities(),
            error: { code: mapped.code },
          }
        }
      },
    },
    {
      name: 'kim_chat_conversations',
      description: 'List a bounded page of recent Kim conversations without deleted sessions.',
      parameters: {
        type: 'object',
        additionalProperties: false,
        properties: {
          search: { type: 'string', maxLength: 256 },
          conversationType: { type: 'string', enum: ['all', 'group', 'private'] },
          limit: { type: 'integer', minimum: 1, maximum: 50 },
          offset: { type: 'integer', minimum: 0, maximum: 10_000 },
        },
      },
      output: output(),
      timeoutMs: 10_000,
      async execute(args, exec) {
        try {
          const object = exactObject(args, ['search', 'conversationType', 'limit', 'offset'])
          const search = optionalString(object, 'search', 256)
          const conversationType = optionalString(object, 'conversationType', 16) ?? 'all'
          if (!['all', 'group', 'private'].includes(conversationType)) {
            throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
          }
          const readerArgs: Record<string, unknown> = {
            conversation_type: conversationType,
            include_deleted: false,
            limit: integer(object, 'limit', 20, 1, 50),
            offset: integer(object, 'offset', 0, 0, 10_000),
          }
          if (search !== undefined) readerArgs.search = search
          return projectConversations(await source.callTool('list_conversations', readerArgs, exec.signal))
        } catch (error) {
          throw mapError(error)
        }
      },
    },
    {
      name: 'kim_chat_messages',
      description: 'Query a bounded chronological page of Kim messages in one exact conversation.',
      parameters: {
        type: 'object',
        additionalProperties: false,
        required: ['conversationId'],
        properties: {
          conversationId: { type: 'string', minLength: 1, maxLength: 512 },
          timeRange: { type: 'string', maxLength: 64 },
          keyword: { type: 'string', maxLength: 256 },
          limit: { type: 'integer', minimum: 1, maximum: 50 },
          cursor: { type: 'string', maxLength: 4_096 },
        },
      },
      output: output(),
      timeoutMs: 10_000,
      async execute(args, exec) {
        try {
          const object = exactObject(args, ['conversationId', 'timeRange', 'keyword', 'limit', 'cursor'])
          const conversationId = requiredString(object, 'conversationId', 512)
          const timeRange = optionalString(object, 'timeRange', 64)
          if (timeRange !== undefined && !SAFE_TIME_RANGES.has(timeRange) && !DATE_RANGE_PATTERN.test(timeRange)) {
            throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
          }
          const keyword = optionalString(object, 'keyword', 256)
          const cursor = optionalString(object, 'cursor', 4_096)
          if (cursor !== undefined && (!CURSOR_PATTERN.test(cursor) || cursor.length % 2 !== 0)) {
            throw new KimChatToolError('KIM_CHAT_INVALID_ARGUMENTS')
          }
          const readerArgs: Record<string, unknown> = {
            conversation_ids: [conversationId],
            limit: integer(object, 'limit', 50, 1, 50),
            order_direction: 'asc',
            include_deleted: false,
          }
          if (timeRange !== undefined) readerArgs.time_range = timeRange
          if (keyword !== undefined) readerArgs.keyword = keyword
          if (cursor !== undefined) readerArgs.cursor = cursor
          const userId = await selfUserId(source, exec.signal)
          return projectMessages(
            await source.callTool('query_chat_log', readerArgs, exec.signal),
            userId,
          )
        } catch (error) {
          throw mapError(error)
        }
      },
    },
    {
      name: 'kim_chat_context',
      description: 'Read bounded chronological context around one exact Kim message.',
      parameters: {
        type: 'object',
        additionalProperties: false,
        required: ['messageId'],
        properties: {
          messageId: { type: 'string', minLength: 1, maxLength: 512 },
          before: { type: 'integer', minimum: 1, maximum: 50 },
          after: { type: 'integer', minimum: 1, maximum: 50 },
        },
      },
      output: output(),
      timeoutMs: 10_000,
      async execute(args, exec) {
        try {
          const object = exactObject(args, ['messageId', 'before', 'after'])
          const messageId = requiredString(object, 'messageId', 512)
          const readerArgs = {
            message_id: messageId,
            before: integer(object, 'before', 10, 1, 50),
            after: integer(object, 'after', 10, 1, 50),
            include_deleted: false,
          }
          const userId = await selfUserId(source, exec.signal)
          return projectContext(
            await source.callTool('get_message_context', readerArgs, exec.signal),
            userId,
          )
        } catch (error) {
          throw mapError(error)
        }
      },
    },
  ]
}

export function registerKimChatTools(ctx: Context, source: KimChatGateway): void {
  for (const definition of createKimChatToolDefinitions(source)) ctx.tools.register(definition)
}
