/** 普通问答使用空工具集，沿用 DSH 对可见和可执行工具的统一限制。 */
import type { Context } from '@deepseek-ai/cordis';
import type {} from '@deepseek-ai/dsh-agent';
import type {} from '@deepseek-ai/dsh-tools';

export const name = 'diagent-chat-no-tools';
export const inject = ['agents', 'tools'];

/** 在每个问答会话的 Agent 创建时限制继承的工具。 */
export function apply(ctx: Context): void {
  ctx.on('agent/created', ({ agent }): undefined => {
    agent.ctx.tools.restrict({ allow: [] });
  }, { global: true });
}
