import { describe, expect, it, vi } from 'vitest'

import { ChatkimConfigError } from '../src/chatkim/config.ts'
import type { ChatkimReaderTool } from '../src/chatkim/client.ts'
import {
  createKimChatToolDefinitions,
  KimChatToolError,
  type KimChatGateway,
} from '../src/chatkim/tools.ts'
import { apply } from '../src/index.ts'

const controller = new AbortController()
const exec = { signal: controller.signal } as never

function currentUser() {
  return {
    account_id: 'private-account',
    current_user: {
      user_id: 'self-1',
      display_name: 'Private User',
      username: 'private',
      active: true,
    },
    database_connection: {
      connected: true,
      read_only: true,
      schema_verified: true,
      file: '/private/path/users.db',
      cipher_version: 'private-cipher',
    },
  }
}

function gateway(overrides: Partial<KimChatGateway> = {}): KimChatGateway & { calls: ReturnType<typeof vi.fn> } {
  const calls = vi.fn(async (name: ChatkimReaderTool, args: Readonly<Record<string, unknown>>) => {
    if (name === 'get_current_user') return currentUser()
    if (name === 'list_conversations') {
      return {
        account_id: 'private-account',
        conversations: [{
          session_id: 'session-private',
          conversation_id: 'conversation-1',
          conversation_type: 'group',
          conversation_name: 'Synthetic Project',
          active_time_ms: 1_755_000_000_000,
          active_at: '2025-08-10T00:00:00.000Z',
          unread_count: 3,
          muted: false,
          marked_unread: false,
          deleted: false,
          private_path: '/not/allowed',
        }],
        returned: 1,
        has_more: false,
        scan_truncated: false,
      }
    }
    const messages = [
      {
        id: 'message-self',
        msg_id: 'provider-self',
        timestamp_ms: 1_755_000_000_001,
        date: '2025-08-10T00:00:00.001Z',
        sender_id: 'self-1',
        sender_name: 'Private User',
        conversation_id: 'conversation-1',
        conversation_name: 'Synthetic Project',
        conversation_type: 'group',
        content: 'Synthetic self text',
        content_type: 0,
        content_type_name: 'text',
        source_shard: '/private/path/messages.db',
      },
      {
        id: 'message-other',
        msg_id: 'provider-other',
        timestamp_ms: 1_755_000_000_002,
        date: '2025-08-10T00:00:00.002Z',
        sender_id: 'other-1',
        sender_name: 'Synthetic Other',
        conversation_id: 'conversation-1',
        conversation_name: 'Synthetic Project',
        conversation_type: 'group',
        content: 'Synthetic other text',
        content_type: 0,
        content_type_name: 'text',
        source_shard: '/private/path/messages.db',
      },
      {
        id: 'message-system',
        msg_id: 'provider-system',
        timestamp_ms: 1_755_000_000_003,
        date: '2025-08-10T00:00:00.003Z',
        sender_id: '',
        sender_name: '',
        conversation_id: 'conversation-1',
        conversation_name: 'Synthetic Project',
        conversation_type: 'group',
        content: 'Synthetic system event',
        content_type: 101,
        content_type_name: 'recall',
        source_shard: '/private/path/messages.db',
      },
    ]
    if (name === 'get_message_context') {
      return {
        account_id: 'private-account',
        anchor: { requested_id: 'message-self', source_shard: '/private/path/messages.db' },
        before_returned: 0,
        after_returned: 2,
        chronological: true,
        messages,
      }
    }
    return {
      account_id: 'private-account',
      messages,
      pagination: { returned: 3, scanned: 3, has_more: true, next_cursor: 'opaque-cursor', limit: 3 },
      query_summary: { private_path: '/private/path' },
    }
  })
  return { calls, callTool: calls, dispose: vi.fn(async () => {}), ...overrides }
}

function definitions(source: KimChatGateway = gateway()) {
  return new Map(createKimChatToolDefinitions(source).map(definition => [definition.name, definition]))
}

