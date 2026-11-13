/** 验证 DiOS 用来探测常驻 DiAgent 的 HTTP 契约。 */
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdir, mkdtempDisposable, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { join } from 'node:path';
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

test('non-streaming A2A service request returns the DSH reply', { timeout: 45_000 }, async () => {
  await mkdir('.cache', { recursive: true });
  await using workspace = await mkdtempDisposable(join(process.cwd(), '.cache', 'diagent-chat-'));
  const received = [];
  await using model = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    received.push(JSON.parse(Buffer.concat(chunks).toString()));
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    const base = { id: 'chatcmpl-test', object: 'chat.completion.chunk', created: 1, model: 'fixture-model' };
    for (const [delta, finish_reason] of [[{ role: 'assistant', content: 'A2A reply' }, null], [{}, 'stop']]) {
      response.write('data: ' + JSON.stringify({ ...base, choices: [{ index: 0, delta, finish_reason }] }) + '\n\n');
    }
    response.end('data: [DONE]\n\n');
  });
  model.listen(0, '127.0.0.1');
  await once(model, 'listening');
  const modelsPath = join(workspace.path, 'models.yaml');
  await writeFile(modelsPath, JSON.stringify({ models: { 'fixture-model': {
    provider: 'openai', model: 'fixture-model', base_url: 'http://127.0.0.1:' + model.address().port + '/v1',
  } } }));

  await using service = createServiceServer({
    AGENT_WORKSPACE: workspace.path,
    LLM_MODELS_CONFIG_PATH: modelsPath,
    AGENT_SYSTEM_PROMPT: 'Reviewer role',
  });
  service.listen(0, '127.0.0.1');
  await once(service, 'listening');
  const response = await fetch('http://127.0.0.1:' + service.address().port + '/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'fixture-model', stream: false, messages: [{ role: 'user', content: 'Review the draft' }] }),
  });
  const completion = await response.json();
  assert.equal(response.status, 200, JSON.stringify(completion));
  assert.equal(completion.choices[0].message.content, 'A2A reply');
  assert.equal(received[0].model, 'fixture-model');
  assert.ok(received[0].messages.some(message => message.role === 'user' && message.content === 'Review the draft'));
  assert.match(JSON.stringify(received[0].messages), /Reviewer role/);
  assert.equal(received[0].tools?.length ?? 0, 0);
});

test('rejects unsupported streaming requests before starting DSH', async () => {
  await using service = createServiceServer({});
  service.listen(0, '127.0.0.1');
  await once(service, 'listening');
  const response = await fetch('http://127.0.0.1:' + service.address().port + '/v1/chat/completions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ stream: true, messages: [{ role: 'user', content: 'Review the draft' }] }),
  });
  assert.equal(response.status, 400);
  assert.match((await response.json()).detail, /non-streaming/);
});
