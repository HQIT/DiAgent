/** 将模型的事件工具调用接到 DiOS。DiOS 负责审批、订阅匹配和派发。 */
import { defineTool, type ToolsService } from '@deepseek-ai/dsh-tools';

interface EventInput {
  event_type: string;
  source: string;
  subject?: string;
  data?: Record<string, unknown> | null;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : undefined;
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** 按 DiOS 来源规则匹配整个字符串。Python fnmatch 的通配符可跨越斜杠。 */
function sourceMatches(source: string, pattern: string): boolean {
  let expression = '';
  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index];
    if (character === '*') {
      if (pattern[index - 1] !== '*') expression += '.*';
    } else if (character === '?') {
      expression += '.';
    } else if (character === '[') {
      const negated = pattern[index + 1] === '!';
      const start = index + (negated ? 2 : 1);
      // 字符类开头的 ] 是字面量，后一个 ] 才关闭字符类。
      const end = pattern.indexOf(']', pattern[start] === ']' ? start + 1 : start);
      if (end === -1) {
        expression += '\\[';
        continue;
      }
      const characterClass = pattern.slice(start, end).replace(/[\\[\]^]/g, '\\$&');
      expression += '[' + (negated ? '^' : '') + characterClass + ']';
      index = end;
    } else {
      expression += escapeRegExp(character);
    }
  }
  try {
    // JavaScript 的 $ 可匹配末尾换行之前的位置，再检查后面没有字符。
    return new RegExp('^(?:' + expression + ')$(?!.)', 'su').test(source);
  } catch {
    // 反向字符范围等非法模式无法授权任何来源。
    return false;
  }
}

class DiosRequestError extends Error {}

function redactDetail(detail: string, accessToken: string): string {
  return (accessToken ? detail.replaceAll(accessToken, '[redacted]') : detail).slice(0, 500);
}

/** 事件请求允许沿用基础地址的路径前缀。禁止重定向，避免凭据被转发到其他地址。 */
async function requestJson(
  baseURL: URL, path: string, accessToken: string, signal: AbortSignal, body?: EventInput,
): Promise<unknown> {
  const url = new URL(baseURL.href.replace(/\/+$/, '') + path);
  const response = await fetch(url, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {
      Accept: 'application/json',
      ...(accessToken ? { Authorization: 'Bearer ' + accessToken } : {}),
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    redirect: 'error',
    // 沿用原事件工具的预算，目录查询 20 秒，可能触发派发的发布请求 30 秒。
    signal: AbortSignal.any([signal, AbortSignal.timeout(body === undefined ? 20_000 : 30_000)]),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch (cause) {
    if (!response.ok) throw new DiosRequestError('HTTP ' + response.status, { cause });
    throw new DiosRequestError('Invalid JSON from DiOS at ' + path, { cause });
  }
  if (!response.ok) {
    const detail = record(payload)?.detail;
    throw new DiosRequestError('HTTP ' + response.status + (typeof detail === 'string' ? ': ' + detail : ''));
  }
  return payload;
}

/** 验证事件类型和来源后最多提交一次。发布结果返回给模型，取消由 DSH 处理。 */
async function publishEvent(input: EventInput, signal: AbortSignal): Promise<string> {
  const accessToken = process.env.DIAGENT_EVENT_ACCESS_TOKEN?.trim() ?? '';
  try {
    const baseURL = new URL(process.env.DIOS_API ?? '');
    if (!['http:', 'https:'].includes(baseURL.protocol) || baseURL.username || baseURL.password
      || baseURL.search || baseURL.hash) {
      return '[publish_event failed] DIOS_API must be an HTTP(S) base URL';
    }
    const catalog = record(await requestJson(baseURL, '/api/os/events/catalog', accessToken, signal));
    if (!Array.isArray(catalog?.event_types)) throw new DiosRequestError('Invalid DiOS event catalog');
    if (!catalog.event_types.some(entry => record(entry)?.type === input.event_type)) {
      return "[publish_event rejected] event_type '" + input.event_type + "' is not in /events/catalog";
    }

    const patterns = await requestJson(baseURL, '/api/os/connectors/source-patterns', accessToken, signal);
    if (!Array.isArray(patterns)) throw new DiosRequestError('Invalid DiOS source patterns');
    const matching = patterns.map(record).filter(entry =>
      typeof entry?.source_pattern === 'string' && sourceMatches(input.source, entry.source_pattern));
    if (matching.length === 0) {
      return "[publish_event rejected] source '" + input.source + "' not allowed by /connectors/source-patterns";
    }
    if (!matching.some(entry => Array.isArray(entry?.event_types) && entry.event_types.includes(input.event_type))) {
      return "[publish_event rejected] event_type '" + input.event_type + "' not allowed for source '" + input.source + "'";
    }

    const result = record(await requestJson(baseURL, '/api/os/events/manual', accessToken, signal, {
      event_type: input.event_type,
      source: input.source,
      subject: input.subject ?? '',
      data: input.data ?? {},
    }));
    if (typeof result?.status !== 'string') throw new DiosRequestError('Invalid DiOS publish response');
    const ok = result.status !== 'denied' && result.status !== 'failed';
    return JSON.stringify({
      ok,
      event_id: result.event_id ?? null,
      status: result.status,
      matched_agents: result.matched_agents ?? null,
      type: result.type ?? null,
      source: result.source ?? null,
      error: !ok && typeof result.error === 'string' ? redactDetail(result.error, accessToken) : undefined,
    });
  } catch (error) {
    if (signal.aborted) throw signal.reason;
    const detail = error instanceof Error ? error.message : String(error);
    return '[publish_event failed] ' + redactDetail(detail, accessToken);
  }
}

export const name = 'diagent-publish-event';
export const inject = ['tools'];

/** Cordis 加载此插件时，将事件工具注册到当前 DSH 进程的工具列表。 */
export function apply(context: { tools: ToolsService }): void {
  context.tools.register(defineTool({
    name: 'publish_event',
    description: 'Publish an event through DiOS after checking the event catalog and allowed sources.',
    parameters: {
      event_type: { type: 'string', required: true, description: 'DiOS event type.' },
      source: { type: 'string', required: true, description: 'Source matching an enabled DiOS namespace.' },
      subject: { type: 'string', description: 'Optional event subject.' },
      data: { oneOf: [{ type: 'object', additionalProperties: true }, { type: 'null' }],
        description: 'Optional event payload.' },
    },
    output: {
      schema: { type: 'string' },
      render: (_args, value) => [{ type: 'text', text: value }],
    },
    execute: (args, execution) => publishEvent(args, execution.signal),
  }));
}
