/** 将一次性任务解析后的温度应用到 DSH 模型请求。 */
import type { Context } from '@deepseek-ai/cordis';
import type {} from '@deepseek-ai/dsh-agent';

export const name = 'diagent-task-temperature';
export const inject = ['agents'];

/** 在 DSH 校验并冻结请求前补入温度，覆盖任务内的后续工具轮次。 */
export function apply(ctx: Context, config: { temperature: number }): void {
  // 固定版本的 DSH 已弃用此事件，但尚无替代的逐请求温度接口。
  ctx.on('agent/request', async (_request, next) => ({
    ...await next(),
    temperature: config.temperature,
  }), { global: true });
}
