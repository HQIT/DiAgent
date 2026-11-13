/** 验证 DiOS 用来探测常驻 DiAgent 的 HTTP 契约。 */
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { test } from 'node:test';
import { createServiceServer } from '../dist/service/server.js';

test('GET /health reports the service is alive', async () => {
  const server = createServiceServer();
  server.listen(0, '127.0.0.1');
  try {
    await once(server, 'listening');
    const response = await fetch('http://127.0.0.1:' + server.address().port + '/health');
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { status: 'healthy' });
  } finally {
    await new Promise(resolve => server.close(resolve));
  }
});
