import { readFileSync } from 'node:fs'

import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-skill'

interface KimChatSkillDefinition {
  readonly name: 'kim-chat-history'
  readonly description: string
  readonly source: 'runtime'
  readonly provider: 'personal-context'
  readonly invocation: {
    readonly modelInvocable: true
    readonly userInvocable: true
  }
  readonly content: string
}

function parseFrontmatter(source: string): { name: string, description: string, content: string } {
  const match = /^---\n([\s\S]*?)\n---\n([\s\S]+)$/.exec(source)
  if (match === null) throw new Error('Kim chat skill has invalid frontmatter')

  const metadata = new Map<string, string>()
  for (const line of match[1]!.split('\n')) {
    const field = /^([a-z_]+):\s*(\S.*)$/.exec(line)
    if (field === null || metadata.has(field[1]!)) {
      throw new Error('Kim chat skill has invalid frontmatter')
    }
    metadata.set(field[1]!, field[2]!)
  }
  if ([...metadata.keys()].join(',') !== 'name,description') {
    throw new Error('Kim chat skill has invalid frontmatter')
  }

  const name = metadata.get('name')!
  const description = metadata.get('description')!
  const content = match[2]!.trim()
  if (name !== 'kim-chat-history' || description.length === 0 || content.length === 0) {
    throw new Error('Kim chat skill has invalid frontmatter')
  }
  return { name, description, content }
}

export function loadKimChatSkill(skillUrl: URL): KimChatSkillDefinition {
  const parsed = parseFrontmatter(readFileSync(skillUrl, 'utf8'))
  return Object.freeze({
    name: 'kim-chat-history',
    description: parsed.description,
    source: 'runtime',
    provider: 'personal-context',
    invocation: Object.freeze({ modelInvocable: true, userInvocable: true }),
    content: parsed.content,
  })
}

export function registerKimChatSkill(ctx: Context, skillUrl: URL): () => void {
  return ctx.skills.register(loadKimChatSkill(skillUrl))
}
