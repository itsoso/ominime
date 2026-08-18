import { describe, expect, it, vi } from 'vitest'

import {
  AccountScopedKimChatGateway,
  KimChatAccountError,
} from '../src/chatkim/account.ts'

const signal = new AbortController().signal

function currentUser(userId: string, active: boolean) {
  return {
    current_user: { user_id: userId, active },
    database_connection: { connected: true, read_only: true, schema_verified: true },
  }
}

describe('private Kim account selection', () => {
  it('uses the only discovered account and injects it without exposing discovery metadata', async () => {
    const callTool = vi.fn(async (name: string, args: Record<string, unknown>) => {
      if (name === 'list_accounts') {
        return {
          data_root: '/private/database/path',
          accounts: [{ account_id: '10001', account_path: '/private/account/path' }],
          total: 1,
        }
      }
      return { name, args }
    })
    const source = { callTool, dispose: vi.fn(async () => {}) }
    const scoped = new AccountScopedKimChatGateway(source)

    await expect(scoped.callTool('list_conversations', { limit: 2 }, signal)).resolves.toEqual({
      name: 'list_conversations',
      args: { limit: 2, account_id: '10001' },
    })
    expect(callTool).toHaveBeenNthCalledWith(1, 'list_accounts', {}, signal)
    expect(JSON.stringify(await scoped.callTool('get_current_user', {}, signal))).not.toContain('/private/')
  })

  it('selects the unique active account when discovery finds several', async () => {
    const callTool = vi.fn(async (name: string, args: Record<string, unknown>) => {
      if (name === 'list_accounts') {
        return { accounts: [{ account_id: '10001' }, { account_id: '20002' }], total: 2 }
      }
      if (name === 'get_current_user' && args.account_id === '10001') return currentUser('old-user', false)
      if (name === 'get_current_user' && args.account_id === '20002') return currentUser('active-user', true)
      return { messages: [], pagination: { returned: 0, has_more: false, next_cursor: null } }
    })
    const scoped = new AccountScopedKimChatGateway({ callTool, dispose: vi.fn(async () => {}) })

    await scoped.callTool('query_chat_log', { limit: 1 }, signal)
    expect(callTool).toHaveBeenLastCalledWith(
      'query_chat_log',
      { limit: 1, account_id: '20002' },
      signal,
    )
  })

  it('fails closed when several accounts are active without echoing their IDs', async () => {
    const callTool = vi.fn(async (name: string) => {
      if (name === 'list_accounts') {
        return { accounts: [{ account_id: '10001' }, { account_id: '20002' }], total: 2 }
      }
      return currentUser('private-user', true)
    })
    const scoped = new AccountScopedKimChatGateway({ callTool, dispose: vi.fn(async () => {}) })
    const error = await scoped.callTool('get_current_user', {}, signal).catch((caught: unknown) => caught)

    expect(error).toBeInstanceOf(KimChatAccountError)
    expect(error).toMatchObject({ code: 'CHATKIM_ACCOUNT_AMBIGUOUS' })
    expect(String(error)).not.toMatch(/10001|20002|private-user/)
  })

  it('accepts only a bounded numeric explicit account without discovery', async () => {
    const callTool = vi.fn(async (name: string, args: Record<string, unknown>) => ({ name, args }))
    const source = { callTool, dispose: vi.fn(async () => {}) }
    const scoped = new AccountScopedKimChatGateway(source, '30003')
    await scoped.callTool('get_current_user', {}, signal)
    expect(callTool).toHaveBeenCalledOnce()
    expect(callTool).toHaveBeenCalledWith('get_current_user', { account_id: '30003' }, signal)

    const invalid = new AccountScopedKimChatGateway(source, '../private')
    await expect(invalid.callTool('get_current_user', {}, signal)).rejects.toMatchObject({
      code: 'CHATKIM_ACCOUNT_INVALID',
    })
  })
})
