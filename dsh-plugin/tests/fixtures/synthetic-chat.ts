import {
  SourceIncompatibleError,
  type SourceConnector,
} from '../../src/connectors/contract.ts'
import type {
  ConversationPage,
  ConversationRef,
  MessageChangePage,
  MessagePage,
  SourceAccount,
  SourceCapabilities,
  SourceConversation,
  SourceHealth,
  SourceMessageChange,
} from '../../src/domain/types.ts'

const SOURCE = 'synthetic-chat'
const ACCOUNT_ID = 'account-self'
const CONVERSATION_CURSOR = 'opaque:8UmC5bVG'
const MESSAGE_CURSOR = 'opaque:k9N4tQ2x'

const capabilities: SourceCapabilities = {
  edits: true,
  retractions: true,
  replyLinks: true,
  deletes: true,
}

const accounts: readonly SourceAccount[] = [{
  source: SOURCE,
  accountId: ACCOUNT_ID,
  selfParticipantIds: ['participant-self'],
  adapterVersion: 'synthetic-v1',
}]

const conversations: readonly SourceConversation[] = [
  {
    source: SOURCE,
    accountId: ACCOUNT_ID,
    conversationId: 'conversation-one',
    participantIds: ['participant-self', 'participant-other'],
    sourceOrder: '1',
    sourceTimestamp: '2026-08-17T12:00:00.000Z',
  },
  {
    source: SOURCE,
    accountId: ACCOUNT_ID,
    conversationId: 'conversation-two',
    participantIds: ['participant-self', 'participant-other'],
    sourceOrder: '2',
    sourceTimestamp: '2026-08-17T12:01:00.000Z',
  },
]

export const syntheticMessageBodies = [
  'synthetic self body',
  'synthetic other body',
  'synthetic system body',
  'synthetic unknown body',
] as const

const messageChanges: readonly SourceMessageChange[] = [
  {
    source: SOURCE,
    accountId: ACCOUNT_ID,
    conversationId: 'conversation-one',
    messageId: 'message-self',
    authorId: 'participant-self',
    direction: 'self',
    kind: 'create',
    text: syntheticMessageBodies[0],
    replyToMessageId: null,
    sourceOrder: '1',
    sourceTimestamp: '2026-08-17T12:00:00.000Z',
    observedAt: '2026-08-17T12:02:00.000Z',
  },
  {
    source: SOURCE,
    accountId: ACCOUNT_ID,
    conversationId: 'conversation-one',
    messageId: 'message-other',
    authorId: 'participant-other',
    direction: 'other',
    kind: 'edit',
    text: syntheticMessageBodies[1],
    replyToMessageId: 'message-self',
    sourceOrder: '2',
    sourceTimestamp: '2026-08-17T12:00:10.000Z',
    observedAt: '2026-08-17T12:02:00.000Z',
  },
  {
    source: SOURCE,
    accountId: ACCOUNT_ID,
    conversationId: 'conversation-one',
    messageId: 'message-system',
    authorId: null,
    direction: 'system',
    kind: 'retract',
    text: syntheticMessageBodies[2],
    replyToMessageId: null,
    sourceOrder: '3',
    sourceTimestamp: '2026-08-17T12:00:20.000Z',
    observedAt: '2026-08-17T12:02:00.000Z',
  },
  {
    source: SOURCE,
    accountId: ACCOUNT_ID,
    conversationId: 'conversation-one',
    messageId: 'message-unknown',
    authorId: null,
    direction: 'unknown',
    kind: 'delete',
    text: null,
    replyToMessageId: null,
    sourceOrder: '4',
    sourceTimestamp: '2026-08-17T12:00:30.000Z',
    observedAt: '2026-08-17T12:02:00.000Z',
  },
]

function assertCompatible(incompatible: boolean): void {
  if (!incompatible) return
  throw new SourceIncompatibleError({
    source: SOURCE,
    adapterVersion: 'synthetic-v1',
    observedVersion: 'synthetic-v2',
    reason: 'UNSUPPORTED_SOURCE_VERSION',
  })
}

export function createSyntheticConnector({
  id = SOURCE,
  incompatible = false,
}: {
  id?: string
  incompatible?: boolean
} = {}): SourceConnector {
  return {
    id,
    async discoverAccounts(signal: AbortSignal): Promise<SourceAccount[]> {
      signal.throwIfAborted()
      assertCompatible(incompatible)
      return [...structuredClone(accounts)]
    },
    async discoverConversations(cursor: string | null, signal: AbortSignal): Promise<ConversationPage> {
      signal.throwIfAborted()
      assertCompatible(incompatible)
      if (cursor === null) {
        return { conversations: structuredClone(conversations.slice(0, 1)), nextCursor: CONVERSATION_CURSOR }
      }
      if (cursor === CONVERSATION_CURSOR) {
        return { conversations: structuredClone(conversations.slice(1)), nextCursor: null }
      }
      throw new Error('invalid synthetic conversation cursor')
    },
    async syncMessages(
      _ref: ConversationRef,
      cursor: string | null,
      signal: AbortSignal,
    ): Promise<MessageChangePage> {
      signal.throwIfAborted()
      assertCompatible(incompatible)
      if (cursor === null) {
        return { changes: structuredClone(messageChanges.slice(0, 2)), nextCursor: MESSAGE_CURSOR }
      }
      if (cursor === MESSAGE_CURSOR) {
        return { changes: structuredClone(messageChanges.slice(2)), nextCursor: null }
      }
      throw new Error('invalid synthetic message cursor')
    },
    async backfill(
      _ref: ConversationRef,
      boundary: string | null,
      signal: AbortSignal,
    ): Promise<MessagePage> {
      signal.throwIfAborted()
      assertCompatible(incompatible)
      if (boundary !== null) throw new Error('invalid synthetic backfill boundary')
      return { messages: [...structuredClone(messageChanges)], nextBoundary: null }
    },
    health(): SourceHealth {
      return {
        source: SOURCE,
        status: incompatible ? 'incompatible' : 'healthy',
        adapterVersion: 'synthetic-v1',
        checkedAt: '2026-08-17T12:02:00.000Z',
        lastSuccessfulSyncAt: incompatible ? null : '2026-08-17T12:01:00.000Z',
        capabilities,
        error: incompatible
          ? { code: 'SOURCE_INCOMPATIBLE' }
          : null,
      }
    },
  }
}

export const syntheticConversationRef: ConversationRef = {
  source: SOURCE,
  accountId: ACCOUNT_ID,
  conversationId: 'conversation-one',
}
