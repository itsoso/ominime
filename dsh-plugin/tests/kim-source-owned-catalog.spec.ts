import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const repositoryRoot = resolve(import.meta.dirname, '../..')
const reportRelativePath = 'docs/verification/kim-source-owned-catalog.md'
const reportPath = resolve(repositoryRoot, reportRelativePath)
const dossierPath = resolve(
  repositoryRoot,
  'docs/dossiers/2026-08-17-dsh-personal-context.md',
)

const allowedValues = new Map<string, readonly string[]>([
  ['Status', ['PROVEN', 'NOT PROVEN', 'BLOCK']],
  [
    'Authorization class',
    [
      'enterprise_sso',
      'administrator_approval',
      'enterprise_sso+administrator_approval',
      'NOT PROVEN',
    ],
  ],
  [
    'Historical participation scope',
    ['historical_personal', 'bot_only', 'notification_only', 'post_install_only', 'NOT PROVEN'],
  ],
  ['Self identity', ['PROVEN', 'NOT PROVEN']],
  ['Conversation identity', ['PROVEN', 'NOT PROVEN']],
  ['Stable message identity', ['PROVEN', 'NOT PROVEN']],
  ['Timestamp or order', ['PROVEN', 'NOT PROVEN']],
  ['Edit and retraction events', ['PROVEN', 'NOT PROVEN']],
  ['Incremental cursor or event stream', ['PROVEN', 'NOT PROVEN']],
  [
    'Failure codes',
    [
      'NONE',
      'KIM_CATALOG_ACCESS_NOT_APPROVED',
      'KIM_CATALOG_AUTHORIZATION_NOT_PROVEN',
      'KIM_CATALOG_HISTORICAL_SCOPE_NOT_PROVEN',
      'KIM_CATALOG_BOT_ONLY',
      'KIM_CATALOG_NOTIFICATION_ONLY',
      'KIM_CATALOG_POST_INSTALL_ONLY',
      'KIM_CATALOG_REQUIRED_CAPABILITIES_NOT_PROVEN',
    ],
  ],
])

describe('Kim source-owned catalog report contract', () => {
  it('contains only generic fixed-enum evidence and updates the Dossier gate', () => {
    expect(
      existsSync(reportPath),
      `missing required catalog report: ${reportRelativePath}`,
    ).toBe(true)

    const report = readFileSync(reportPath, 'utf8')
    expect(/https?:\/\//.test(report), 'catalog report contains a URL').toBe(false)
    expect(
      /token|cookie|client_secret|organization_id/i.test(report),
      'catalog report contains credential metadata',
    ).toBe(false)
    expect(
      /account_id|user_id|endpoint|raw schemas?|message content|\bcounts?\b|\bhash(?:es)?\b|credential/i
        .test(report),
      'catalog report contains forbidden metadata',
    ).toBe(false)

    const lines = report.trim().split(/\r?\n/)
    expect(
      lines[0] === '# Kim Source-Owned Catalog Gate',
      'catalog report title is not allowlisted',
    ).toBe(true)
    expect(lines).toHaveLength(allowedValues.size + 1)

    const reportFields = new Map<string, string>()
    let linesMatchGenericShape = true
    let fieldsAreUnique = true
    let fieldsAndValuesAreAllowlisted = true
    for (const line of lines.slice(1)) {
      const match = /^- ([^:]+): `([^`]+)`$/.exec(line)
      if (match === null) {
        linesMatchGenericShape = false
        continue
      }
      const [, field, value] = match as RegExpExecArray
      if (reportFields.has(field)) fieldsAreUnique = false
      reportFields.set(field, value)
      if (allowedValues.get(field)?.includes(value) !== true) {
        fieldsAndValuesAreAllowlisted = false
      }
    }

    expect(linesMatchGenericShape, 'catalog report contains copied or free-form content').toBe(true)
    expect(fieldsAreUnique, 'catalog report contains duplicate fields').toBe(true)
    expect(fieldsAndValuesAreAllowlisted, 'catalog report contains a non-enum field or value').toBe(true)
    expect(reportFields.size).toBe(allowedValues.size)
    for (const field of allowedValues.keys()) {
      expect(reportFields.has(field), `catalog report is missing ${field}`).toBe(true)
    }

    const dossier = readFileSync(dossierPath, 'utf8')
    expect(
      /\[Kim source-owned catalog gate\]\(\.\.\/verification\/kim-source-owned-catalog\.md\)[^\r\n]*`(?:PROVEN|NOT PROVEN|BLOCK)`/
        .test(dossier),
      'Dossier is missing the Kim catalog report link and fixed-enum status',
    ).toBe(true)
  })
})
