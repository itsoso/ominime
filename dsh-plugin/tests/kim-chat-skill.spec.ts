import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

import { describe, expect, it, vi } from 'vitest'

import { loadKimChatSkill, registerKimChatSkill } from '../src/chatkim/skill.ts'

const root = resolve(import.meta.dirname, '..')
const skillPath = resolve(root, 'skills/kim-chat-history/SKILL.md')

describe('Kim chat history DSH skill', () => {
  it('loads a minimal packaged skill with the approved routing contract', () => {
    const skill = loadKimChatSkill(pathToFileURL(skillPath))

    expect(skill).toMatchObject({
      name: 'kim-chat-history',
      source: 'runtime',
      provider: 'personal-context',
      invocation: { modelInvocable: true, userInvocable: true },
    })
    expect(skill.description).toContain('local Kim')
    expect(skill.content).toContain('kim_chat_status')
    expect(skill.content).toContain('kim_chat_conversations')
    expect(skill.content).toContain('kim_chat_messages')
    expect(skill.content).toContain('kim_chat_context')
    expect(skill.content).not.toMatch(/\b(?:shell|sql|sqlite|exec|spawn)\b/i)
  })

  it('keeps SKILL frontmatter limited to name and description', () => {
    const source = readFileSync(skillPath, 'utf8')
    const frontmatter = source.split('---', 3)[1]!
    const keys = frontmatter
      .split('\n')
      .map(line => line.match(/^([a-z_]+):/)?.[1])
      .filter((key): key is string => key !== undefined)
    expect(keys).toEqual(['name', 'description'])
  })

  it('registers the skill with DSH and returns its exact disposer', () => {
    const dispose = vi.fn()
    const register = vi.fn(() => dispose)
    const result = registerKimChatSkill({ skills: { register } } as never, pathToFileURL(skillPath))

    expect(register).toHaveBeenCalledOnce()
    expect(register.mock.calls[0]![0]).toEqual(loadKimChatSkill(pathToFileURL(skillPath)))
    expect(result).toBe(dispose)
  })
})
