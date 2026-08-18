import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const repositoryRoot = resolve(import.meta.dirname, '../..')

function read(relativePath: string): string {
  return readFileSync(resolve(repositoryRoot, relativePath), 'utf8')
}

describe('Kim user-authorized local adapter gate', () => {
  it('records the approved Kim-only evidence path without passing overall G2', () => {
    const designPath = 'docs/plans/2026-08-18-kim-chat-skill-design.md'
    expect(existsSync(resolve(repositoryRoot, designPath))).toBe(true)

    const design = read(designPath)
    expect(design).toContain('user authorizes an audited local-database adapter for Kim')
    expect(design).toContain('does not itself pass G2')

    const gate = read('docs/verification/chat-source-gate.md')
    expect(gate).toContain('User-authorized Kim local adapter evidence path')
    expect(gate).toContain('On-demand Kim Skill: `NOT YET PROVEN`')
    expect(gate).toContain('Kim production connector: `DISABLED`')
    expect(gate).toContain('G2 is **BLOCKED** overall')

    const dossier = read('docs/dossiers/2026-08-17-dsh-personal-context.md')
    expect(dossier).toContain('[Kim Chat Skill design](../plans/2026-08-18-kim-chat-skill-design.md)')
    expect(dossier).toContain('user-authorized local-database adapter')
    expect(dossier).toContain('still BLOCKED at G2')
  })
})
