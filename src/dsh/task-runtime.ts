/** 管理一次任务的 DSH 子进程，按 SDK 事件判断实际终态。 */
import { DeepSeekHarness, validatedSessionEvent } from '@deepseek-ai/dsh-sdk-client';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { TaskConfig } from '../task/config.js';
import { writeTaskProfile } from './profile.js';

/** 执行一次任务，只有收到成功终态才返回答案，并在退出前释放子进程。 */
export async function runDshTask(
  config: TaskConfig,
  runDirectory: string,
  signal: AbortSignal,
  log: (message: string) => void,
): Promise<string> {
  const home = await mkdtemp(join(tmpdir(), 'diagent-dsh-'));
  try {
    const patch = await writeTaskProfile(config, home, runDirectory);
    signal.throwIfAborted();
    await using harness = new DeepSeekHarness({
      dshHome: home,
      profile: 'sdk',
      patches: [patch],
      provider: 'diagent-model',
      model: config.model.name,
      cwd: config.workspace,
      processCwd: config.workspace,
      env: {
        ...process.env,
        // 固定 DiOS 连接配置，防止 DSH 从任务工作区的 .env 补入缺失值。
        DIOS_API: process.env.DIOS_API || 'http://backend:8000',
        DIAGENT_EVENT_ACCESS_TOKEN: process.env.DIAGENT_EVENT_ACCESS_TOKEN ?? '',
        DIAGENT_MODEL_API_KEY: config.model.apiKey,
        DSH_PERMISSION_MODE: 'workspace-write',
        DSH_TELEMETRY_MODE: 'DISABLED',
        DSH_MAX_TOKENS_AS_SUCCESS: 'false',
      },
    });
    const stop = () => {
      void harness.close().catch(() => log('[dsh] shutdown_failed'));
    };
    signal.addEventListener('abort', stop, { once: true });
    try {
      await harness.start();
      signal.throwIfAborted();
      const sessionId = randomUUID();
      const subscription = harness.client.subscribeSessionTree(sessionId);
      try {
        // 用低层 prompt 提交原始任务，避免以 / 开头的文本被路由成 SDK 命令。
        await harness.client.prompt(sessionId, [{ type: 'text', text: config.prompt }]);
        const finished = harness.client.request('session/wait', { sessionId }).then(() => null);
        let steps = 0;
        let reply = '';
        let reason: string | undefined;
        let errorCode: string | undefined;
        while (true) {
          const notification = await Promise.race([subscription.next(), finished]);
          if (notification === null) break;
          if (notification.method !== 'session.event') continue;

          const event = validatedSessionEvent(notification.params.event);
          if (event.type === 'step/start') {
            steps += 1;
            if (steps > config.stepLimit) throw new Error('Task exceeded its configured step limit');
          }
          log('[dsh] ' + event.type);
          if (notification.params.sessionId !== sessionId) continue;
          if (event.type === 'assistant/message') {
            reply = event.data.message.content.flatMap(block => block.type === 'text' ? [block.text] : []).join('');
          } else if (event.type === 'turn/end') {
            reason = event.data.reason.kind;
            if (event.data.reason.kind === 'error') errorCode = event.data.reason.error.code;
          }
        }
        signal.throwIfAborted();
        if (reason !== 'completed') {
          const detail = errorCode ? reason + ' (' + errorCode + ')' : reason ?? 'missing turn end';
          throw new Error('DSH did not complete the task: ' + detail);
        }
        return reply;
      } finally {
        subscription.close();
      }
    } finally {
      signal.removeEventListener('abort', stop);
    }
  } finally {
    await rm(home, { recursive: true, force: true });
  }
}
