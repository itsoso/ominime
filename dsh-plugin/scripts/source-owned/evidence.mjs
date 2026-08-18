export const requiredCapabilityKeys = Object.freeze([
  'selfAccountIdentity',
  'conversationIdentity',
  'stableMessageIdentity',
  'finalMessageText',
  'authoritativeDirection',
  'timestampOrOrder',
  'incrementalChanges',
])

const reportKeys = Object.freeze([
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

const blockedArgumentKeys = Object.freeze([
  'source',
  'interfaceClass',
  'failureCode',
])

const sources = new Set(['kim', 'wechat'])
const interfaceClasses = new Set(['app_loopback', 'enterprise_open_api'])
const statuses = new Set(['block', 'candidate'])
const protocolClasses = new Set([null, 'banner', 'http', 'tls'])
const authorizationClasses = new Set([null, 'app_session', 'enterprise_sso', 'none'])
const versionClasses = new Set([null, 'unversioned', 'vendor_documented', 'versioned'])
const failureCodePattern = /^[A-Z][A-Z0-9_]{0,63}$/

function shapeInvalid() {
  throw new Error('EVIDENCE_SHAPE_INVALID')
}

function exactDataRecord(value, expectedKeys) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) shapeInvalid()
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) shapeInvalid()

  const ownKeys = Reflect.ownKeys(value)
  if (
    ownKeys.length !== expectedKeys.length
    || ownKeys.some((key) => typeof key !== 'string' || !expectedKeys.includes(key))
  ) shapeInvalid()

  const descriptors = Object.getOwnPropertyDescriptors(value)
  const result = Object.create(null)
  for (const key of expectedKeys) {
    const descriptor = descriptors[key]
    if (descriptor === undefined || !('value' in descriptor) || !descriptor.enumerable) shapeInvalid()
    result[key] = descriptor.value
  }
  return result
}

function oneOf(value, allowed) {
  if (!allowed.has(value)) shapeInvalid()
  return value
}

function sanitizeCapabilities(value) {
  const raw = exactDataRecord(value, requiredCapabilityKeys)
  const capabilities = {}
  for (const key of requiredCapabilityKeys) {
    if (typeof raw[key] !== 'boolean') shapeInvalid()
    capabilities[key] = raw[key]
  }
  return Object.freeze(capabilities)
}

function sanitizeFieldMappings(value) {
  exactDataRecord(value, [])
  return Object.freeze({})
}

function sanitizeFailureCodes(value) {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype) shapeInvalid()

  const ownKeys = Reflect.ownKeys(value)
  const descriptors = Object.getOwnPropertyDescriptors(value)
  const lengthDescriptor = descriptors.length
  if (
    lengthDescriptor === undefined
    || !('value' in lengthDescriptor)
    || lengthDescriptor.enumerable
    || !Number.isInteger(lengthDescriptor.value)
    || lengthDescriptor.value < 0
    || lengthDescriptor.value > 16
  ) shapeInvalid()

  const length = lengthDescriptor.value
  const expectedKeys = new Set(['length'])
  for (let index = 0; index < length; index += 1) expectedKeys.add(String(index))
  if (
    ownKeys.length !== expectedKeys.size
    || ownKeys.some((key) => typeof key !== 'string' || !expectedKeys.has(key))
  ) shapeInvalid()

  const failureCodes = []
  for (let index = 0; index < length; index += 1) {
    const descriptor = descriptors[String(index)]
    if (descriptor === undefined || !('value' in descriptor) || !descriptor.enumerable) {
      shapeInvalid()
    }
    const code = descriptor.value
    if (typeof code !== 'string' || !failureCodePattern.test(code)) shapeInvalid()
    failureCodes[index] = code
  }
  return Object.freeze(failureCodes)
}

function validateStatusEvidence(capabilities) {
  if (requiredCapabilityKeys.some((key) => capabilities[key])) shapeInvalid()
}

function sanitizeSourceOwnedEvidenceUnsafe(value) {
  const raw = exactDataRecord(value, reportKeys)
  const source = oneOf(raw.source, sources)
  const interfaceClass = oneOf(raw.interfaceClass, interfaceClasses)
  const status = oneOf(raw.status, statuses)
  const protocolClass = oneOf(raw.protocolClass, protocolClasses)
  const authorizationClass = oneOf(raw.authorizationClass, authorizationClasses)
  const versionClass = oneOf(raw.versionClass, versionClasses)
  const capabilities = sanitizeCapabilities(raw.capabilities)
  const fieldMappings = sanitizeFieldMappings(raw.fieldMappings)
  const failureCodes = sanitizeFailureCodes(raw.failureCodes)

  validateStatusEvidence(capabilities)

  return Object.freeze({
    source,
    interfaceClass,
    status,
    protocolClass,
    authorizationClass,
    versionClass,
    capabilities,
    fieldMappings,
    failureCodes,
  })
}

export function sanitizeSourceOwnedEvidence(value) {
  try {
    return sanitizeSourceOwnedEvidenceUnsafe(value)
  } catch {
    shapeInvalid()
  }
}

export function createBlockedEvidence(value) {
  let raw
  try {
    raw = exactDataRecord(value, blockedArgumentKeys)
  } catch {
    shapeInvalid()
  }
  if (typeof raw.failureCode !== 'string') shapeInvalid()
  if (!failureCodePattern.test(raw.failureCode)) throw new Error('EVIDENCE_CODE_INVALID')

  const capabilities = {}
  for (const key of requiredCapabilityKeys) {
    capabilities[key] = false
  }

  return sanitizeSourceOwnedEvidence({
    source: raw.source,
    interfaceClass: raw.interfaceClass,
    status: 'block',
    protocolClass: null,
    authorizationClass: null,
    versionClass: null,
    capabilities,
    fieldMappings: {},
    failureCodes: [raw.failureCode],
  })
}
