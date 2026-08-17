import {
  lstatSync,
  opendirSync,
  realpathSync,
  type Dirent,
} from 'node:fs'
import {
  isAbsolute,
  join,
  parse,
  relative,
  resolve,
  sep,
} from 'node:path'
import { SourceIncompatibleError } from '../contract.ts'

export const WECHAT_SOURCE = 'wechat'
export const WECHAT_ADAPTER_VERSION = 'wechat-macos-xwechat-v4-v1'
export const WECHAT_LEGACY_ADAPTER_VERSION = 'wechat-macos-legacy-v3-v1'
export const WECHAT_SYNTHETIC_ADAPTER_VERSION = 'wechat-synthetic-fixture-v1'
export const WECHAT_DISCOVERY_HARD_MAXIMUM_ENTRIES = 1024

const adapterDatabasePaths = Object.freeze({
  [WECHAT_ADAPTER_VERSION]: 'db_storage/message/message_0.db',
  [WECHAT_LEGACY_ADAPTER_VERSION]: 'Message/msg_0.db',
  [WECHAT_SYNTHETIC_ADAPTER_VERSION]: 'db_storage/message/message_0.db',
})

export type WechatAdapterVersion = keyof typeof adapterDatabasePaths

export function isWechatLiveAdapterVersion(adapterVersion: string): boolean {
  return adapterVersion === WECHAT_ADAPTER_VERSION || adapterVersion === WECHAT_LEGACY_ADAPTER_VERSION
}

export interface WechatSourceRequest {
  readonly containerRoot: string
  readonly accountDirectory: string
  readonly adapterVersion: string
  readonly databaseRelativePath?: string
}

export interface WechatSourcePaths {
  readonly containerRoot: string
  readonly accountDirectory: string
  readonly accountRoot: string
  readonly sourceDirectory: string
  readonly adapterVersion: WechatAdapterVersion
  readonly databaseRelativePath: string
  readonly database: string
  readonly wal: string
  readonly shm: string
}

function incompatible(reason: string): never {
  throw new SourceIncompatibleError({
    source: WECHAT_SOURCE,
    adapterVersion: WECHAT_ADAPTER_VERSION,
    observedVersion: null,
    reason,
  })
}

function safeLstat(path: string, missingReason: string) {
  try {
    return lstatSync(path, { throwIfNoEntry: false })
  } catch (error) {
    if (['EACCES', 'EPERM'].includes((error as NodeJS.ErrnoException).code ?? '')) {
      incompatible('WECHAT_SOURCE_PERMISSION_DENIED')
    }
    incompatible(missingReason)
  }
}

function safeRealpath(path: string, missingReason: string): string {
  try {
    return realpathSync(path)
  } catch (error) {
    if (['EACCES', 'EPERM'].includes((error as NodeJS.ErrnoException).code ?? '')) {
      incompatible('WECHAT_SOURCE_PERMISSION_DENIED')
    }
    incompatible(missingReason)
  }
}

function isContained(root: string, candidate: string): boolean {
  const remainder = relative(root, candidate)
  return remainder === '' || (!remainder.startsWith(`..${sep}`) && remainder !== '..' && !isAbsolute(remainder))
}

function hasParentTraversal(path: string): boolean {
  return path.split(/[\\/]+/).includes('..')
}

function assertSafeAbsoluteRoot(path: string): void {
  if (!isAbsolute(path) || hasParentTraversal(path)) incompatible('WECHAT_PATH_ESCAPE')
}

function assertOrdinaryDirectoryChain(
  path: string,
  missingReason: string,
  allowMissingTail = false,
): boolean {
  const absolutePath = resolve(path)
  const { root } = parse(absolutePath)
  const remainder = absolutePath.slice(root.length)
  const segments = remainder === '' ? [] : remainder.split(sep)
  let candidate = root

  for (const segment of ['', ...segments]) {
    if (segment !== '') candidate = join(candidate, segment)
    const stats = safeLstat(candidate, missingReason)
    if (stats === undefined) {
      if (allowMissingTail) return false
      incompatible(missingReason)
    }
    if (stats.isSymbolicLink()) incompatible('WECHAT_SYMLINK_REJECTED')
    if (!stats.isDirectory()) incompatible(missingReason)
  }
  return true
}

