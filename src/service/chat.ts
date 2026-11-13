/** 将 DiOS 的无工具单轮 Chat 请求映射到独立 DSH 会话。 */
import { randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'yaml';
import { modelProfileRow } from '../dsh/profile.js';
import { runDshTurn } from '../dsh/task-runtime.js';
import { parseModelConfig, TaskConfigError } from '../task/config.js';

/** 表示调用方输入不符合当前在线接口契约。 */
export class ChatRequestError extends Error {}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

/** 使用部署提供的模型配置执行一轮问答，并返回 DiOS 可读取的 completion。 */
export async function completeChat(input: unknown, env: NodeJS.ProcessEnv, signal: AbortSignal): Promise<object> {
  const request = record(input);
  const messages = Array.isArray(request.messages) ? request.messages.map(record) : [];
  const prompt = messages.at(-1)?.content;
  const system = messages.slice(0, -1);
  if (request.stream !== undefined && request.stream !== false) {
    throw new ChatRequestError('Only non-streaming Chat is supported');
  }
  if (typeof prompt !== 'string' || !prompt.trim() || messages.at(-1)?.role !== 'user'
    || system.some(message => message.role !== 'system' || typeof message.content !== 'string')) {
    throw new ChatRequestError('Expected optional system messages followed by one user text message');
  }
  for (const field of ['session_id', 'tools', 'tool_selection', 'custom_fields', 'max_tokens', 'top_p', 'stop']) {
    if (request[field] != null) throw new ChatRequestError(field + ' is not supported by this Chat entry yet');
  }
  if (request.model != null && typeof request.model !== 'string') {
    throw new ChatRequestError('model must be a string');
  }
  const temperature = request.temperature ?? 0.7;
  if (typeof temperature !== 'number' || !Number.isFinite(temperature) || temperature < 0 || temperature > 2) {
    throw new ChatRequestError('temperature must be a number between 0 and 2');
  }
  const workspace = resolve(env.AGENT_WORKSPACE || 'workspace');
  const source = await readFile(env.LLM_MODELS_CONFIG_PATH || join(workspace, 'models.yaml'), 'utf8');
  const catalog = record(parse(source));
  const models = record(catalog.models);
  const keys = Object.keys(models);
  const defaultModel = typeof catalog.default_model === 'string' ? catalog.default_model : undefined;
  const modelKey = request.model || env.LLM_DEFAULT_MODEL || defaultModel || (keys.length === 1 ? keys[0] : '');
  if (!modelKey || !Object.hasOwn(models, modelKey)) {
    throw new ChatRequestError('Select a model from the configured model catalog');
  }
  let model;
  try {
    model = parseModelConfig(models, modelKey, env.LLM_OPENAI_API_KEY || env.OPENAI_API_KEY);
  } catch (error) {
    if (error instanceof TaskConfigError) throw new Error('Invalid configured model', { cause: error });
    throw error;
  }

  const content = await runDshTurn({ workspace, prompt, model, stepLimit: 100 }, async home => {
    const profile = join(home, 'chat.cordis.yml');
    const personaPrefix = system.length > 0 ? system.map(message => message.content).join('\n')
      : env.AGENT_SYSTEM_PROMPT || '你是用户的助理。';
    await writeFile(profile, JSON.stringify([
      modelProfileRow(model),
      { id: 'system-prompt', config: { personaPrefix } },
      { id: 'skill-filesystem', config: { includeDefaultRoots: false, customSkillDirs: [], watch: false } },
      ...['session-log-deepseek', 'session-telemetry-otel', 'plugin-package-inventory-deepseek']
        .map(id => ({ id, disabled: true })),
      { insert: [
        { id: 'diagent-chat-no-tools', name: fileURLToPath(new URL('../dsh/plugins/chat-no-tools.js', import.meta.url)) },
        { id: 'diagent-task-temperature', name: fileURLToPath(new URL('../dsh/plugins/task-temperature.js', import.meta.url)),
          config: { temperature } },
      ] },
    ]), { mode: 0o600 });
    return profile;
  }, signal, () => {});
  return {
    id: 'chatcmpl-' + randomUUID(), object: 'chat.completion',
    created: Math.floor(Date.now() / 1000), model: model.name,
    choices: [{ index: 0, message: { role: 'assistant', content }, finish_reason: 'stop' }],
  };
}
