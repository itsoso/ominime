import type {
  ConversationPage,
  ConversationRef,
  MessageChangePage,
  MessagePage,
  SourceAccount,
  SourceHealth,
} from '../domain/types.ts'

export interface SourceConnector {
  readonly id: string
  discoverAccounts(signal: AbortSignal): Promise<SourceAccount[]>
  discoverConversations(cursor: string | null, signal: AbortSignal): Promise<ConversationPage>
  syncMessages(
    ref: ConversationRef,
    cursor: string | null,
    signal: AbortSignal,
  ): Promise<MessageChangePage>
  backfill(
    ref: ConversationRef,
    boundary: string | null,
    signal: AbortSignal,
  ): Promise<MessagePage>
  health(): SourceHealth
}

export interface SourceIncompatibleMetadata {
  source: string
  adapterVersion: string
  observedVersion: string | null
  reason: string
}

export class SourceIncompatibleError extends Error {
  declare readonly code: 'SOURCE_INCOMPATIBLE'
  declare readonly metadata: Readonly<SourceIncompatibleMetadata>

  constructor(metadata: SourceIncompatibleMetadata) {
    super(`source ${JSON.stringify(metadata.source)} is incompatible with adapter ${JSON.stringify(metadata.adapterVersion)}`)
    this.name = 'SourceIncompatibleError'
    Object.defineProperties(this, {
      code: {
        enumerable: true,
        value: 'SOURCE_INCOMPATIBLE',
      },
      metadata: {
        enumerable: true,
        value: Object.freeze({ ...metadata }),
      },
    })
  }
}
