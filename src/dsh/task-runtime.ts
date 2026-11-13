/** 封装一次性任务的 DSH 会话和子进程生命周期，将运行终态交回任务入口。 */
import { DeepSeekHarness, validatedSessionEvent } from '@deepseek-ai/dsh-sdk-client';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { TaskConfig } from '../task/config.js';
import { writeTaskProfile } from './profile.js';

/**
 * 在配置的工作区启动独立 DSH 子进程，完成或取消后清理临时配置。
 * @param runDirectory - 本轮文件产物目录，由调用方创建。
 * @returns 根会话成功结束时的最后一条助手文本。
 * @throws 任务取消、超出步数、启动失败或根会话没有成功结束。
 */
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
        // 空值也显式传递，避免任务工作区的 .env 成为 Git 凭据来源。
        GIT_PLATFORM_TOKEN: process.env.GIT_PLATFORM_TOKEN ?? '',
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
        // 用协议层 prompt 保留原始任务文本，避免 SDK 把开头的 / 当成命令。
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
