import { realpathSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const capabilities = Object.freeze({
  sourceAccountIdentity: false,
  conversationAndParticipantIdentity: false,
  stableMessageIdentity: false,
  finalMessageText: false,
  authoritativeDirectionOrSender: false,
  timestampOrOrdering: false,
  incrementalChangeDetection: false,
})

const fieldMappings = Object.freeze({
  sourceAccountIdentity: null,
  conversationIdentity: null,
  participantIdentity: null,
  stableMessageIdentity: null,
  finalMessageText: null,
  authoritativeDirectionOrSender: null,
  timestampOrOrdering: null,
  incrementalChangeDetection: null,
})

function failureReport(code: 'KIM_REDACTION_REQUIRED' | 'KIM_ATOMIC_OPEN_UNAVAILABLE') {
  return Object.freeze({
    adapterVersion: 'kim-macos-structured-v1',
    capabilities,
    fieldMappings,
    failureCodes: Object.freeze([code]),
  })
}

export async function runKimProbeCli({
  argv = process.argv.slice(2),
  env: _env = process.env,
  homeDirectory: _homeDirectory,
  write = (text: string) => process.stdout.write(text),
}: {
  argv?: readonly string[]
  env?: NodeJS.ProcessEnv
  homeDirectory?: string
  write?: (text: string) => unknown
} = {}): Promise<number> {
  const normalized = argv[0] === '--' ? argv.slice(1) : argv
  const report = failureReport(
    normalized.length === 1 && normalized[0] === '--redact'
      ? 'KIM_ATOMIC_OPEN_UNAVAILABLE'
      : 'KIM_REDACTION_REQUIRED',
  )
  write(`${JSON.stringify(report)}\n`)
  return 2
}

const invoked = process.argv[1] === undefined ? null : realpathSync(resolve(process.argv[1]))
if (invoked === realpathSync(fileURLToPath(import.meta.url))) {
  process.exitCode = await runKimProbeCli()
}
