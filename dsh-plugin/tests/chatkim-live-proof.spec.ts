import { describe, expect, it, vi } from 'vitest'

import { ChatkimClientError } from '../src/chatkim/client.ts'
import { probeKimChatCapabilities } from '../src/chatkim/live-proof.ts'
import type { KimChatGateway } from '../src/chatkim/tools.ts'

const privateMarkers = [
  'private-user-id',
  'private-conversation-id',
  'private-message-id',
  'private message body',
  '/private/database/path',
]

function gateway(overrides: Partial<KimChatGateway> = {}): KimChatGateway & { callTool: ReturnType<typeof vi.fn> } {
  return {
    callTool: vi.fn(async (name: string) => {
      if (name === 'get_current_user') {
        return {
          current_user: { user_id: 'private-user-id' },
          database_connection: {
            connected: true,
            read_only: true,
            schema_verified: true,
            path: '/private/database/path',
          },
        }
      }
      if (name === 'list_conversations') {
        return {
          conversations: [{
            conversation_id: 'private-conversation-id',
            conversation_type: 'private',
            conversation_name: 'Private Person',
            active_time_ms: 1_755_000_000_000,
            active_at: '2025-08-10T00:00:00.000Z',
            unread_count: 0,
          }],
          returned: 1,
          has_more: false,
          scan_truncated: false,
        }
      }
      return {
        messages: [{
          id: 'private-message-id',
          msg_id: 'provider-private-message-id',
          timestamp_ms: 1_755_000_000_000,
          date: '2025-08-10T00:00:00.000Z',
          sender_id: 'private-user-id',
          sender_name: 'Private User',
          conversation_id: 'private-conversation-id',
          conversation_name: 'Private Person',
          conversation_type: 'private',
          content: 'private message body',
          content_type: 0,
          content_type_name: 'text',
        }],
        pagination: { returned: 1, has_more: false, next_cursor: null },
      }
    }),
    dispose: vi.fn(async () => {}),
    ...overrides,
  }
}

describe('redacted Kim chat live proof', () => {
  it('proves only bounded capabilities and emits no source values', async () => {
    const source = gateway()
    const report = await probeKimChatCapabilities(source)

    expect(report).toEqual({
      gate: 'PASS',
      adapterVersionClass: 'chatkimv2-mcp-v1',
      capabilities: {
        currentUserIdentity: true,
        conversationIdentity: true,
        stableMessageIdentity: true,
        finalMessageText: true,
        authoritativeSender: true,
        timestampOrdering: true,
        durableIncrementalSync: false,
      },
      failureCodes: [],
    })
    for (const marker of privateMarkers) expect(JSON.stringify(report)).not.toContain(marker)
    expect(source.callTool).toHaveBeenNthCalledWith(2, 'list_conversations', {
      conversation_type: 'all',
      include_deleted: false,
      limit: 5,
      offset: 0,
    }, expect.any(AbortSignal))
    expect(source.callTool).toHaveBeenNthCalledWith(3, 'query_chat_log', {
      conversation_ids: ['private-conversation-id'],
      time_range: 'recent_30days',
      limit: 2,
      order_direction: 'asc',
      include_deleted: false,
    }, expect.any(AbortSignal))
  })

  it('blocks without inventing message capabilities when no message is observed', async () => {
    const source = gateway({
      callTool: vi.fn(async (name: string) => {
        if (name === 'get_current_user') {
          return {
            current_user: { user_id: 'private-user-id' },
            database_connection: { connected: true, read_only: true, schema_verified: true },
          }
        }
        return { conversations: [], returned: 0, has_more: false, scan_truncated: false }
      }),
    })
    const report = await probeKimChatCapabilities(source)
    expect(report.gate).toBe('BLOCK')
    expect(report.capabilities.currentUserIdentity).toBe(true)
    expect(report.capabilities.conversationIdentity).toBe(false)
    expect(report.failureCodes).toEqual(['KIM_CHAT_LIVE_PROOF_INCOMPLETE'])
  })

  it('does not prove final text or sender from an empty system-only observation', async () => {
    const source = gateway()
    const original = source.callTool.getMockImplementation()!
    source.callTool.mockImplementation(async (name: string, args: Record<string, unknown>, signal: AbortSignal) => {
      if (name !== 'query_chat_log') return original(name, args, signal)
      return {
        messages: [{
          id: 'private-message-id',
          msg_id: 'provider-private-message-id',
          timestamp_ms: 1_755_000_000_000,
          date: '2025-08-10T00:00:00.000Z',
          sender_id: '',
          sender_name: '',
          conversation_id: 'private-conversation-id',
          conversation_name: 'Private Person',
          conversation_type: 'private',
          content: '',
          content_type: 101,
          content_type_name: 'system',
        }],
        pagination: { returned: 1, has_more: false, next_cursor: null },
      }
    })

    const report = await probeKimChatCapabilities(source)
    expect(report.gate).toBe('BLOCK')
    expect(report.capabilities.finalMessageText).toBe(false)
    expect(report.capabilities.authoritativeSender).toBe(false)
  })

  it('converts unknown failures to one fixed redacted code', async () => {
    const source = gateway({ callTool: vi.fn(async () => { throw new Error('private failure detail') }) })
    const report = await probeKimChatCapabilities(source)
    expect(report).toMatchObject({ gate: 'BLOCK', failureCodes: ['KIM_CHAT_LIVE_PROOF_FAILED'] })
    expect(JSON.stringify(report)).not.toContain('private failure detail')
  })

  it('preserves only an existing fixed client code for diagnosis', async () => {
    const source = gateway({
      callTool: vi.fn(async () => { throw new ChatkimClientError('CHATKIM_READER_REJECTED') }),
    })
    const report = await probeKimChatCapabilities(source)
    expect(report).toMatchObject({ gate: 'BLOCK', failureCodes: ['CHATKIM_READER_REJECTED'] })
  })
})
