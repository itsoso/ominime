import { constants, createReadStream } from 'node:fs'
import { access, lstat } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { isAbsolute } from 'node:path'

const SHA256_PATTERN = /^[a-f0-9]{64}$/

export type ChatkimConfigErrorCode =
  | 'CHATKIM_CONFIG_MISSING'
  | 'CHATKIM_PATH_INVALID'
  | 'CHATKIM_HASH_INVALID'
  | 'CHATKIM_FILE_UNSAFE'
  | 'CHATKIM_HASH_FAILED'
  | 'CHATKIM_HASH_MISMATCH'

export class ChatkimConfigError extends Error {
  declare readonly code: ChatkimConfigErrorCode

  constructor(code: ChatkimConfigErrorCode) {
    super('Kim chat reader configuration is unavailable or unsafe')
    this.name = 'ChatkimConfigError'
    Object.defineProperty(this, 'code', { enumerable: true, value: code })
  }
}

export interface ChatkimEnvironment {
  readonly OMINIME_CHATKIM_BIN?: string
  readonly OMINIME_CHATKIM_SHA256?: string
}

export interface ResolvedChatkimExecutable {
  readonly binaryPath: string
  readonly sha256: string
}

export interface ResolveChatkimOptions {
  readonly signal?: AbortSignal
  readonly hashFile?: (path: string, signal?: AbortSignal) => Promise<string>
}

async function hashFile(path: string, signal?: AbortSignal): Promise<string> {
  signal?.throwIfAborted()
  const hash = createHash('sha256')
  const stream = createReadStream(path, { signal })
  for await (const chunk of stream) hash.update(chunk as Buffer)
  signal?.throwIfAborted()
  return hash.digest('hex')
}

export async function resolveChatkimExecutable(
  environment: ChatkimEnvironment,
  options: ResolveChatkimOptions = {},
): Promise<Readonly<ResolvedChatkimExecutable>> {
  options.signal?.throwIfAborted()
  const binaryPath = environment.OMINIME_CHATKIM_BIN?.trim()
  const expectedHash = environment.OMINIME_CHATKIM_SHA256?.trim()
  if (binaryPath === undefined || binaryPath === '' || expectedHash === undefined || expectedHash === '') {
    throw new ChatkimConfigError('CHATKIM_CONFIG_MISSING')
  }
  if (!isAbsolute(binaryPath)) throw new ChatkimConfigError('CHATKIM_PATH_INVALID')
  if (!SHA256_PATTERN.test(expectedHash)) throw new ChatkimConfigError('CHATKIM_HASH_INVALID')

  try {
    const stats = await lstat(binaryPath)
    if (stats.isSymbolicLink() || !stats.isFile() || (stats.mode & 0o022) !== 0 || (stats.mode & 0o111) === 0) {
      throw new ChatkimConfigError('CHATKIM_FILE_UNSAFE')
    }
    await access(binaryPath, constants.X_OK)
  } catch (error) {
    if (error instanceof ChatkimConfigError) throw error
    options.signal?.throwIfAborted()
    throw new ChatkimConfigError('CHATKIM_FILE_UNSAFE')
  }

  let actualHash: string
  try {
    actualHash = await (options.hashFile ?? hashFile)(binaryPath, options.signal)
  } catch {
    options.signal?.throwIfAborted()
    throw new ChatkimConfigError('CHATKIM_HASH_FAILED')
  }
  options.signal?.throwIfAborted()
  if (actualHash !== expectedHash) throw new ChatkimConfigError('CHATKIM_HASH_MISMATCH')
  return Object.freeze({ binaryPath, sha256: expectedHash })
}
