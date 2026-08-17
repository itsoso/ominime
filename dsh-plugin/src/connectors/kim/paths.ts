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

export const KIM_SOURCE = 'kim'
export const KIM_ADAPTER_VERSION = 'kim-macos-structured-v1'
export const KIM_SYNTHETIC_ADAPTER_VERSION = 'kim-synthetic-structured-v1'
export const KIM_SYNTHETIC_APP_VERSION = '0.0.0-synthetic'
export const KIM_DISCOVERY_HARD_MAXIMUM_ENTRIES = 1024

const syntheticStoreRelativePath = 'storage/chat/records.kimstore'

export type KimAdapterVersion = typeof KIM_ADAPTER_VERSION | typeof KIM_SYNTHETIC_ADAPTER_VERSION

export interface KimSourceRequest {
  readonly containerRoot: string
  readonly profileDirectory: string
  readonly adapterVersion: string
  readonly appVersion: string
  readonly storeRelativePath?: string
}

export interface KimSourcePaths {
  readonly containerRoot: string
  readonly profileDirectory: string
  readonly profileRoot: string
  readonly sourceDirectory: string
  readonly adapterVersion: KimAdapterVersion
  readonly appVersion: string
  readonly storeRelativePath: string
  readonly store: string
  readonly journal: string
  readonly sharedMemory: string
}

export function isKimLiveAdapterVersion(adapterVersion: string): boolean {
  return adapterVersion === KIM_ADAPTER_VERSION
}

function incompatible(reason: string): never {
  throw new SourceIncompatibleError({
    source: KIM_SOURCE,
    adapterVersion: KIM_ADAPTER_VERSION,
    observedVersion: null,
    reason,
  })
}

function safeLstat(path: string, missingReason: string) {
  try {
    return lstatSync(path, { throwIfNoEntry: false })
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'EACCES' || code === 'EPERM') incompatible('KIM_SOURCE_PERMISSION_DENIED')
    incompatible(missingReason)
  }
}

function safeRealpath(path: string, missingReason: string): string {
  try {
    return realpathSync(path)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'EACCES' || code === 'EPERM') incompatible('KIM_SOURCE_PERMISSION_DENIED')
    incompatible(missingReason)
  }
}

function hasRawParentTraversal(path: string): boolean {
  return path.split(/[\\/]+/).includes('..')
}

function assertAbsoluteRoot(path: string): void {
  if (!isAbsolute(path) || hasRawParentTraversal(path)) incompatible('KIM_PATH_ESCAPE')
}

function assertSingleDirectoryName(name: string): void {
  if (
    name === ''
    || name === '.'
    || name === '..'
    || isAbsolute(name)
    || name.includes('/')
    || name.includes('\\')
  ) {
    incompatible('KIM_PATH_ESCAPE')
  }
}

function assertDirectoryChain(
  path: string,
  missingReason: string,
  allowMissingTail = false,
): boolean {
  const absolute = resolve(path)
  const { root } = parse(absolute)
  const remainder = absolute.slice(root.length)
  const segments = remainder === '' ? [] : remainder.split(sep)
  let candidate = root
  for (const segment of ['', ...segments]) {
    if (segment !== '') candidate = join(candidate, segment)
    const stats = safeLstat(candidate, missingReason)
    if (stats === undefined) {
      if (allowMissingTail) return false
      incompatible(missingReason)
    }
    if (stats.isSymbolicLink()) incompatible('KIM_SYMLINK_REJECTED')
    if (!stats.isDirectory()) incompatible(missingReason)
  }
  return true
}

function assertDirectory(path: string, missingReason: string): void {
  const stats = safeLstat(path, missingReason)
  if (stats === undefined) incompatible(missingReason)
  if (stats.isSymbolicLink()) incompatible('KIM_SYMLINK_REJECTED')
  if (!stats.isDirectory()) incompatible(missingReason)
}

function assertFile(path: string, required: boolean): boolean {
  const stats = safeLstat(path, 'KIM_SOURCE_MISSING')
  if (stats === undefined) {
    if (required) incompatible('KIM_SOURCE_MISSING')
    return false
  }
  if (stats.isSymbolicLink()) incompatible('KIM_SYMLINK_REJECTED')
  if (!stats.isFile()) incompatible('KIM_SOURCE_ENTRY_INVALID')
  return true
}

function isContained(root: string, candidate: string): boolean {
  const remainder = relative(root, candidate)
  return remainder === ''
    || (!remainder.startsWith(`..${sep}`) && remainder !== '..' && !isAbsolute(remainder))
}

function assertStoreChain(profileRoot: string, relativePath: string): void {
  const segments = relativePath.split('/')
  let candidate = profileRoot
  for (const [index, segment] of segments.entries()) {
    candidate = join(candidate, segment)
    const stats = safeLstat(candidate, 'KIM_SOURCE_MISSING')
    if (stats === undefined) incompatible('KIM_SOURCE_MISSING')
    if (stats.isSymbolicLink()) incompatible('KIM_SYMLINK_REJECTED')
    if (index < segments.length - 1 && !stats.isDirectory()) {
      incompatible('KIM_SOURCE_ENTRY_INVALID')
    }
  }
}

