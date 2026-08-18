export class KimChatProjectionError extends Error {
  constructor() {
    super('Kim chat reader response does not match the approved schema')
    this.name = 'KimChatProjectionError'
  }
}

interface CurrentUserProjection {
  readonly userId: string
  readonly readOnly: true
  readonly schemaVerified: true
}

const SYSTEM_CONTENT_TYPES = new Set([100, 101, 200])

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new KimChatProjectionError()
  }
  return value as Record<string, unknown>
}

function string(value: unknown, maximum = 65_536): string {
  if (typeof value !== 'string' || value.length > maximum) throw new KimChatProjectionError()
  return value
}

function nonemptyString(value: unknown, maximum = 512): string {
  const result = string(value, maximum)
  if (result.length === 0) throw new KimChatProjectionError()
  return result
}

function integer(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) throw new KimChatProjectionError()
  return value
}

function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new KimChatProjectionError()
  return value
}

function nullableString(value: unknown, maximum = 4_096): string | null {
  return value === null || value === undefined ? null : string(value, maximum)
}

function array(value: unknown, maximum: number): unknown[] {
  if (!Array.isArray(value) || value.length > maximum) throw new KimChatProjectionError()
  return value
}

export function projectCurrentUser(value: unknown): CurrentUserProjection {
  const root = record(value)
  const user = record(root.current_user)
  const connection = record(root.database_connection)
  const userId = nonemptyString(user.user_id)
  if (connection.connected !== true || connection.read_only !== true || connection.schema_verified !== true) {
    throw new KimChatProjectionError()
  }
  return Object.freeze({ userId, readOnly: true, schemaVerified: true })
}

export function projectConversations(value: unknown) {
  const root = record(value)
  const conversations = array(root.conversations, 50).map(candidate => {
    const conversation = record(candidate)
    return {
      conversationId: nonemptyString(conversation.conversation_id),
      type: nonemptyString(conversation.conversation_type, 32),
      name: string(conversation.conversation_name, 1_024),
      activeTimestampMs: integer(conversation.active_time_ms),
      activeAt: nullableString(conversation.active_at, 64),
      unreadCount: integer(conversation.unread_count),
    }
  })
  return {
    conversations,
    returned: integer(root.returned),
    hasMore: boolean(root.has_more),
    truncated: boolean(root.scan_truncated),
  }
}

function projectMessage(value: unknown, selfUserId: string) {
  const message = record(value)
  const contentType = integer(message.content_type)
  const authorId = string(message.sender_id, 512)
  const direction = SYSTEM_CONTENT_TYPES.has(contentType)
    ? 'system'
    : authorId === selfUserId
      ? 'self'
      : 'other'
  return {
    messageId: nonemptyString(message.id),
    providerMessageId: string(message.msg_id, 512),
    timestampMs: integer(message.timestamp_ms),
    timestamp: string(message.date, 64),
    authorId,
    authorName: string(message.sender_name, 1_024),
    direction,
    conversationId: nonemptyString(message.conversation_id),
    conversationName: string(message.conversation_name, 1_024),
    conversationType: nonemptyString(message.conversation_type, 32),
    text: string(message.content),
    contentType,
    contentTypeName: string(message.content_type_name, 128),
  }
}

export function projectMessages(value: unknown, selfUserId: string) {
  const root = record(value)
  const page = record(root.pagination)
  return {
    messages: array(root.messages, 50).map(message => projectMessage(message, selfUserId)),
    page: {
      returned: integer(page.returned),
      hasMore: boolean(page.has_more),
      nextCursor: nullableString(page.next_cursor),
    },
  }
}

export function projectContext(value: unknown, selfUserId: string) {
  const root = record(value)
  const anchor = record(root.anchor)
  return {
    anchorMessageId: nonemptyString(anchor.requested_id),
    beforeReturned: integer(root.before_returned),
    afterReturned: integer(root.after_returned),
    chronological: boolean(root.chronological),
    messages: array(root.messages, 101).map(message => projectMessage(message, selfUserId)),
  }
}