function assertSingleDirectoryName(accountDirectory: string): void {
  if (
    accountDirectory === ''
    || accountDirectory === '.'
    || accountDirectory === '..'
    || isAbsolute(accountDirectory)
    || accountDirectory.includes('/')
    || accountDirectory.includes('\\')
  ) {
    incompatible('WECHAT_PATH_ESCAPE')
  }
}

function assertOrdinaryDirectory(path: string, missingReason: string): void {
  const stats = safeLstat(path, missingReason)
  if (stats === undefined) incompatible(missingReason)
  if (stats.isSymbolicLink()) incompatible('WECHAT_SYMLINK_REJECTED')
  if (!stats.isDirectory()) incompatible(missingReason)
}

function assertOrdinaryFile(path: string, required: boolean): boolean {
  const stats = safeLstat(path, 'WECHAT_SOURCE_MISSING')
  if (stats === undefined) {
    if (required) incompatible('WECHAT_SOURCE_MISSING')
    return false
  }
  if (stats.isSymbolicLink()) incompatible('WECHAT_SYMLINK_REJECTED')
  if (!stats.isFile()) incompatible('WECHAT_SOURCE_ENTRY_INVALID')
  return true
}

function assertNoSymlinkChain(accountRoot: string, databaseRelativePath: string): void {
  const segments = databaseRelativePath.split('/')
  let candidate = accountRoot
  for (const [index, segment] of segments.entries()) {
    candidate = join(candidate, segment)
    const stats = safeLstat(candidate, 'WECHAT_SOURCE_MISSING')
    if (stats === undefined) incompatible('WECHAT_SOURCE_MISSING')
    if (stats.isSymbolicLink()) incompatible('WECHAT_SYMLINK_REJECTED')
    if (index < segments.length - 1 && !stats.isDirectory()) {
      incompatible('WECHAT_SOURCE_ENTRY_INVALID')
    }
  }
}

export function resolveWechatSourcePaths(request: WechatSourceRequest): WechatSourcePaths {
  const recognizedDatabase = adapterDatabasePaths[request.adapterVersion as WechatAdapterVersion]
  if (recognizedDatabase === undefined) incompatible('WECHAT_ADAPTER_UNKNOWN')
  if (isWechatLiveAdapterVersion(request.adapterVersion)) incompatible('WECHAT_ATOMIC_OPEN_UNAVAILABLE')
  const databaseRelativePath = request.databaseRelativePath ?? recognizedDatabase
  if (databaseRelativePath !== recognizedDatabase) incompatible('WECHAT_FILE_UNRECOGNIZED')
  assertSingleDirectoryName(request.accountDirectory)
  assertSafeAbsoluteRoot(request.containerRoot)

  const containerRoot = resolve(request.containerRoot)
  assertOrdinaryDirectoryChain(containerRoot, 'WECHAT_CONTAINER_UNRESOLVED')
  const canonicalContainer = safeRealpath(containerRoot, 'WECHAT_CONTAINER_UNRESOLVED')

  const accountRoot = join(containerRoot, request.accountDirectory)
  assertOrdinaryDirectory(accountRoot, 'WECHAT_ACCOUNT_UNRESOLVED')
  const canonicalAccount = safeRealpath(accountRoot, 'WECHAT_ACCOUNT_UNRESOLVED')
  if (!isContained(canonicalContainer, canonicalAccount)) incompatible('WECHAT_PATH_ESCAPE')
  if (canonicalAccount !== join(canonicalContainer, request.accountDirectory)) {
    incompatible('WECHAT_SYMLINK_REJECTED')
  }

  assertNoSymlinkChain(accountRoot, databaseRelativePath)
  const database = join(accountRoot, ...databaseRelativePath.split('/'))
  assertOrdinaryFile(database, true)
  const canonicalDatabase = safeRealpath(database, 'WECHAT_SOURCE_MISSING')
  if (!isContained(canonicalContainer, canonicalDatabase)) incompatible('WECHAT_PATH_ESCAPE')

  const wal = `${database}-wal`
  const shm = `${database}-shm`
  for (const optional of [wal, shm]) {
    if (!assertOrdinaryFile(optional, false)) continue
    const canonicalOptional = safeRealpath(optional, 'WECHAT_SOURCE_MISSING')
    if (!isContained(canonicalContainer, canonicalOptional)) incompatible('WECHAT_PATH_ESCAPE')
  }

  return Object.freeze({
    containerRoot,
    accountDirectory: request.accountDirectory,
    accountRoot,
    sourceDirectory: join(database, '..'),
    adapterVersion: request.adapterVersion as WechatAdapterVersion,
    databaseRelativePath,
    database,
    wal,
    shm,
  })
}