describe('restricted Kim chat DSH tools', () => {
  it('wires the four tools and one lifecycle cleanup into the Host plugin', async () => {
    const names: string[] = []
    const skillNames: string[] = []
    const cleanups: Array<() => void | Promise<void>> = []
    apply({
      tools: {
        register(definition: { name: string }) {
          names.push(definition.name)
          return () => {}
        },
      },
      skills: {
        register(definition: { name: string }) {
          skillNames.push(definition.name)
          return () => {}
        },
      },
      effect(factory: () => void | (() => void | Promise<void>)) {
        const cleanup = factory()
        if (typeof cleanup === 'function') cleanups.push(cleanup)
      },
    } as never)

    expect(names.sort()).toEqual([
      'kim_chat_context',
      'kim_chat_conversations',
      'kim_chat_messages',
      'kim_chat_status',
      'personal_context_health',
    ])
    expect(skillNames).toEqual(['kim-chat-history'])
    expect(cleanups).toHaveLength(1)
    await cleanups[0]!()
  })

  it('registers exactly four closed input schemas', () => {
    const tools = definitions()
    expect([...tools.keys()].sort()).toEqual([
      'kim_chat_context',
      'kim_chat_conversations',
      'kim_chat_messages',
      'kim_chat_status',
    ])
    for (const definition of tools.values()) {
      expect(definition.parameters).toMatchObject({ type: 'object', additionalProperties: false })
    }
  })

  it('returns sanitized healthy status without identity, path, or cipher details', async () => {
    const status = await definitions().get('kim_chat_status')!.execute({}, exec)
    expect(status).toEqual({
      status: 'healthy',
      adapterVersion: 'chatkimv2-mcp-v1',
      readOnly: true,
      schemaVerified: true,
      capabilities: {
        currentUserIdentity: true,
        conversationIdentity: false,
        stableMessageIdentity: false,
        finalMessageText: false,
        authoritativeSender: false,
        timestampOrdering: false,
        durableIncrementalSync: false,
      },
      error: null,
    })
    expect(JSON.stringify(status)).not.toMatch(/self-1|private|cipher|users\.db/)
  })

  it('reports missing configuration as disabled with only one fixed code', async () => {
    const source = gateway({
      callTool: vi.fn(async () => { throw new ChatkimConfigError('CHATKIM_CONFIG_MISSING') }),
    })
    await expect(definitions(source).get('kim_chat_status')!.execute({}, exec)).resolves.toEqual({
      status: 'disabled',
      adapterVersion: 'chatkimv2-mcp-v1',
      readOnly: false,
      schemaVerified: false,
      capabilities: {
        currentUserIdentity: false,
        conversationIdentity: false,
        stableMessageIdentity: false,
        finalMessageText: false,
        authoritativeSender: false,
        timestampOrdering: false,
        durableIncrementalSync: false,
      },
      error: { code: 'CHATKIM_CONFIG_MISSING' },
    })
  })

  it('rejects unknown arguments before invoking the reader', async () => {
    const source = gateway()
    const tool = definitions(source).get('kim_chat_messages')!
    await expect(tool.execute({ conversationId: 'conversation-1', extra: true }, exec)).rejects.toMatchObject({
      code: 'KIM_CHAT_INVALID_ARGUMENTS',
    })
    expect(source.calls).not.toHaveBeenCalled()
  })

  it('projects bounded conversations and removes source-private fields', async () => {
    const source = gateway()
    const result = await definitions(source).get('kim_chat_conversations')!.execute({
      search: 'Synthetic',
      conversationType: 'group',
      limit: 5,
      offset: 0,
    }, exec)
    expect(result).toEqual({
      conversations: [{
        conversationId: 'conversation-1',
        type: 'group',
        name: 'Synthetic Project',
        activeTimestampMs: 1_755_000_000_000,
        activeAt: '2025-08-10T00:00:00.000Z',
        unreadCount: 3,
      }],
      returned: 1,
      hasMore: false,
      truncated: false,
    })
    expect(source.calls).toHaveBeenCalledWith('list_conversations', {
      search: 'Synthetic',
      conversation_type: 'group',
      include_deleted: false,
      limit: 5,
      offset: 0,
    }, controller.signal)
    expect(JSON.stringify(result)).not.toMatch(/session-private|private-account|private_path/)
  })

  it('projects messages with authoritative self, other, and system directions', async () => {
    const source = gateway()
    const result = await definitions(source).get('kim_chat_messages')!.execute({
      conversationId: 'conversation-1',
      timeRange: 'recent_7days',
      limit: 3,
    }, exec) as { messages: Array<{ direction: string }>, page: unknown }
    expect(result.messages.map(message => message.direction)).toEqual(['self', 'other', 'system'])
    expect(result.page).toEqual({ returned: 3, hasMore: true, nextCursor: 'opaque-cursor' })
    expect(source.calls).toHaveBeenNthCalledWith(1, 'get_current_user', {}, controller.signal)
    expect(source.calls).toHaveBeenNthCalledWith(2, 'query_chat_log', {
      conversation_ids: ['conversation-1'],
      time_range: 'recent_7days',
      limit: 3,
      order_direction: 'asc',
      include_deleted: false,
    }, controller.signal)
    expect(JSON.stringify(result)).not.toMatch(/source_shard|private\/path|query_summary/)
  })

  it('projects bounded chronological context and strips anchor internals', async () => {
    const source = gateway()
    const result = await definitions(source).get('kim_chat_context')!.execute({
      messageId: 'message-self',
      before: 2,
      after: 2,
    }, exec) as Record<string, unknown>
    expect(result).toMatchObject({
      anchorMessageId: 'message-self',
      beforeReturned: 0,
      afterReturned: 2,
      chronological: true,
    })
    expect(JSON.stringify(result)).not.toMatch(/source_shard|private\/path|private-account/)
  })

  it('fails closed on an incomplete reader response', async () => {
    const source = gateway({ callTool: vi.fn(async () => ({ messages: [{}] })) })
    const error = await definitions(source).get('kim_chat_messages')!.execute({
      conversationId: 'conversation-1',
    }, exec).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(KimChatToolError)
    expect(error).toMatchObject({ code: 'KIM_CHAT_RESPONSE_INVALID' })
    expect(String(error)).not.toContain('messages')
  })
})
