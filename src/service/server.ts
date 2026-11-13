/** 常驻 DiAgent 的 HTTP 入口，保留 DiOS 的健康检查契约。 */
import { createServer, type Server } from 'node:http';

/** 创建尚未监听的 HTTP 服务，部署入口负责选择绑定地址。 */
export function createServiceServer(): Server {
  return createServer((request, response) => {
    if (request.method === 'GET' && request.url === '/health') {
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end('{"status":"healthy"}');
      return;
    }

    response.writeHead(404, { 'Content-Type': 'application/json' });
    response.end('{"detail":"Not Found"}');
  });
}

if (import.meta.main) {
  createServiceServer().listen(8000, '0.0.0.0');
}