interface CandidateLayout {
  readonly container: readonly string[]
  readonly adapterVersion: WechatAdapterVersion
  readonly accountDepth: 1 | 2
}

const testOnlyCandidateLayouts: readonly CandidateLayout[] = Object.freeze([
  {
    container: ['Library', 'Containers', 'com.tencent.xinWeChat', 'Data', 'Documents', 'xwechat_files'],
    adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    accountDepth: 1,
  },
  {
    container: [
      'Library',
      'Containers',
      'com.tencent.xinWeChat',
      'Data',
      'Library',
      'Application Support',
      'com.tencent.xinWeChat',
    ],
    adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    accountDepth: 2,
  },
])

interface DiscoveryBudget {
  remaining: number
}

function createDiscoveryBudget(maximumEntries: number): DiscoveryBudget {
  if (
    !Number.isSafeInteger(maximumEntries)
    || maximumEntries <= 0
    || maximumEntries > WECHAT_DISCOVERY_HARD_MAXIMUM_ENTRIES
  ) {
    incompatible('WECHAT_DISCOVERY_LIMIT_INVALID')
  }
  return { remaining: maximumEntries }
}

function boundedDirectories(path: string, budget: DiscoveryBudget): Dirent[] {
  if (!assertOrdinaryDirectoryChain(path, 'WECHAT_SOURCE_UNAVAILABLE', true)) return []
  let directory
  try {
    directory = opendirSync(path)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'ENOENT' || code === 'ENOTDIR') return []
    if (code === 'EACCES' || code === 'EPERM') incompatible('WECHAT_SOURCE_PERMISSION_DENIED')
    incompatible('WECHAT_SOURCE_UNAVAILABLE')
  }
  const entries: Dirent[] = []
  try {
    for (;;) {
      const entry = directory.readSync()
      if (entry === null) break
      if (budget.remaining === 0) incompatible('WECHAT_DISCOVERY_LIMIT_EXCEEDED')
      budget.remaining -= 1
      if (entry.isSymbolicLink()) continue
      if (entry.isDirectory() && entry.name !== '.' && entry.name !== '..') entries.push(entry)
    }
  } finally {
    directory.closeSync()
  }
  return entries
}

function isMissingCandidate(error: unknown): boolean {
  if (!(error instanceof SourceIncompatibleError)) return false
  return [
    'WECHAT_ACCOUNT_UNRESOLVED',
    'WECHAT_SOURCE_MISSING',
    'WECHAT_SOURCE_ENTRY_INVALID',
  ].includes(error.metadata.reason)
}

export function discoverWechatLiveSource(_options: {
  homeDirectory?: string
  maximumEntries?: number
} = {}): never {
  incompatible('WECHAT_ATOMIC_OPEN_UNAVAILABLE')
}

export function discoverTestOnlyNonAtomicWechatSource({
  homeDirectory,
  maximumEntries = 128,
}: {
  homeDirectory: string
  maximumEntries?: number
}): WechatSourcePaths | null {
  assertSafeAbsoluteRoot(homeDirectory)
  const physicalHome = resolve(homeDirectory)
  const budget = createDiscoveryBudget(maximumEntries)
  const candidates: WechatSourcePaths[] = []
  for (const layout of testOnlyCandidateLayouts) {
    const containerRoot = join(physicalHome, ...layout.container)
    const firstLevel = boundedDirectories(containerRoot, budget)
    const accountEntries = layout.accountDepth === 1
      ? firstLevel.map(entry => ({ root: containerRoot, account: entry.name }))
      : firstLevel.flatMap(parent => boundedDirectories(join(containerRoot, parent.name), budget)
          .map(entry => ({ root: join(containerRoot, parent.name), account: entry.name })))

    for (const entry of accountEntries) {
      try {
        candidates.push(resolveWechatSourcePaths({
          containerRoot: entry.root,
          accountDirectory: entry.account,
          adapterVersion: layout.adapterVersion,
        }))
      } catch (error) {
        if (isMissingCandidate(error)) continue
        throw error
      }
      if (candidates.length > 1) incompatible('WECHAT_ACCOUNT_AMBIGUOUS')
    }
  }
  return candidates[0] ?? null
}
