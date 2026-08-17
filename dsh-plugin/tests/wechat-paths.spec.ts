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
  WECHAT_ADAPTER_VERSION,
  WECHAT_DISCOVERY_HARD_MAXIMUM_ENTRIES,
  WECHAT_SYNTHETIC_ADAPTER_VERSION,
  discoverTestOnlyNonAtomicWechatSource,
  discoverWechatLiveSource,
  resolveWechatSourcePaths,
} from '../src/connectors/wechat/paths.ts'
import { withTestOnlyNonAtomicWechatSnapshot } from '../src/connectors/wechat/snapshot.ts'

const roots: string[] = []

afterEach(() => {
  while (roots.length > 0) rmSync(roots.pop()!, { recursive: true, force: true })
})

function createTemporaryRoot(prefix = 'ominime-wechat-paths-') {
  const temporaryRoot = mkdtempSync(join(realpathSync(tmpdir()), prefix))
  roots.push(temporaryRoot)
  return temporaryRoot
}

function writeSyntheticSource(containerRoot: string, accountDirectory = 'invented-account') {
  const database = join(
    containerRoot,
    accountDirectory,
    'db_storage',
    'message',
    'message_0.db',
  )
  mkdirSync(join(database, '..'), { recursive: true })
  writeFileSync(database, 'synthetic database bytes', { mode: 0o400 })
  return database
}

function createSource() {
  const temporaryRoot = createTemporaryRoot()
  const containerRoot = join(temporaryRoot, 'container')
  const accountDirectory = 'invented-account'
  const database = writeSyntheticSource(containerRoot, accountDirectory)
  return { temporaryRoot, containerRoot, accountDirectory, database }
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
    metadata: { source: 'wechat', reason },
  })
}

