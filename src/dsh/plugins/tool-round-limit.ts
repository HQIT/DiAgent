/** 在 DSH 派发工具前执行一次性任务的工具轮次上限。 */
import type { Context } from '@deepseek-ai/cordis';
import type { ResolvedToolSet } from '@deepseek-ai/dsh-tools';

export const name = 'diagent-tool-round-limit';
export const inject = ['tools'];

/** 整次任务共用预算。每个包含工具调用的模型步骤最多扣一次。 */
export function apply(context: Context, config: { maxToolRounds: number }): void {
  let remainingRounds = config.maxToolRounds;
  // DSH 为每个模型步骤创建一个工具集，并把同一个实例传给该步骤的并行及嵌套调用。
  const admitted = new WeakSet<ResolvedToolSet>();
  context.on('tools/pre-execute', (execution, next) => {
    const { toolSet } = execution;
    if (!toolSet) {
      return Promise.resolve({ kind: 'deny', reason: 'Cannot apply max_tool_rounds without a model step' });
    }
    if (!admitted.has(toolSet)) {
      if (remainingRounds === 0) {
        return Promise.resolve({ kind: 'deny', reason: 'Task exceeded its configured max_tool_rounds' });
      }
      remainingRounds -= 1;
      admitted.add(toolSet);
    }
    return next();
  }, { prepend: true });
}
