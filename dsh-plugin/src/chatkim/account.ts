import type { ChatkimQueryTool, ChatkimReaderTool } from './client.ts'
import { projectCurrentUser } from './project.ts'

const ACCOUNT_ID = /^\d{1,64}$/
const MAX_DISCOVERED_ACCOUNTS = 16

export type KimChatAccountErrorCode =
  | 'CHATKIM_ACCOUNT_INVALID'
  | 'CHATKIM_ACCOUNT_AMBIGUOUS'
  | 'CHATKIM_ACCOUNT_RESPONSE_INVALID'

export class KimChatAccountError extends Error {
  declare readonly code: KimChatAccountErrorCode

  constructor(code: KimChatAccountErrorCode) {
    super('Kim chat account selection failed')
    this.name = 'KimChatAccountError'
    Object.defineProperty(this, 'code', { enumerable: true, value: code })
  }
}

export interface ChatkimProcessGateway {
  callTool(
    name: ChatkimReaderTool,
    args: Readonly<Record<string, unknown>>,
    signal?: AbortSignal,
  ): Promise<unknown>
  dispose(): Promise<void>
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new KimChatAccountError('CHATKIM_ACCOUNT_RESPONSE_INVALID')
  }
  return value as Record<string, unknown>
}

function accountIds(value: unknown): string[] {
  const root = record(value)
  if (!Array.isArray(root.accounts)
    || root.accounts.length === 0
    || root.accounts.length > MAX_DISCOVERED_ACCOUNTS
    || root.total !== root.accounts.length) {
    throw new KimChatAccountError('CHATKIM_ACCOUNT_RESPONSE_INVALID')
  }
  const ids = root.accounts.map((candidate) => {
    const id = record(candidate).account_id
    if (typeof id !== 'string' || !ACCOUNT_ID.test(id)) {
      throw new KimChatAccountError('CHATKIM_ACCOUNT_RESPONSE_INVALID')
    }
    return id
  })
  if (new Set(ids).size !== ids.length) {
    throw new KimChatAccountError('CHATKIM_ACCOUNT_RESPONSE_INVALID')
  }
  return ids
}

function active(value: unknown): boolean {
  projectCurrentUser(value)
  const candidate = record(record(value).current_user).active
  if (typeof candidate !== 'boolean') {
    throw new KimChatAccountError('CHATKIM_ACCOUNT_RESPONSE_INVALID')
  }
  return candidate
}

async function resolveAccountId(
  source: ChatkimProcessGateway,
  configuredAccount: string | undefined,
  signal?: AbortSignal,
): Promise<string> {
  const configured = configuredAccount?.trim()
  if (configured !== undefined && configured !== '') {
    if (!ACCOUNT_ID.test(configured)) throw new KimChatAccountError('CHATKIM_ACCOUNT_INVALID')
    return configured
  }

  const ids = accountIds(await source.callTool('list_accounts', {}, signal))
  if (ids.length === 1) return ids[0]!

  const activeIds: string[] = []
  for (const accountId of ids) {
    try {
      const currentUser = await source.callTool('get_current_user', { account_id: accountId }, signal)
      if (active(currentUser)) activeIds.push(accountId)
    } catch (error) {
      if (signal?.aborted === true) throw error
    }
  }
  if (activeIds.length === 1) return activeIds[0]!
  throw new KimChatAccountError('CHATKIM_ACCOUNT_AMBIGUOUS')
}

export class AccountScopedKimChatGateway {
  private accountId: string | undefined
  private accountOpening: Promise<string> | undefined

  constructor(
    private readonly source: ChatkimProcessGateway,
    private readonly configuredAccount?: string,
  ) {}

  async callTool(
    name: ChatkimQueryTool,
    args: Readonly<Record<string, unknown>>,
    signal?: AbortSignal,
  ): Promise<unknown> {
    const accountId = await this.getAccountId(signal)
    return this.source.callTool(name, { ...args, account_id: accountId }, signal)
  }

  dispose(): Promise<void> {
    return this.source.dispose()
  }

  private getAccountId(signal?: AbortSignal): Promise<string> {
    if (this.accountId !== undefined) return Promise.resolve(this.accountId)
    if (this.accountOpening === undefined) {
      const opening = resolveAccountId(this.source, this.configuredAccount, signal)
        .then((accountId) => {
          this.accountId = accountId
          return accountId
        })
      this.accountOpening = opening
      void opening.catch(() => {
        if (this.accountOpening === opening) this.accountOpening = undefined
      })
    }
    return this.accountOpening
  }
}