describe('WeChat source path containment', () => {
  it('fails closed before touching a live path when atomic open is unavailable', async () => {
    const privatePath = '/invented-private-live-root'
    expectReason(() => resolveWechatSourcePaths({
      containerRoot: privatePath,
      accountDirectory: 'invented-private-account',
      adapterVersion: WECHAT_ADAPTER_VERSION,
    }), 'WECHAT_ATOMIC_OPEN_UNAVAILABLE')
    expectReason(
      () => discoverWechatLiveSource({ homeDirectory: privatePath }),
      'WECHAT_ATOMIC_OPEN_UNAVAILABLE',
    )
  })

  it('accepts a regular directory chain and resolves only adapter-owned file names', () => {
    const source = createSource()
    const resolved = resolveWechatSourcePaths({
      containerRoot: source.containerRoot,
      accountDirectory: source.accountDirectory,
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    })

    expect(resolved.database).toBe(source.database)
    expect(resolved.wal).toBe(`${source.database}-wal`)
    expect(resolved.shm).toBe(`${source.database}-shm`)
    expect(Object.isFrozen(resolved)).toBe(true)
  })

  it('rejects an ancestor symlink that escapes the lexical tree or stays inside it', () => {
    const temporaryRoot = createTemporaryRoot()
    const declaredRoot = join(temporaryRoot, 'declared')
    const outsideRoot = join(temporaryRoot, 'outside')
    const insideTarget = join(declaredRoot, 'inside-target')
    mkdirSync(declaredRoot)

    for (const [linkName, target] of [
      ['outside-link', outsideRoot],
      ['inside-link', insideTarget],
    ] as const) {
      const containerRoot = join(target, 'container')
      writeSyntheticSource(containerRoot)
      symlinkSync(target, join(declaredRoot, linkName))

      expectReason(() => resolveWechatSourcePaths({
        containerRoot: join(declaredRoot, linkName, 'container'),
        accountDirectory: 'invented-account',
        adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
      }), 'WECHAT_SYMLINK_REJECTED')
    }
  })

  it('rejects a non-directory ancestor and parent traversal in the configured root', () => {
    const source = createSource()
    const ordinaryFile = join(source.temporaryRoot, 'ordinary-file')
    writeFileSync(ordinaryFile, 'invented')

    expectReason(() => resolveWechatSourcePaths({
      containerRoot: join(ordinaryFile, 'container'),
      accountDirectory: source.accountDirectory,
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    }), 'WECHAT_CONTAINER_UNRESOLVED')

    expectReason(() => resolveWechatSourcePaths({
      containerRoot: `${source.temporaryRoot}/unused/../container`,
      accountDirectory: source.accountDirectory,
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    }), 'WECHAT_PATH_ESCAPE')
  })

  it('uses fixed path-free errors for missing and permission-denied ancestors', () => {
    const temporaryRoot = createTemporaryRoot()
    const missingContainer = join(temporaryRoot, 'private-missing-value', 'container')
    let missingError: unknown
    try {
      resolveWechatSourcePaths({
        containerRoot: missingContainer,
        accountDirectory: 'invented-account',
        adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
      })
    } catch (error) {
      missingError = error
    }
    expect(missingError).toMatchObject({ metadata: { reason: 'WECHAT_CONTAINER_UNRESOLVED' } })
    expect(JSON.stringify(missingError)).not.toContain('private-missing-value')

    const restricted = join(temporaryRoot, 'private-restricted-value')
    writeSyntheticSource(join(restricted, 'container'))
    chmodSync(restricted, 0o000)
    let permissionError: unknown
    try {
      resolveWechatSourcePaths({
        containerRoot: join(restricted, 'container'),
        accountDirectory: 'invented-account',
        adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
      })
    } catch (error) {
      permissionError = error
    } finally {
      chmodSync(restricted, 0o700)
    }
    expect(permissionError).toMatchObject({ metadata: { reason: 'WECHAT_SOURCE_PERMISSION_DENIED' } })
    expect(JSON.stringify(permissionError)).not.toContain('private-restricted-value')
  })

  it('rejects traversal and an account outside the configured container', () => {
    const source = createSource()
    const outside = join(source.temporaryRoot, 'outside')
    mkdirSync(outside)

    for (const accountDirectory of ['../outside', outside]) {
      expectReason(() => resolveWechatSourcePaths({
        containerRoot: source.containerRoot,
        accountDirectory,
        adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
      }), 'WECHAT_PATH_ESCAPE')
    }
  })

  it('rejects symlinked roots, accounts, entries, and intermediate directories', () => {
    const source = createSource()
    const outside = join(source.temporaryRoot, 'outside')
    mkdirSync(outside)

    const rootLink = join(source.temporaryRoot, 'root-link')
    symlinkSync(source.containerRoot, rootLink)
    expectReason(() => resolveWechatSourcePaths({
      containerRoot: rootLink,
      accountDirectory: source.accountDirectory,
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    }), 'WECHAT_SYMLINK_REJECTED')

    const accountLink = 'linked-account'
    symlinkSync(outside, join(source.containerRoot, accountLink))
    expectReason(() => resolveWechatSourcePaths({
      containerRoot: source.containerRoot,
      accountDirectory: accountLink,
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    }), 'WECHAT_SYMLINK_REJECTED')

    const linkedEntryAccount = join(source.containerRoot, 'linked-entry')
    mkdirSync(join(linkedEntryAccount, 'db_storage', 'message'), { recursive: true })
    symlinkSync(source.database, join(linkedEntryAccount, 'db_storage', 'message', 'message_0.db'))
    expectReason(() => resolveWechatSourcePaths({
      containerRoot: source.containerRoot,
      accountDirectory: 'linked-entry',
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    }), 'WECHAT_SYMLINK_REJECTED')

    const linkedIntermediateAccount = join(source.containerRoot, 'linked-intermediate')
    mkdirSync(linkedIntermediateAccount)
    symlinkSync(join(source.containerRoot, source.accountDirectory, 'db_storage'), join(linkedIntermediateAccount, 'db_storage'))
    expectReason(() => resolveWechatSourcePaths({
      containerRoot: source.containerRoot,
      accountDirectory: 'linked-intermediate',
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    }), 'WECHAT_SYMLINK_REJECTED')
  })

  it('rejects unresolved accounts without echoing path or account values', () => {
    const source = createSource()
    const privateAccount = 'invented-private-account-value'
    let error: unknown
    try {
      resolveWechatSourcePaths({
        containerRoot: source.containerRoot,
        accountDirectory: privateAccount,
        adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
      })
    } catch (candidate) {
      error = candidate
    }

    expect(error).toMatchObject({ metadata: { reason: 'WECHAT_ACCOUNT_UNRESOLVED' } })
    expect(String(error)).not.toContain(privateAccount)
    expect(String(error)).not.toContain(source.temporaryRoot)
    expect(JSON.stringify(error)).not.toContain(privateAccount)
    expect(JSON.stringify(error)).not.toContain(source.temporaryRoot)
  })

  it('rejects unknown adapter versions and unrecognized database file names', () => {
    const source = createSource()
    expectReason(() => resolveWechatSourcePaths({
      containerRoot: source.containerRoot,
      accountDirectory: source.accountDirectory,
      adapterVersion: 'invented-unknown-version',
    }), 'WECHAT_ADAPTER_UNKNOWN')

    expectReason(() => resolveWechatSourcePaths({
      containerRoot: source.containerRoot,
      accountDirectory: source.accountDirectory,
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
      databaseRelativePath: 'db_storage/message/not-recognized.db',
    }), 'WECHAT_FILE_UNRECOGNIZED')
  })

  it('fails closed before any writable source open can occur', async () => {
    const source = createSource()
    const paths = resolveWechatSourcePaths({
      containerRoot: source.containerRoot,
      accountDirectory: source.accountDirectory,
      adapterVersion: WECHAT_SYNTHETIC_ADAPTER_VERSION,
    })

    await expect(withTestOnlyNonAtomicWechatSnapshot(paths, async () => undefined, {
      sourceOpenMode: 'read-write' as never,
      temporaryParent: source.temporaryRoot,
    })).rejects.toMatchObject({
      code: 'SOURCE_INCOMPATIBLE',
      metadata: { reason: 'WECHAT_WRITABLE_SOURCE_OPEN_REJECTED' },
    })
  })

  it('uses only fixed-depth known macOS containers for bounded live discovery', () => {
    const temporaryHome = createTemporaryRoot('ominime-wechat-home-')
    const knownContainer = join(
      temporaryHome,
      'Library',
      'Containers',
      'com.tencent.xinWeChat',
      'Data',
      'Documents',
      'xwechat_files',
    )
    const database = join(
      knownContainer,
      'invented-account',
      'db_storage',
      'message',
      'message_0.db',
    )
    mkdirSync(join(database, '..'), { recursive: true })
    writeFileSync(database, 'synthetic database bytes', { mode: constants.S_IRUSR })

    const candidate = discoverTestOnlyNonAtomicWechatSource({ homeDirectory: temporaryHome })
    expect(candidate).not.toBeNull()
    expect(candidate?.database).toBe(database)

    const unrelated = join(temporaryHome, 'unrelated', 'account', 'db_storage', 'message', 'message_0.db')
    mkdirSync(join(unrelated, '..'), { recursive: true })
    writeFileSync(unrelated, 'must never be discovered')
    rmSync(knownContainer, { recursive: true, force: true })
    expect(discoverTestOnlyNonAtomicWechatSource({ homeDirectory: temporaryHome })).toBeNull()
    expect(existsSync(unrelated)).toBe(true)
  })

  it('bounds every inspected directory entry, not only candidate directories', () => {
    const temporaryHome = createTemporaryRoot('ominime-wechat-home-')
    const knownContainer = join(
      temporaryHome,
      'Library',
      'Containers',
      'com.tencent.xinWeChat',
      'Data',
      'Documents',
      'xwechat_files',
    )
    mkdirSync(knownContainer, { recursive: true })
    for (const name of ['invented-a', 'invented-b', 'invented-c']) {
      writeFileSync(join(knownContainer, name), 'invented non-candidate')
    }

    expectReason(
      () => discoverTestOnlyNonAtomicWechatSource({ homeDirectory: temporaryHome, maximumEntries: 2 }),
      'WECHAT_DISCOVERY_LIMIT_EXCEEDED',
    )
  })

  it('rejects invalid discovery limits and shares one budget across nested levels', () => {
    const temporaryHome = createTemporaryRoot('ominime-wechat-home-')
    for (const maximumEntries of [0, -1, 1.5, Number.NaN, Number.POSITIVE_INFINITY,
      WECHAT_DISCOVERY_HARD_MAXIMUM_ENTRIES + 1]) {
      expectReason(
        () => discoverTestOnlyNonAtomicWechatSource({ homeDirectory: temporaryHome, maximumEntries }),
        'WECHAT_DISCOVERY_LIMIT_INVALID',
      )
    }

    const nestedContainer = join(
      temporaryHome,
      'Library',
      'Containers',
      'com.tencent.xinWeChat',
      'Data',
      'Library',
      'Application Support',
      'com.tencent.xinWeChat',
    )
    writeSyntheticSource(join(nestedContainer, 'invented-parent'))

    expectReason(
      () => discoverTestOnlyNonAtomicWechatSource({ homeDirectory: temporaryHome, maximumEntries: 1 }),
      'WECHAT_DISCOVERY_LIMIT_EXCEEDED',
    )
    expect(discoverTestOnlyNonAtomicWechatSource({
      homeDirectory: temporaryHome,
      maximumEntries: 2,
    })?.adapterVersion).toBe(WECHAT_SYNTHETIC_ADAPTER_VERSION)
  })
})
