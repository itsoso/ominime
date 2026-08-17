import { realpathSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const cliCapabilities = Object.freeze({
  sourceAccountIdentity: false,
  conversationAndParticipantIdentity: false,
  stableMessageIdentity: false,
  finalMessageText: false,
  authoritativeDirectionOrSender: false,
  timestampOrOrdering: false,
  incrementalChangeDetection: false,
})

const cliFieldMappings = Object.freeze({
  sourceAccountIdentity: null,
  conversationIdentity: null,
  participantIdentity: null,
  stableMessageIdentity: null,
  finalMessageText: null,
  authoritativeDirectionOrSender: null,
  timestampOrOrdering: null,
  incrementalChangeDetection: null,
})

function createCliFailureReport(
  failureCode: 'WECHAT_REDACTION_REQUIRED' | 'WECHAT_ATOMIC_OPEN_UNAVAILABLE',
) {
  return Object.freeze({
    adapterVersion: 'wechat-macos-xwechat-v4-v1',
    capabilities: cliCapabilities,
    fieldMappings: cliFieldMappings,
    failureCodes: Object.freeze([failureCode]),
  })
}

export async function runWechatProbeCli({
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
  const normalizedArguments = argv[0] === '--' ? argv.slice(1) : argv
  const report = createCliFailureReport(
    normalizedArguments.length === 1 && normalizedArguments[0] === '--redact'
      ? 'WECHAT_ATOMIC_OPEN_UNAVAILABLE'
      : 'WECHAT_REDACTION_REQUIRED',
  )
  write(`${JSON.stringify(report)}\n`)
  return report.failureCodes.length === 0 ? 0 : 2
}

const invoked = process.argv[1] === undefined ? null : realpathSync(resolve(process.argv[1]))
if (invoked === realpathSync(fileURLToPath(import.meta.url))) {
  process.exitCode = await runWechatProbeCli()
}
