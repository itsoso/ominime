import type { Context } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'

export const inject = ['slots']

function PersonalContextPlaceholder() {
  return (
    <section aria-label="个人上下文">
      <h2>个人上下文</h2>
      <p>启用本地上下文来源后，相关内容会显示在这里。</p>
    </section>
  )
}

/** Add an isolated Personal Context tab without replacing the conversation surface. */
export function apply(ctx: Context): void {
  ctx.slots.inject('conversation.view', () => ctx.slots.register({
    name: 'conversation.view',
    id: 'personal-context',
    order: 20,
    label: '个人上下文',
  }, PersonalContextPlaceholder))
}