export function resolveKimSourcePaths(request: KimSourceRequest): KimSourcePaths {
  if (request.adapterVersion !== KIM_ADAPTER_VERSION
    && request.adapterVersion !== KIM_SYNTHETIC_ADAPTER_VERSION) {
    incompatible('KIM_ADAPTER_UNKNOWN')
  }
  if (isKimLiveAdapterVersion(request.adapterVersion)) incompatible('KIM_ATOMIC_OPEN_UNAVAILABLE')
  if (request.appVersion !== KIM_SYNTHETIC_APP_VERSION) {
    incompatible('KIM_APP_VERSION_UNKNOWN')
  }
  const storeRelativePath = request.storeRelativePath ?? syntheticStoreRelativePath
  if (storeRelativePath !== syntheticStoreRelativePath) incompatible('KIM_FILE_UNRECOGNIZED')
  assertSingleDirectoryName(request.profileDirectory)
  assertAbsoluteRoot(request.containerRoot)

  const containerRoot = resolve(request.containerRoot)
  assertDirectoryChain(containerRoot, 'KIM_CONTAINER_UNRESOLVED')
  const canonicalContainer = safeRealpath(containerRoot, 'KIM_CONTAINER_UNRESOLVED')

  const profileRoot = join(containerRoot, request.profileDirectory)
  assertDirectory(profileRoot, 'KIM_PROFILE_UNRESOLVED')
  const canonicalProfile = safeRealpath(profileRoot, 'KIM_PROFILE_UNRESOLVED')
  if (!isContained(canonicalContainer, canonicalProfile)) incompatible('KIM_PATH_ESCAPE')
  if (canonicalProfile !== join(canonicalContainer, request.profileDirectory)) {
    incompatible('KIM_SYMLINK_REJECTED')
  }

  assertStoreChain(profileRoot, storeRelativePath)
  const store = join(profileRoot, ...storeRelativePath.split('/'))
  assertFile(store, true)
  const canonicalStore = safeRealpath(store, 'KIM_SOURCE_MISSING')
  if (!isContained(canonicalContainer, canonicalStore)) incompatible('KIM_PATH_ESCAPE')

  const journal = `${store}.journal`
  const sharedMemory = `${store}.shared`
  for (const optional of [journal, sharedMemory]) {
    if (!assertFile(optional, false)) continue
    const canonicalOptional = safeRealpath(optional, 'KIM_SOURCE_MISSING')
    if (!isContained(canonicalContainer, canonicalOptional)) incompatible('KIM_PATH_ESCAPE')
  }

  return Object.freeze({
    containerRoot,
    profileDirectory: request.profileDirectory,
    profileRoot,
    sourceDirectory: join(store, '..'),
    adapterVersion: request.adapterVersion,
    appVersion: request.appVersion,
    storeRelativePath,
    store,
    journal,
    sharedMemory,
  })
}

interface DiscoveryBudget {
  remaining: number
}

function createDiscoveryBudget(maximumEntries: number): DiscoveryBudget {
  if (
    !Number.isSafeInteger(maximumEntries)
    || maximumEntries <= 0
    || maximumEntries > KIM_DISCOVERY_HARD_MAXIMUM_ENTRIES
  ) {
    incompatible('KIM_DISCOVERY_LIMIT_INVALID')
  }
  return { remaining: maximumEntries }
}

function boundedDirectories(path: string, budget: DiscoveryBudget): Dirent[] {
  if (!assertDirectoryChain(path, 'KIM_SOURCE_UNAVAILABLE', true)) return []
  let directory
  try {
    directory = opendirSync(path)
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    if (code === 'ENOENT' || code === 'ENOTDIR') return []
    if (code === 'EACCES' || code === 'EPERM') incompatible('KIM_SOURCE_PERMISSION_DENIED')
    incompatible('KIM_SOURCE_UNAVAILABLE')
  }
  const entries: Dirent[] = []
  try {
    for (;;) {
      const entry = directory.readSync()
      if (entry === null) break
      if (budget.remaining === 0) incompatible('KIM_DISCOVERY_LIMIT_EXCEEDED')
      budget.remaining -= 1
      if (!entry.isSymbolicLink() && entry.isDirectory() && entry.name !== '.' && entry.name !== '..') {
        entries.push(entry)
      }
    }
  } finally {
    directory.closeSync()
  }
  return entries
}

function missingCandidate(error: unknown): boolean {
  return error instanceof SourceIncompatibleError && [
    'KIM_PROFILE_UNRESOLVED',
    'KIM_SOURCE_MISSING',
    'KIM_SOURCE_ENTRY_INVALID',
  ].includes(error.metadata.reason)
}

export function discoverKimLiveSource(_options: {
  homeDirectory?: string
  maximumEntries?: number
} = {}): never {
  incompatible('KIM_ATOMIC_OPEN_UNAVAILABLE')
}

export function discoverTestOnlyNonAtomicKimSource({
  homeDirectory,
  maximumEntries = 128,
}: {
  homeDirectory: string
  maximumEntries?: number
}): KimSourcePaths | null {
  assertAbsoluteRoot(homeDirectory)
  const containerRoot = join(
    resolve(homeDirectory),
    'Library',
    'Containers',
    'com.ominime.kim.synthetic',
    'Data',
    'Documents',
    'kim-fixture',
  )
  const budget = createDiscoveryBudget(maximumEntries)
  const candidates: KimSourcePaths[] = []
  for (const entry of boundedDirectories(containerRoot, budget)) {
    try {
      candidates.push(resolveKimSourcePaths({
        containerRoot,
        profileDirectory: entry.name,
        adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
        appVersion: KIM_SYNTHETIC_APP_VERSION,
      }))
    } catch (error) {
      if (missingCandidate(error)) continue
      throw error
    }
    if (candidates.length > 1) incompatible('KIM_PROFILE_AMBIGUOUS')
  }
  return candidates[0] ?? null
}
