/** 保留旧版 shell 工具契约，将执行交给 DSH 的 Bash 工具。 */
import type { Context } from '@deepseek-ai/cordis';
import { ToolCallId } from '@deepseek-ai/dsh-llm';
import { defineTool, type ToolExecutionResult } from '@deepseek-ai/dsh-tools';
import { ToolExecutionPipeline } from '@deepseek-ai/dsh-tools/pipeline';

export const name = 'diagent-legacy-shell';
export const inject = ['tools'];

function formatShellResult(exitCode: number, stdout: string, stderr: string): string {
  return `exit_code: ${exitCode}\nstdout:\n${stdout.slice(0, 32_000)}\nstderr:\n${stderr.slice(0, 8_000)}`;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

function outputText(value: unknown): string {
  const text = record(value)?.text;
  return typeof text === 'string' ? text : '';
}

/** 将 DSH 的有界输出和执行状态映射为旧版文本格式。 */
function legacyResult(result: ToolExecutionResult): string {
  if (result.isError) return formatShellResult(-1, '', result.error.message);
  const value = record(result.value);
  if (value?.kind !== 'foreground') {
    return formatShellResult(-1, '', 'DSH Bash did not return a foreground result');
  }
  if (value.timedOut === true && typeof value.timeoutMs === 'number') {
    return formatShellResult(-1, '', `command timed out after ${value.timeoutMs / 1000}s`);
  }
  const diagnostic = result.content.flatMap(block => block.type === 'text' ? [block.text] : []).join('\n');
  const sandbox = record(value.sandbox);
  if (sandbox?.denied === true || sandbox?.runnerFailed === true) {
    return formatShellResult(-1, '', diagnostic);
  }
  const stderr = outputText(value.stderr);
  return formatShellResult(
    typeof value.exitCode === 'number' ? value.exitCode : -1,
    outputText(value.stdout),
    stderr || (value.exitCode === null ? diagnostic : ''),
  );
}

/** 通过 DSH 工具管道委派 Bash，沿用工作区策略、取消和当前工具轮次。 */
export function apply(ctx: Context): void {
  const pipeline = new ToolExecutionPipeline(ctx);
  ctx.tools.register(defineTool({
    name: 'shell',
    description: 'Execute a Bash command in the current workspace and return exit_code, stdout and stderr.',
    parameters: {
      command: { type: 'string', required: true, description: 'Bash command to execute.' },
      cwd: { oneOf: [{ type: 'string' }, { type: 'null' }], description: 'Working directory. Defaults to the task workspace.' },
      timeout: { type: 'integer', description: 'Timeout in seconds. Defaults to 300 and is capped at 1800.' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    async execute(args, execution) {
      const timeout = Math.min(Math.max(args.timeout ?? 300, 1), 1800);
      const prepared = await pipeline.prepare({
        name: 'bash',
        callId: ToolCallId(execution.callId + '-bash'),
        rootCallId: execution.rootCallId,
        parent: execution.token,
        agent: execution.agent,
        toolSet: execution.toolSet,
        signal: execution.signal,
        arguments: {
          command: args.command,
          description: 'Run the requested shell command',
          ...(args.cwd ? { workdir: args.cwd } : {}),
          timeoutMs: timeout * 1000,
        },
      });
      const outcome = prepared.kind === 'dispatch' ? await pipeline.dispatch(prepared.exec) : prepared;
      const result = await pipeline.complete(prepared.exec, outcome);
      execution.signal.throwIfAborted();
      result.additionalContexts?.forEach(context => execution.deferContext(context));
      return legacyResult(result);
    },
  }));
}
