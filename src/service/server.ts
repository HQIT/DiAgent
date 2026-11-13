/** 常驻 DiAgent 的 HTTP 入口，保留 DiOS 的健康检查契约。 */
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { ChatRequestError, completeChat } from './chat.js';

function sendJson(response: ServerResponse, status: number, value: object): void {
  response.writeHead(status, { 'Content-Type': 'application/json' });
  response.end(JSON.stringify(value));
}

/** 读入有大小限制的 JSON。执行期间断开连接或超时会取消 DSH。 */
async function handleChat(request: IncomingMessage, response: ServerResponse, env: NodeJS.ProcessEnv): Promise<void> {
  const disconnected = new AbortController();
  response.once('close', () => disconnected.abort());
  let signal = disconnected.signal;
  try {
    let size = 0;
    const chunks: Buffer[] = [];
    for await (const chunk of request.iterator({ destroyOnReturn: false })) {
      size += chunk.length;
      if (size > 1_048_576) {
        request.resume();
        response.setHeader('Connection', 'close');
        sendJson(response, 413, { detail: 'Chat request is too large' });
        return;
      }
      chunks.push(chunk);
    }
    let input: unknown;
    try {
      input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch {
      sendJson(response, 400, { detail: 'Invalid JSON' });
      return;
    }
    signal = AbortSignal.any([disconnected.signal, AbortSignal.timeout(290_000)]);
    const result = await completeChat(input, env, signal);
    if (!response.destroyed) sendJson(response, 200, result);
  } catch (error) {
    if (response.destroyed) return;
    if (error instanceof ChatRequestError) {
      sendJson(response, 400, { detail: error.message });
    } else if (signal.aborted) {
      sendJson(response, 504, { detail: 'Chat execution timed out' });
    } else {
      sendJson(response, 502, { detail: 'DSH chat execution failed' });
    }
  }
}

/** 创建尚未监听的 HTTP 服务，部署入口负责选择绑定地址。 */
export function createServiceServer(env: NodeJS.ProcessEnv = process.env): Server {
  return createServer((request, response) => {
    if (request.method === 'GET' && request.url === '/health') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end('{"status":"healthy"}');
      return;
    }
    if (request.method === 'POST' && request.url === '/v1/chat/completions') {
      void handleChat(request, response, env);
      return;
    }

    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end('{"detail":"Not Found"}');
  });
}

if (import.meta.main) {
  createServiceServer().listen(8000, '0.0.0.0');
}
