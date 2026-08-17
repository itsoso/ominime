import {
  chmodSync,
  constants,
  existsSync,
  mkdirSync,
  mkdtempSync,
  realpathSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import { SourceIncompatibleError } from '../src/connectors/contract.ts'
import {
  KIM_ADAPTER_VERSION,
  KIM_DISCOVERY_HARD_MAXIMUM_ENTRIES,
  KIM_SYNTHETIC_ADAPTER_VERSION,
  KIM_SYNTHETIC_APP_VERSION,
  discoverKimLiveSource,
  discoverTestOnlyNonAtomicKimSource,
  resolveKimSourcePaths,
} from '../src/connectors/kim/paths.ts'
import { withTestOnlyNonAtomicKimSnapshot } from '../src/connectors/kim/snapshot.ts'

const roots: string[] = []

afterEach(() => {
  while (roots.length > 0) rmSync(roots.pop()!, { recursive: true, force: true })
})

function temporaryRoot(prefix = 'ominime-kim-paths-'): string {
  const root = mkdtempSync(join(realpathSync(tmpdir()), prefix))
  roots.push(root)
  return root
}

function writeSyntheticStore(containerRoot: string, profileDirectory = 'invented-profile'): string {
  const store = join(containerRoot, profileDirectory, 'storage', 'chat', 'records.kimstore')
  mkdirSync(join(store, '..'), { recursive: true })
  writeFileSync(store, 'invented structured bytes', { mode: constants.S_IRUSR })
  return store
}

function sourceFixture() {
  const root = temporaryRoot()
  const containerRoot = join(root, 'container')
  const profileDirectory = 'invented-profile'
  const store = writeSyntheticStore(containerRoot, profileDirectory)
  return { root, containerRoot, profileDirectory, store }
}

function expectReason(action: () => unknown, reason: string): void {
  let error: unknown
  try {
    action()
  } catch (candidate) {
    error = candidate
  }
  expect(error).toBeInstanceOf(SourceIncompatibleError)
  expect(error).toMatchObject({
    code: 'SOURCE_INCOMPATIBLE',
    metadata: { source: 'kim', reason },
  })
}

describe('Kim source path containment', () => {
  it('fails closed before touching a live path when atomic open is unavailable', () => {
    const privatePath = '/invented-private-kim-root'
    expectReason(() => resolveKimSourcePaths({
      containerRoot: privatePath,
      profileDirectory: 'invented-private-profile',
      adapterVersion: KIM_ADAPTER_VERSION,
      appVersion: 'invented-live-version',
    }), 'KIM_ATOMIC_OPEN_UNAVAILABLE')
    expectReason(
      () => discoverKimLiveSource({ homeDirectory: privatePath }),
      'KIM_ATOMIC_OPEN_UNAVAILABLE',
    )
  })

  it('resolves only the synthetic adapter-owned whitelist', () => {
    const source = sourceFixture()
    const paths = resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: source.profileDirectory,
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    })

    expect(paths.store).toBe(source.store)
    expect(paths.journal).toBe(`${source.store}.journal`)
    expect(paths.sharedMemory).toBe(`${source.store}.shared`)
    expect(Object.isFrozen(paths)).toBe(true)
  })

  it('rejects root and ancestor symlinks whether they escape or stay inside', () => {
    const root = temporaryRoot()
    const declared = join(root, 'declared')
    const outside = join(root, 'outside')
    const inside = join(declared, 'inside')
    mkdirSync(declared)

    for (const [name, target] of [['outside-link', outside], ['inside-link', inside]] as const) {
      const containerRoot = join(target, 'container')
      writeSyntheticStore(containerRoot)
      symlinkSync(target, join(declared, name))
      expectReason(() => resolveKimSourcePaths({
        containerRoot: join(declared, name, 'container'),
        profileDirectory: 'invented-profile',
        adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
        appVersion: KIM_SYNTHETIC_APP_VERSION,
      }), 'KIM_SYMLINK_REJECTED')
    }
  })

  it('rejects raw parent traversal and non-directory ancestors', () => {
    const source = sourceFixture()
    const ordinaryFile = join(source.root, 'ordinary-file')
    writeFileSync(ordinaryFile, 'invented')

    expectReason(() => resolveKimSourcePaths({
      containerRoot: `${source.root}/unused/../container`,
      profileDirectory: source.profileDirectory,
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    }), 'KIM_PATH_ESCAPE')
    expectReason(() => resolveKimSourcePaths({
      containerRoot: join(ordinaryFile, 'container'),
      profileDirectory: source.profileDirectory,
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    }), 'KIM_CONTAINER_UNRESOLVED')
  })

  it('uses fixed path-free errors for missing and denied ancestors', () => {
    const root = temporaryRoot()
    const missing = join(root, 'private-missing-value', 'container')
    let missingError: unknown
    try {
      resolveKimSourcePaths({
        containerRoot: missing,
        profileDirectory: 'invented-profile',
        adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
        appVersion: KIM_SYNTHETIC_APP_VERSION,
      })
    } catch (candidate) {
      missingError = candidate
    }
    expect(missingError).toMatchObject({ metadata: { reason: 'KIM_CONTAINER_UNRESOLVED' } })
    expect(JSON.stringify(missingError)).not.toContain('private-missing-value')

    const restricted = join(root, 'private-restricted-value')
    writeSyntheticStore(join(restricted, 'container'))
    chmodSync(restricted, 0o000)
    let denied: unknown
    try {
      resolveKimSourcePaths({
        containerRoot: join(restricted, 'container'),
        profileDirectory: 'invented-profile',
        adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
        appVersion: KIM_SYNTHETIC_APP_VERSION,
      })
    } catch (candidate) {
      denied = candidate
    } finally {
      chmodSync(restricted, 0o700)
    }
    expect(denied).toMatchObject({ metadata: { reason: 'KIM_SOURCE_PERMISSION_DENIED' } })
    expect(JSON.stringify(denied)).not.toContain('private-restricted-value')
  })

  it('rejects profile traversal and unresolved profiles without echoing values', () => {
    const source = sourceFixture()
    const outside = join(source.root, 'outside')
    mkdirSync(outside)
    for (const profileDirectory of ['../outside', outside]) {
      expectReason(() => resolveKimSourcePaths({
        containerRoot: source.containerRoot,
        profileDirectory,
        adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
        appVersion: KIM_SYNTHETIC_APP_VERSION,
      }), 'KIM_PATH_ESCAPE')
    }

    const privateProfile = 'invented-private-profile-value'
    let error: unknown
    try {
      resolveKimSourcePaths({
        containerRoot: source.containerRoot,
        profileDirectory: privateProfile,
        adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
        appVersion: KIM_SYNTHETIC_APP_VERSION,
      })
    } catch (candidate) {
      error = candidate
    }
    expect(error).toMatchObject({ metadata: { reason: 'KIM_PROFILE_UNRESOLVED' } })
    expect(String(error)).not.toContain(privateProfile)
    expect(JSON.stringify(error)).not.toContain(source.root)
  })

  it('rejects profile, intermediate, store, and sidecar symlinks', () => {
    const source = sourceFixture()
    const outside = join(source.root, 'outside')
    mkdirSync(outside)

    symlinkSync(outside, join(source.containerRoot, 'linked-profile'))
    expectReason(() => resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: 'linked-profile',
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    }), 'KIM_SYMLINK_REJECTED')

    const intermediateProfile = join(source.containerRoot, 'linked-intermediate')
    mkdirSync(intermediateProfile)
    symlinkSync(join(source.containerRoot, source.profileDirectory, 'storage'), join(intermediateProfile, 'storage'))
    expectReason(() => resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: 'linked-intermediate',
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    }), 'KIM_SYMLINK_REJECTED')

    const linkedStoreProfile = join(source.containerRoot, 'linked-store')
    mkdirSync(join(linkedStoreProfile, 'storage', 'chat'), { recursive: true })
    symlinkSync(source.store, join(linkedStoreProfile, 'storage', 'chat', 'records.kimstore'))
    expectReason(() => resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: 'linked-store',
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    }), 'KIM_SYMLINK_REJECTED')

    symlinkSync(outside, `${source.store}.journal`)
    expectReason(() => resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: source.profileDirectory,
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    }), 'KIM_SYMLINK_REJECTED')
  })

  it('rejects unknown adapters, app versions, and file names instead of guessing', () => {
    const source = sourceFixture()
    expectReason(() => resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: source.profileDirectory,
      adapterVersion: 'invented-adapter',
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    }), 'KIM_ADAPTER_UNKNOWN')
    expectReason(() => resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: source.profileDirectory,
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: 'invented-app-version',
    }), 'KIM_APP_VERSION_UNKNOWN')
    expectReason(() => resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: source.profileDirectory,
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
      storeRelativePath: 'storage/chat/guessed.kimstore',
    }), 'KIM_FILE_UNRECOGNIZED')
  })

  it('rejects writable source access before opening a source file', async () => {
    const source = sourceFixture()
    const paths = resolveKimSourcePaths({
      containerRoot: source.containerRoot,
      profileDirectory: source.profileDirectory,
      adapterVersion: KIM_SYNTHETIC_ADAPTER_VERSION,
      appVersion: KIM_SYNTHETIC_APP_VERSION,
    })
    await expect(withTestOnlyNonAtomicKimSnapshot(paths, async () => undefined, {
      sourceOpenMode: 'read-write' as never,
      temporaryParent: source.root,
    })).rejects.toMatchObject({ metadata: { reason: 'KIM_WRITABLE_SOURCE_OPEN_REJECTED' } })
  })

  it('discovers only one fixed-depth synthetic bundle and ignores unrelated trees', () => {
    const home = temporaryRoot('ominime-kim-home-')
    const knownContainer = join(
      home,
      'Library',
      'Containers',
      'com.ominime.kim.synthetic',
      'Data',
      'Documents',
      'kim-fixture',
    )
    const store = writeSyntheticStore(knownContainer)
    const unrelated = join(home, 'unrelated', 'profile', 'storage', 'chat', 'records.kimstore')
    mkdirSync(join(unrelated, '..'), { recursive: true })
    writeFileSync(unrelated, 'must remain unread')

    expect(discoverTestOnlyNonAtomicKimSource({ homeDirectory: home })?.store).toBe(store)
    rmSync(knownContainer, { recursive: true, force: true })
    expect(discoverTestOnlyNonAtomicKimSource({ homeDirectory: home })).toBeNull()
    expect(existsSync(unrelated)).toBe(true)
  })

  it('uses one bounded Dirent budget and rejects invalid limits', () => {
    const home = temporaryRoot('ominime-kim-home-')
    const knownContainer = join(
      home,
      'Library',
      'Containers',
      'com.ominime.kim.synthetic',
      'Data',
      'Documents',
      'kim-fixture',
    )
    mkdirSync(knownContainer, { recursive: true })
    for (const name of ['invented-a', 'invented-b', 'invented-c']) {
      writeFileSync(join(knownContainer, name), 'non-directory')
    }
    expectReason(
      () => discoverTestOnlyNonAtomicKimSource({ homeDirectory: home, maximumEntries: 2 }),
      'KIM_DISCOVERY_LIMIT_EXCEEDED',
    )
    for (const maximumEntries of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY,
      KIM_DISCOVERY_HARD_MAXIMUM_ENTRIES + 1]) {
      expectReason(
        () => discoverTestOnlyNonAtomicKimSource({ homeDirectory: home, maximumEntries }),
        'KIM_DISCOVERY_LIMIT_INVALID',
      )
    }
  })
})
