import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-skill'
import type {} from '@deepseek-ai/dsh-tools'

import { registerKimChatSkill } from './chatkim/skill.ts'
import {
  createEnvironmentKimChatGateway,
  registerKimChatTools,
} from './chatkim/tools.ts'

export const name = 'personal-context'
export const inject = ['tools', 'skills']

/** Plugin-owned error for invalid arguments to the raw health definition. */
class InvalidHealthArgsError extends Error {
  readonly code = 'INVALID_HEALTH_ARGS'
  readonly violations: string[]

  constructor(violations: string[]) {
    super(`invalid personal_context_health arguments: ${violations.join('; ')}`)
    this.name = 'InvalidHealthArgsError'
    this.violations = violations
  }
}

function assertEmptyObject(args: unknown): asserts args is Record<string, never> {
  if (args === null || typeof args !== 'object' || Array.isArray(args)) {
    throw new InvalidHealthArgsError(['"arguments" must be an object'])
  }
  const prototype = Object.getPrototypeOf(args)
  if (prototype !== Object.prototype && prototype !== null) {
    throw new InvalidHealthArgsError(['"arguments" must be a plain JSON object'])
  }
  const keys = Reflect.ownKeys(args)
  if (keys.length > 0) {
    throw new InvalidHealthArgsError(keys.map(key => `unexpected property ${JSON.stringify(String(key))}`))
  }
}

/** Register the read-only Personal Context scaffold health tool. */
export function apply(ctx: Context): void {
  registerKimChatSkill(
    ctx,
    new URL('../skills/kim-chat-history/SKILL.md', import.meta.url),
  )

  ctx.tools.register({
    name: 'personal_context_health',
    description: 'Report the local Personal Context scaffold status.',
    parameters: {
      type: 'object',
      properties: {},
      additionalProperties: false,
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        required: ['status', 'schemaVersion', 'sources'],
        properties: {
          status: { type: 'string' },
          schemaVersion: { type: 'integer' },
          sources: {
            type: 'array',
            items: { type: 'string' },
          },
        },
      },
      render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }],
    },
    async execute(args: unknown) {
      assertEmptyObject(args)
      return { status: 'scaffold', schemaVersion: 0, sources: [] }
    },
  })

  const kimChat = createEnvironmentKimChatGateway()
  registerKimChatTools(ctx, kimChat)
  ctx.effect(
    () => async () => kimChat.dispose(),
    'personal-context: Kim chat reader',
  )
}
