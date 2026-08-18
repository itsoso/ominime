import { describe, expect, it } from 'vitest'
import {
  createBlockedEvidence,
  requiredCapabilityKeys,
  sanitizeSourceOwnedEvidence,
} from '../scripts/source-owned/evidence.mjs'

const blockedCapabilities = {
  selfAccountIdentity: false,
  conversationIdentity: false,
  stableMessageIdentity: false,
  finalMessageText: false,
  authoritativeDirection: false,
  timestampOrOrder: false,
  incrementalChanges: false,
}

function validBlockedEvidence() {
  return {
    source: 'wechat',
    interfaceClass: 'app_loopback',
    status: 'block',
    protocolClass: null,
    authorizationClass: null,
    versionClass: null,
    capabilities: { ...blockedCapabilities },
    fieldMappings: {},
    failureCodes: ['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN'],
  }
}

function expectShapeInvalid(action: () => unknown, privateMessage?: string) {
  let thrown: unknown
  try {
    action()
  } catch (error) {
    thrown = error
  }

  expect(thrown).toBeInstanceOf(Error)
  expect((thrown as Error).message).toBe('EVIDENCE_SHAPE_INVALID')
  if (privateMessage !== undefined) {
    expect((thrown as Error).message).not.toContain(privateMessage)
  }
}

