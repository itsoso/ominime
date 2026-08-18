import { chmod, mkdtemp, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, relative } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'

import {
  ChatkimConfigError,
  resolveChatkimExecutable,
} from '../src/chatkim/config.ts'

const VALID_HASH = 'a'.repeat(64)
const roots: string[] = []

async function fixture(): Promise<{ root: string, binary: string }> {
  const root = await mkdtemp(join(tmpdir(), 'ominime-chatkim-config-'))
  roots.push(root)
  const binary = join(root, 'chatkimv2')
  await writeFile(binary, '#!/bin/sh\nexit 0\n', { mode: 0o700 })
  return { root, binary }
}

afterEach(async () => {
  await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true })))
})

describe('chatkim executable provenance', () => {
  it.each([
    [{}, 'CHATKIM_CONFIG_MISSING'],
    [{ OMINIME_CHATKIM_BIN: '/tmp/tool' }, 'CHATKIM_CONFIG_MISSING'],
    [{ OMINIME_CHATKIM_SHA256: VALID_HASH }, 'CHATKIM_CONFIG_MISSING'],
  ])('rejects incomplete configuration without echoing values', async (environment, code) => {
    const error = await resolveChatkimExecutable(environment).catch((caught: unknown) => caught)
    expect(error).toBeInstanceOf(ChatkimConfigError)
    expect(error).toMatchObject({ code })
    expect(String(error)).not.toContain('/tmp/tool')
    expect(String(error)).not.toContain(VALID_HASH)
  })

  it('rejects a relative executable path before filesystem access', async () => {
    const error = await resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: relative(process.cwd(), join(process.cwd(), 'chatkimv2')),
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }).catch((caught: unknown) => caught)
    expect(error).toMatchObject({ code: 'CHATKIM_PATH_INVALID' })
  })

  it('rejects malformed or uppercase hashes', async () => {
    const { binary } = await fixture()
    for (const hash of ['abc', 'A'.repeat(64), `${VALID_HASH}0`]) {
      const error = await resolveChatkimExecutable({
        OMINIME_CHATKIM_BIN: binary,
        OMINIME_CHATKIM_SHA256: hash,
      }).catch((caught: unknown) => caught)
      expect(error).toMatchObject({ code: 'CHATKIM_HASH_INVALID' })
    }
  })

  it('rejects symlinks and group/world-writable executables', async () => {
    const { root, binary } = await fixture()
    const link = join(root, 'chatkim-link')
    await symlink(binary, link)

    await expect(resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: link,
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }, { hashFile: async () => VALID_HASH })).rejects.toMatchObject({
      code: 'CHATKIM_FILE_UNSAFE',
    })

    await chmod(binary, 0o722)
    await expect(resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: binary,
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }, { hashFile: async () => VALID_HASH })).rejects.toMatchObject({
      code: 'CHATKIM_FILE_UNSAFE',
    })
  })

  it('rejects a non-regular file and a non-executable regular file', async () => {
    const { root, binary } = await fixture()
    await expect(resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: root,
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }, { hashFile: async () => VALID_HASH })).rejects.toMatchObject({
      code: 'CHATKIM_FILE_UNSAFE',
    })

    await chmod(binary, 0o600)
    await expect(resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: binary,
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }, { hashFile: async () => VALID_HASH })).rejects.toMatchObject({
      code: 'CHATKIM_FILE_UNSAFE',
    })
  })

  it('rejects a hash mismatch and accepts one exact safe executable', async () => {
    const { binary } = await fixture()
    await expect(resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: binary,
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }, { hashFile: async () => 'b'.repeat(64) })).rejects.toMatchObject({
      code: 'CHATKIM_HASH_MISMATCH',
    })

    const resolved = await resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: binary,
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }, { hashFile: async () => VALID_HASH })
    expect(resolved).toEqual({ binaryPath: binary, sha256: VALID_HASH })
    expect(Object.isFrozen(resolved)).toBe(true)
  })

  it('propagates cancellation without rewriting the abort reason', async () => {
    const { binary } = await fixture()
    const controller = new AbortController()
    const reason = new Error('cancelled by test')
    controller.abort(reason)

    await expect(resolveChatkimExecutable({
      OMINIME_CHATKIM_BIN: binary,
      OMINIME_CHATKIM_SHA256: VALID_HASH,
    }, {
      signal: controller.signal,
      hashFile: async (_path, signal) => {
        signal?.throwIfAborted()
        return VALID_HASH
      },
    })).rejects.toBe(reason)
  })
})
