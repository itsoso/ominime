import {
  KimChatProjectionError,
  projectConversations,
  projectCurrentUser,
  projectMessages,
} from './project.ts'
import { ChatkimClientError } from './client.ts'
import { ChatkimConfigError } from './config.ts'
import {
  createEnvironmentKimChatGateway,
  type KimChatGateway,
} from './tools.ts'
import { KimChatAccountError } from './account.ts'

const ADAPTER_VERSION_CLASS = 'chatkimv2-mcp-v1'
const FAILURE_INCOMPLETE = 'KIM_CHAT_LIVE_PROOF_INCOMPLETE'
const FAILURE_FAILED = 'KIM_CHAT_LIVE_PROOF_FAILED'

interface CapabilityReport {
  currentUserIdentity: boolean
  conversationIdentity: boolean
  stableMessageIdentity: boolean
  finalMessageText: boolean
  authoritativeSender: boolean
  timestampOrdering: boolean
  durableIncrementalSync: false
}

export interface KimChatLiveProofReport {
  readonly gate: 'PASS' | 'BLOCK'
  readonly adapterVersionClass: typeof ADAPTER_VERSION_CLASS
  readonly capabilities: Readonly<CapabilityReport>
  readonly failureCodes: readonly string[]
}

function emptyCapabilities(): CapabilityReport {
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

function report(capabilities: CapabilityReport, failureCodes: readonly string[]): KimChatLiveProofReport {
  return Object.freeze({
    gate: failureCodes.length === 0 ? 'PASS' : 'BLOCK',
    adapterVersionClass: ADAPTER_VERSION_CLASS,
    capabilities: Object.freeze({ ...capabilities }),
    failureCodes: Object.freeze([...failureCodes]),
  })
}

function failureCode(error: unknown): string {
  if (error instanceof ChatkimClientError || error instanceof ChatkimConfigError) return error.code
  if (error instanceof KimChatAccountError) return error.code
  if (error instanceof KimChatProjectionError) return 'KIM_CHAT_RESPONSE_INVALID'
  return FAILURE_FAILED
}

export async function probeKimChatCapabilities(
  source: KimChatGateway,
  signal: AbortSignal = AbortSignal.timeout(30_000),
): Promise<KimChatLiveProofReport> {
  const capabilities = emptyCapabilities()
  try {
    const currentUser = projectCurrentUser(await source.callTool('get_current_user', {}, signal))
    capabilities.currentUserIdentity = true

    const conversations = projectConversations(await source.callTool('list_conversations', {
      conversation_type: 'all',
      include_deleted: false,
      limit: 5,
      offset: 0,
    }, signal))
    capabilities.conversationIdentity = conversations.conversations.length > 0

    for (const conversation of conversations.conversations) {
      const page = projectMessages(await source.callTool('query_chat_log', {
        conversation_ids: [conversation.conversationId],
        time_range: 'recent_30days',
        limit: 2,
        order_direction: 'asc',
        include_deleted: false,
      }, signal), currentUser.userId)
      if (page.messages.length === 0) continue

      capabilities.stableMessageIdentity = page.messages.every(message => message.messageId.length > 0)
      capabilities.finalMessageText = page.messages.every(message => typeof message.text === 'string')
      capabilities.authoritativeSender = page.messages.every(
        message => message.direction === 'self' || message.direction === 'other' || message.direction === 'system',
      )
      capabilities.timestampOrdering = page.messages.every(
        (message, index) => index === 0 || page.messages[index - 1]!.timestampMs <= message.timestampMs,
      )
      break
    }

    const onDemandComplete = Object.entries(capabilities)
      .filter(([name]) => name !== 'durableIncrementalSync')
      .every(([, available]) => available)
    return report(capabilities, onDemandComplete ? [] : [FAILURE_INCOMPLETE])
  } catch (error) {
    return report(capabilities, [failureCode(error)])
  }
}

export async function runChatkimLiveProofCli(): Promise<number> {
  const source = createEnvironmentKimChatGateway()
  try {
    const proof = await probeKimChatCapabilities(source)
    process.stdout.write(`${JSON.stringify(proof)}\n`)
    return proof.gate === 'PASS' ? 0 : 2
  } finally {
    await source.dispose()
  }
}
