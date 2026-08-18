import { execFile } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)
const temporaryPrefix = join(tmpdir(), 'ominime-loopback-cert-')

export async function generateTestCertificate({
  runner = execFileAsync,
  makeTemporaryDirectory = () => mkdtemp(temporaryPrefix),
  removeTemporaryDirectory = (directory, options) => rm(directory, options),
} = {}) {
  const directory = await makeTemporaryDirectory()
  const keyPath = join(directory, 'key.pem')
  const certPath = join(directory, 'cert.pem')
  let cleaned = false
  let cleanupInFlight = null
  const cleanup = () => {
    if (cleaned) return Promise.resolve()
    if (cleanupInFlight !== null) return cleanupInFlight
    if (typeof directory !== 'string' || !directory.startsWith(temporaryPrefix)) {
      return Promise.reject(new Error('SYNTHETIC_CERT_CLEANUP_REFUSED'))
    }
    const attempt = Promise.resolve().then(async () => {
      await removeTemporaryDirectory(directory, { recursive: true, force: true })
      cleaned = true
    })
    cleanupInFlight = attempt
    void attempt.then(
      () => {
        if (cleanupInFlight === attempt) cleanupInFlight = null
      },
      () => {
        if (cleanupInFlight === attempt) cleanupInFlight = null
      },
    )
    return attempt
  }

  try {
    await runner('/usr/bin/openssl', [
      'req',
      '-x509',
      '-newkey',
      'rsa:2048',
      '-nodes',
      '-sha256',
      '-days',
      '1',
      '-subj',
      '/CN=synthetic-loopback.invalid',
      '-keyout',
      keyPath,
      '-out',
      certPath,
    ], {
      cwd: directory,
      encoding: 'utf8',
      maxBuffer: 16_384,
      timeout: 5_000,
      killSignal: 'SIGKILL',
    })

    const [key, cert] = await Promise.all([
      readFile(keyPath, 'utf8'),
      readFile(certPath, 'utf8'),
    ])

    return Object.freeze({
      key,
      cert,
      cleanup,
    })
  } catch (error) {
    await cleanup()
    throw error
  }
}