describe('source-owned redacted evidence', () => {
  it('creates an exact deeply frozen blocked report with all seven capabilities false', () => {
    expect(requiredCapabilityKeys).toEqual([
      'selfAccountIdentity',
      'conversationIdentity',
      'stableMessageIdentity',
      'finalMessageText',
      'authoritativeDirection',
      'timestampOrOrder',
      'incrementalChanges',
    ])
    expect(Object.isFrozen(requiredCapabilityKeys)).toBe(true)

    const report = createBlockedEvidence({
      source: 'wechat',
      interfaceClass: 'app_loopback',
      failureCode: 'WECHAT_STANDARD_PROTOCOL_NOT_PROVEN',
    })

    expect(report).toEqual(validBlockedEvidence())
    expect(Object.keys(report)).toEqual([
      'source',
      'interfaceClass',
      'status',
      'protocolClass',
      'authorizationClass',
      'versionClass',
      'capabilities',
      'fieldMappings',
      'failureCodes',
    ])
    expect(Object.isFrozen(report)).toBe(true)
    expect(Object.isFrozen(report.capabilities)).toBe(true)
    expect(Object.isFrozen(report.fieldMappings)).toBe(true)
    expect(Object.isFrozen(report.failureCodes)).toBe(true)
    expect(Object.values(report.capabilities)).toEqual(Array(7).fill(false))
    expect(Object.keys(report.fieldMappings)).toEqual([])
  })

  it('rejects malformed failure codes without echoing caller input', () => {
    const privateValue = 'private/path?token=secret'

    expect(() => createBlockedEvidence({
      source: 'wechat',
      interfaceClass: 'app_loopback',
      failureCode: privateValue,
    })).toThrowError(/^EVIDENCE_CODE_INVALID$/)
  })

  it('reconstructs a new deeply frozen allowlisted report', () => {
    const input = validBlockedEvidence()
    const report = sanitizeSourceOwnedEvidence(input)

    expect(report).toEqual(input)
    expect(report).not.toBe(input)
    expect(report.capabilities).not.toBe(input.capabilities)
    expect(report.fieldMappings).not.toBe(input.fieldMappings)
    expect(report.failureCodes).not.toBe(input.failureCodes)
    expect(Object.isFrozen(report)).toBe(true)
    expect(Object.isFrozen(report.capabilities)).toBe(true)
    expect(Object.isFrozen(report.fieldMappings)).toBe(true)
    expect(Object.isFrozen(report.failureCodes)).toBe(true)
  })

  it.each([
    ['unknown top-level key', { metadata: 'private diagnostic' }],
    ['raw error', { rawError: 'private stack and message' }],
    ['path', { path: '/private/user/container' }],
    ['URL', { url: 'http://127.0.0.1/private' }],
    ['message', { message: 'private chat text' }],
    ['identifier', { identifier: 'private-user-id' }],
    ['token', { token: 'private-token' }],
    ['cookie', { cookie: 'private-cookie' }],
    ['count', { count: 42 }],
    ['hash', { hash: 'private-hash' }],
  ])('rejects %s metadata with one fixed non-reflective error', (_name, extra) => {
    const input = { ...validBlockedEvidence(), ...extra }

    expect(() => sanitizeSourceOwnedEvidence(input)).toThrowError(/^EVIDENCE_SHAPE_INVALID$/)
  })

  it('rejects unknown nested keys, non-boolean capabilities, and unsafe field mappings', () => {
    const invalidInputs = [
      {
        ...validBlockedEvidence(),
        capabilities: { ...blockedCapabilities, rawError: false },
      },
      {
        ...validBlockedEvidence(),
        capabilities: { ...blockedCapabilities, finalMessageText: 'false' },
      },
      {
        ...validBlockedEvidence(),
        fieldMappings: { path: null },
      },
      {
        ...validBlockedEvidence(),
        fieldMappings: { finalMessageText: null },
      },
    ]

    for (const input of invalidInputs) {
      expect(() => sanitizeSourceOwnedEvidence(input)).toThrowError(/^EVIDENCE_SHAPE_INVALID$/)
    }
  })

  it('rejects incomplete shapes and arbitrary enum or code values', () => {
    const { versionClass: _omitted, ...incomplete } = validBlockedEvidence()
    const invalidInputs = [
      incomplete,
      { ...validBlockedEvidence(), source: 'private-source' },
      { ...validBlockedEvidence(), interfaceClass: 'private-interface' },
      { ...validBlockedEvidence(), status: 'private-status' },
      { ...validBlockedEvidence(), protocolClass: 'private-protocol' },
      { ...validBlockedEvidence(), authorizationClass: 'private-auth' },
      { ...validBlockedEvidence(), versionClass: 'private-version' },
      { ...validBlockedEvidence(), failureCodes: ['lowercase-private-value'] },
    ]

    for (const input of invalidInputs) {
      expect(() => sanitizeSourceOwnedEvidence(input)).toThrowError(/^EVIDENCE_SHAPE_INVALID$/)
    }
  })

  it('rejects sparse failure-code arrays disguised with a named key', () => {
    const failureCodes = ['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN']
    failureCodes.length = 2
    Object.assign(failureCodes, { rawError: 'private diagnostic' })

    expectShapeInvalid(() => sanitizeSourceOwnedEvidence({
      ...validBlockedEvidence(),
      failureCodes,
    }), 'private diagnostic')
  })

  it('rejects symbol and non-enumerable failure-code metadata', () => {
    const symbolMetadata = ['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN']
    Object.defineProperty(symbolMetadata, Symbol('rawError'), {
      value: 'private symbol diagnostic',
    })
    const hiddenMetadata = ['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN']
    Object.defineProperty(hiddenMetadata, 'rawError', {
      value: 'private hidden diagnostic',
    })

    expectShapeInvalid(() => sanitizeSourceOwnedEvidence({
      ...validBlockedEvidence(),
      failureCodes: symbolMetadata,
    }), 'private symbol diagnostic')
    expectShapeInvalid(() => sanitizeSourceOwnedEvidence({
      ...validBlockedEvidence(),
      failureCodes: hiddenMetadata,
    }), 'private hidden diagnostic')
  })

  it('rejects a failure-code index accessor without invoking it', () => {
    let invoked = 0
    const privateMessage = 'private accessor diagnostic'
    const failureCodes: string[] = []
    Object.defineProperty(failureCodes, '0', {
      enumerable: true,
      get() {
        invoked += 1
        throw new Error(privateMessage)
      },
    })
    failureCodes.length = 1

    expectShapeInvalid(() => sanitizeSourceOwnedEvidence({
      ...validBlockedEvidence(),
      failureCodes,
    }), privateMessage)
    expect(invoked).toBe(0)
  })

  it('rejects custom array prototypes and overridden map methods without invoking them', () => {
    const privateMessage = 'private map diagnostic'
    let invoked = 0
    const customPrototype = ['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN']
    Object.setPrototypeOf(customPrototype, Object.create(Array.prototype, {
      map: {
        value() {
          invoked += 1
          throw new Error(privateMessage)
        },
      },
    }))
    const overriddenMap = ['WECHAT_STANDARD_PROTOCOL_NOT_PROVEN']
    Object.defineProperty(overriddenMap, 'map', {
      value() {
        invoked += 1
        throw new Error(privateMessage)
      },
    })

    expectShapeInvalid(() => sanitizeSourceOwnedEvidence({
      ...validBlockedEvidence(),
      failureCodes: customPrototype,
    }), privateMessage)
    expectShapeInvalid(() => sanitizeSourceOwnedEvidence({
      ...validBlockedEvidence(),
      failureCodes: overriddenMap,
    }), privateMessage)
    expect(invoked).toBe(0)
  })

  it.each([
    ['sanitizeSourceOwnedEvidence', sanitizeSourceOwnedEvidence],
    ['createBlockedEvidence', createBlockedEvidence],
  ])('normalizes throwing Proxy reflection failures in %s', (_name, validate) => {
    const privateMessage = 'private reflection diagnostic'
    const input = new Proxy({}, {
      getPrototypeOf() {
        throw new Error(privateMessage)
      },
    })

    expectShapeInvalid(() => validate(input as never), privateMessage)
  })

  it.each([
    ['sanitizeSourceOwnedEvidence', sanitizeSourceOwnedEvidence],
    ['createBlockedEvidence', createBlockedEvidence],
  ])('normalizes revoked Proxy reflection failures in %s', (_name, validate) => {
    const { proxy, revoke } = Proxy.revocable({}, {})
    revoke()

    expectShapeInvalid(() => validate(proxy as never))
  })
})
