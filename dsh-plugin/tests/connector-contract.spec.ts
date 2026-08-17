import { describe, expect, expectTypeOf, it } from 'vitest'
import {
  DuplicateConnectorError,
  SourceConnectorRegistry,
  type ConnectorResourceDisposer,
} from '../src/connectors/registry.ts'
import {
  SourceIncompatibleError,
  type SourceConnector,
} from '../src/connectors/contract.ts'
import type {
  MessageDirection,
  SourceHealth,
  SourceMessageChange,
} from '../src/domain/types.ts'
import {
  createSyntheticConnector,
  syntheticConversationRef,
  syntheticMessageBodies,
} from './fixtures/synthetic-chat.ts'

function activeSignal(): AbortSignal {
  return new AbortController().signal
}

class SyntheticEffectOwner {
  private cleanup: ConnectorResourceDisposer | undefined

  effect(setup: () => ConnectorResourceDisposer, _label?: string): ConnectorResourceDisposer {
    this.cleanup = setup()
    return async () => {
      const cleanup = this.cleanup
      this.cleanup = undefined
      await cleanup?.()
    }
  }

  async unload(): Promise<void> {
    await this.cleanup?.()
  }
}

describe('source-neutral connector contract', () => {
  it('discovers the source account identities that authoritatively belong to self', async () => {
    const [account] = await createSyntheticConnector().discoverAccounts(activeSignal())

    expect(account).toEqual({
      source: 'synthetic-chat',
      accountId: 'account-self',
      selfParticipantIds: ['participant-self'],
      adapterVersion: 'synthetic-v1',
    })
  })

  it('pages conversations with an opaque resumable cursor', async () => {
    const connector = createSyntheticConnector()
    const first = await connector.discoverConversations(null, activeSignal())
    const second = await connector.discoverConversations(first.nextCursor, activeSignal())

    expect(first.conversations.map(item => item.conversationId)).toEqual(['conversation-one'])
    expect(first.nextCursor).toMatch(/^opaque:/)
    expect(second.conversations.map(item => item.conversationId)).toEqual(['conversation-two'])
    expect(second.nextCursor).toBeNull()
  })

  it('resumes message changes from an opaque cursor without replaying the first page', async () => {
    const connector = createSyntheticConnector()
    const first = await connector.syncMessages(syntheticConversationRef, null, activeSignal())
    const second = await connector.syncMessages(syntheticConversationRef, first.nextCursor, activeSignal())

    expect(first.nextCursor).toMatch(/^opaque:/)
    expect(first.changes.map(item => item.messageId)).toEqual(['message-self', 'message-other'])
    expect(second.changes.map(item => item.messageId)).toEqual(['message-system', 'message-unknown'])
    expect(second.nextCursor).toBeNull()
  })

  it('represents every authoritative direction and required message-change field', async () => {
    const page = await createSyntheticConnector().backfill(syntheticConversationRef, null, activeSignal())
    const directions = page.messages.map(item => item.direction)

    expect(directions).toEqual<MessageDirection[]>(['self', 'other', 'system', 'unknown'])
    expect(page.messages[0]).toEqual<SourceMessageChange>({
      source: 'synthetic-chat',
      accountId: 'account-self',
      conversationId: 'conversation-one',
      messageId: 'message-self',
      authorId: 'participant-self',
      direction: 'self',
      kind: 'create',
      text: 'synthetic self body',
      replyToMessageId: null,
      sourceOrder: '1',
      sourceTimestamp: '2026-08-17T12:00:00.000Z',
      observedAt: '2026-08-17T12:02:00.000Z',
    })
    expectTypeOf(page.messages[0]).toMatchTypeOf<SourceMessageChange>()
  })

  it('exposes explicit edit, retraction, reply, and delete capabilities without bodies in health', () => {
    const health = createSyntheticConnector().health()
    const serialized = JSON.stringify(health)

    expect(health.capabilities).toEqual({
      edits: true,
      retractions: true,
      replyLinks: true,
      deletes: true,
    })
    for (const body of syntheticMessageBodies) expect(serialized).not.toContain(body)
    expect(health).not.toHaveProperty('message')
    expect(health.error).toBeNull()
  })

  it('throws a source-owned incompatibility error instead of returning guessed source data', async () => {
    const connector = createSyntheticConnector({ incompatible: true })

    await expect(connector.discoverAccounts(activeSignal())).rejects.toMatchObject({
      name: 'SourceIncompatibleError',
      code: 'SOURCE_INCOMPATIBLE',
      metadata: {
        source: 'synthetic-chat',
        adapterVersion: 'synthetic-v1',
        observedVersion: 'synthetic-v2',
        reason: 'UNSUPPORTED_SOURCE_VERSION',
      },
    })
    await expect(connector.discoverAccounts(activeSignal())).rejects.toBeInstanceOf(SourceIncompatibleError)
  })

  it('makes incompatibility error code and metadata non-writable at runtime', () => {
    const error = new SourceIncompatibleError({
      source: 'synthetic-chat',
      adapterVersion: 'synthetic-v1',
      observedVersion: 'synthetic-v2',
      reason: 'UNSUPPORTED_SOURCE_VERSION',
    })

    expect(() => Object.assign(error, { code: 'CHANGED' })).toThrow(TypeError)
    expect(() => Object.assign(error, { metadata: {} })).toThrow(TypeError)
    expect(() => Object.assign(error.metadata, { reason: 'CHANGED' })).toThrow(TypeError)
    expect(error).toMatchObject({
      code: 'SOURCE_INCOMPATIBLE',
      metadata: { reason: 'UNSUPPORTED_SOURCE_VERSION' },
    })
  })

  it('honors an already-aborted signal across every source read', async () => {
    const connector = createSyntheticConnector()
    const controller = new AbortController()
    controller.abort()

    await expect(connector.discoverAccounts(controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    await expect(connector.discoverConversations(null, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    await expect(connector.syncMessages(syntheticConversationRef, null, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    await expect(connector.backfill(syntheticConversationRef, null, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  })
})

describe('source connector registry', () => {
  it('rejects invalid connector IDs without echoing the rejected value', () => {
    const rejectedValue = syntheticMessageBodies[0]
    const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)

    let error: unknown
    try {
      registry.register(createSyntheticConnector({ id: rejectedValue }), () => {})
    } catch (candidate) {
      error = candidate
    }

    expect(error).toMatchObject({
      name: 'InvalidConnectorIdError',
      code: 'INVALID_CONNECTOR_ID',
      metadata: { reason: 'FORMAT' },
    })
    expect(String(error)).not.toContain(rejectedValue)
    expect(JSON.stringify(error)).not.toContain(rejectedValue)
  })

  it('rejects duplicate connector IDs with stable plugin-owned error metadata', () => {
    const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)
    registry.register(createSyntheticConnector(), () => {})

    expect(() => registry.register(createSyntheticConnector(), () => {})).toThrowError(expect.objectContaining({
      name: 'DuplicateConnectorError',
      code: 'DUPLICATE_CONNECTOR',
      metadata: { connectorId: 'synthetic-chat' },
    }))
  })

  it('returns a runtime-immutable connector snapshot detached from registry changes', async () => {
    const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)
    const unregister = registry.register(createSyntheticConnector(), () => {})
    const snapshot = registry.snapshot()

    expect(Object.isFrozen(snapshot)).toBe(true)
    expect(Object.isFrozen(snapshot[0])).toBe(true)
    expect(() => (snapshot as SourceConnector[]).push(createSyntheticConnector({ id: 'other' }))).toThrow(TypeError)
    expect(() => Object.assign(snapshot[0], { id: 'changed' })).toThrow(TypeError)
    expect(registry.snapshot()[0]?.id).toBe('synthetic-chat')
    await unregister()
    expect(snapshot.map(item => item.id)).toEqual(['synthetic-chat'])
    expect(registry.snapshot()).toEqual([])
  })

  it('projects valid public health into a detached, deeply frozen DTO', () => {
    const connector = createSyntheticConnector()
    const rawHealth = structuredClone(connector.health())
    rawHealth.error = { code: 'SYNTHETIC_FAILURE' }
    const mutableConnector: SourceConnector = {
      ...connector,
      health: () => rawHealth,
    }
    const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)
    registry.register(mutableConnector, () => {})

    const health = registry.snapshot()[0]?.health()

    expect(health).toEqual({
      source: 'synthetic-chat',
      status: 'healthy',
      adapterVersion: 'synthetic-v1',
      checkedAt: '2026-08-17T12:02:00.000Z',
      lastSuccessfulSyncAt: '2026-08-17T12:01:00.000Z',
      capabilities: {
        edits: true,
        retractions: true,
        replyLinks: true,
        deletes: true,
      },
      error: { code: 'SYNTHETIC_FAILURE' },
    })
    expect(JSON.stringify(health)).not.toContain(syntheticMessageBodies[0])
    expect(Object.isFrozen(health)).toBe(true)
    expect(Object.isFrozen(health?.capabilities)).toBe(true)
    expect(Object.isFrozen(health?.error)).toBe(true)

    rawHealth.capabilities.edits = false
    rawHealth.error.code = 'CHANGED'
    expect(health?.capabilities.edits).toBe(true)
    expect(health?.error?.code).toBe('SYNTHETIC_FAILURE')
  })

  it('fails closed to one fixed health DTO for malformed or throwing connector health', () => {
    const privateBody = syntheticMessageBodies[0]
    const base = createSyntheticConnector().health()
    const invalidHealthPayloads: unknown[] = [
      { ...base, source: privateBody },
      { ...base, status: privateBody },
      { ...base, adapterVersion: privateBody },
      { ...base, checkedAt: privateBody },
      { ...base, lastSuccessfulSyncAt: privateBody },
      { ...base, error: { code: privateBody } },
      { ...base, capabilities: { ...base.capabilities, edits: privateBody } },
      { ...base, leakedBody: privateBody },
      { ...base, capabilities: { ...base.capabilities, leakedBody: privateBody } },
      { ...base, error: { code: 'SYNTHETIC_FAILURE', leakedBody: privateBody } },
    ]
    const expectedFallback: SourceHealth = {
      source: 'synthetic-chat',
      status: 'degraded',
      adapterVersion: 'unknown',
      checkedAt: '1970-01-01T00:00:00.000Z',
      lastSuccessfulSyncAt: null,
      capabilities: {
        edits: false,
        retractions: false,
        replyLinks: false,
        deletes: false,
      },
      error: { code: 'INVALID_HEALTH_PAYLOAD' },
    }

    for (const payload of invalidHealthPayloads) {
      const connector: SourceConnector = {
        ...createSyntheticConnector(),
        health: () => payload as SourceHealth,
      }
      const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)
      registry.register(connector, () => {})

      const health = registry.snapshot()[0]!.health()
      expect(health).toEqual(expectedFallback)
      expect(JSON.stringify(health)).not.toContain(privateBody)
      expect(Object.isFrozen(health)).toBe(true)
      expect(Object.isFrozen(health.capabilities)).toBe(true)
      expect(Object.isFrozen(health.error)).toBe(true)
    }

    const throwingConnector: SourceConnector = {
      ...createSyntheticConnector(),
      health: () => { throw new Error(privateBody) },
    }
    const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)
    registry.register(throwingConnector, () => {})
    expect(registry.snapshot()[0]!.health()).toEqual(expectedFallback)
  })

  it('uses Cordis effect unload to attempt every resource cleanup and surfaces partial failure', async () => {
    const owner = new SyntheticEffectOwner()
    const registry = new SourceConnectorRegistry(owner as never)
    const disposed: string[] = []
    registry.register(createSyntheticConnector({ id: 'first' }), async () => {
      disposed.push('first')
      throw new Error('first cleanup failed')
    })
    registry.register(createSyntheticConnector({ id: 'second' }), () => {
      disposed.push('second')
    })

    await expect(owner.unload()).rejects.toMatchObject({
      name: 'ConnectorDisposalError',
      code: 'CONNECTOR_DISPOSAL_FAILED',
      metadata: { connectorIds: ['first'] },
    })
    expect(disposed).toEqual(['first', 'second'])
    expect(registry.snapshot()).toEqual([])
    expect(() => registry.register(createSyntheticConnector({ id: 'third' }), () => {})).toThrowError(
      expect.objectContaining({
        name: 'ConnectorRegistryDisposedError',
        code: 'CONNECTOR_REGISTRY_DISPOSED',
        metadata: { connectorId: 'third' },
      }),
    )
  })

  it('makes a registration disposer single-shot without removing a later successor', async () => {
    const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)
    let firstDisposals = 0
    const unregisterFirst = registry.register(createSyntheticConnector(), () => { firstDisposals += 1 })

    await unregisterFirst()
    const unregisterSecond = registry.register(createSyntheticConnector(), () => {})
    await unregisterFirst()

    expect(firstDisposals).toBe(1)
    expect(registry.snapshot().map(item => item.id)).toEqual(['synthetic-chat'])
    await unregisterSecond()
  })

  it('reserves an ID while release is pending, then permits a successor only after success', async () => {
    const registry = new SourceConnectorRegistry(new SyntheticEffectOwner() as never)
    const gate = Promise.withResolvers<void>()
    let firstDisposals = 0
    const unregisterFirst = registry.register(createSyntheticConnector(), async () => {
      firstDisposals += 1
      await gate.promise
    })

    const firstRelease = unregisterFirst()
    await new Promise<void>(resolve => setImmediate(resolve))
    expect(registry.snapshot()).toEqual([])
    expect(() => registry.register(createSyntheticConnector(), () => {})).toThrow(DuplicateConnectorError)

    gate.resolve()
    await firstRelease
    const unregisterSecond = registry.register(createSyntheticConnector(), () => {})
    await unregisterFirst()

    expect(firstDisposals).toBe(1)
    expect(registry.snapshot().map(item => item.id)).toEqual(['synthetic-chat'])
    await unregisterSecond()
  })

  it('retains an ID reservation after release failure and reports it again on unload', async () => {
    const owner = new SyntheticEffectOwner()
    const registry = new SourceConnectorRegistry(owner as never)
    let disposalCalls = 0
    const unregister = registry.register(createSyntheticConnector(), async () => {
      disposalCalls += 1
      throw new Error('synthetic cleanup failure')
    })

    await expect(unregister()).rejects.toMatchObject({
      name: 'ConnectorDisposalError',
      code: 'CONNECTOR_DISPOSAL_FAILED',
      metadata: { connectorIds: ['synthetic-chat'] },
    })
    expect(registry.snapshot()).toEqual([])
    expect(() => registry.register(createSyntheticConnector(), () => {})).toThrow(DuplicateConnectorError)
    await expect(owner.unload()).rejects.toMatchObject({
      name: 'ConnectorDisposalError',
      code: 'CONNECTOR_DISPOSAL_FAILED',
      metadata: { connectorIds: ['synthetic-chat'] },
    })
    expect(disposalCalls).toBe(1)
  })

  it('waits for a pending manual release during concurrent Cordis unload without duplicate cleanup', async () => {
    const owner = new SyntheticEffectOwner()
    const registry = new SourceConnectorRegistry(owner as never)
    const gate = Promise.withResolvers<void>()
    let disposalCalls = 0
    const unregister = registry.register(createSyntheticConnector(), async () => {
      disposalCalls += 1
      await gate.promise
    })

    const manualRelease = unregister()
    const firstUnload = owner.unload()
    const secondUnload = owner.unload()
    let unloadSettled = false
    void firstUnload.then(
      () => { unloadSettled = true },
      () => { unloadSettled = true },
    )
    await new Promise<void>(resolve => setImmediate(resolve))

    expect(unloadSettled).toBe(false)
    expect(disposalCalls).toBe(1)
    gate.resolve()
    await expect(Promise.all([manualRelease, firstUnload, secondUnload])).resolves.toEqual([
      undefined,
      undefined,
      undefined,
    ])
    expect(disposalCalls).toBe(1)
  })

  it('reports one pending release rejection to both the manual caller and concurrent unloads', async () => {
    const owner = new SyntheticEffectOwner()
    const registry = new SourceConnectorRegistry(owner as never)
    const gate = Promise.withResolvers<void>()
    const unhandledRejections: unknown[] = []
    const recordUnhandled = (reason: unknown) => { unhandledRejections.push(reason) }
    process.on('unhandledRejection', recordUnhandled)
    let disposalCalls = 0
    const unregister = registry.register(createSyntheticConnector(), async () => {
      disposalCalls += 1
      await gate.promise
    })

    try {
      const manualResult = Promise.resolve(unregister()).catch((error: unknown) => error)
      const firstUnloadResult = owner.unload().catch(error => error)
      const secondUnloadResult = owner.unload().catch(error => error)
      gate.reject(new Error('synthetic cleanup failure'))

      for (const result of await Promise.all([manualResult, firstUnloadResult, secondUnloadResult])) {
        expect(result).toMatchObject({
          name: 'ConnectorDisposalError',
          code: 'CONNECTOR_DISPOSAL_FAILED',
          metadata: { connectorIds: ['synthetic-chat'] },
        })
      }
      await new Promise<void>(resolve => setImmediate(resolve))
      expect(unhandledRejections).toEqual([])
      expect(disposalCalls).toBe(1)
    } finally {
      process.off('unhandledRejection', recordUnhandled)
    }
  })
})
