export type MessageDirection = 'self' | 'other' | 'system' | 'unknown'
export type MessageChangeKind = 'create' | 'edit' | 'retract' | 'delete'

export interface SourceCapabilities {
  edits: boolean
  retractions: boolean
  replyLinks: boolean
  deletes: boolean
}

export interface SourceAccount {
  source: string
  accountId: string
  selfParticipantIds: string[]
  adapterVersion: string
}

export interface ConversationRef {
  source: string
  accountId: string
  conversationId: string
}

export interface SourceConversation extends ConversationRef {
  participantIds: string[]
  sourceOrder: string
  sourceTimestamp: string
}

export interface ConversationPage {
  conversations: SourceConversation[]
  nextCursor: string | null
}

export interface SourceMessageChange {
  source: string
  accountId: string
  conversationId: string
  messageId: string
  authorId: string | null
  direction: MessageDirection
  kind: MessageChangeKind
  text: string | null
  replyToMessageId: string | null
  sourceOrder: string
  sourceTimestamp: string
  observedAt: string
}

export interface MessageChangePage {
  changes: SourceMessageChange[]
  nextCursor: string | null
}

export interface MessagePage {
  messages: SourceMessageChange[]
  nextBoundary: string | null
}

export type SourceHealthStatus = 'healthy' | 'degraded' | 'disabled' | 'incompatible'

export interface SourceHealthError {
  code: string
}

export interface SourceHealth {
  source: string
  status: SourceHealthStatus
  adapterVersion: string
  checkedAt: string
  lastSuccessfulSyncAt: string | null
  capabilities: SourceCapabilities
  error: SourceHealthError | null
}
