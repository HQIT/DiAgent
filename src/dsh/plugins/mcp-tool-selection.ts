/** 将旧任务的 MCP 工具名单转换成 DSH Agent 的工具限制。 */
import type { Context } from '@deepseek-ai/cordis';
import type {} from '@deepseek-ai/dsh-agent';
import type {} from '@deepseek-ai/dsh-tools';

export const name = 'diagent-mcp-tool-selection';
export const inject = ['agents', 'tools'];

/** 保留首次发现时符合任务名单的 MCP 工具和本次任务的内置工具。 */
export function apply(ctx: Context, config: { toolNames: string[] }): void {
  const selected = new Set(config.toolNames);
  ctx.on('agent/created', ({ agent }): undefined => {
    const allow = ctx.tools.definitions()
      .map(tool => tool.name)
      .filter(tool => tool !== 'run_code' && (!tool.startsWith('mcp__') || selected.has(tool)));
    agent.ctx.tools.restrict({ allow });
  }, { global: true });
}
