/** 通过真实 DSH 工具调用验证事件插件，本机服务模拟模型响应和 DiOS API。 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtempDisposable, readFile, readdir, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const project = fileURLToPath(new URL('../', import.meta.url));
const event = {
  event_type: 'git.issue.opened',
  source: 'github/team/repo',
  subject: 'issue/42',
  data: { issue: 42 },
};
const publishedEvent = {
  event_id: 'event-42', status: 'dispatched', matched_agents: ['agent-42'],
  type: event.event_type, source: event.source,
};

function sendModelChunk(response, delta, finish) {
  response.writeHead(200, { 'Content-Type': 'text/event-stream' });
  const payload = { id: 'chatcmpl-event', object: 'chat.completion.chunk', created: 1, model: 'test-model',
    choices: [{ index: 0, delta: { role: 'assistant', ...delta }, finish_reason: finish }] };
  response.end('data: ' + JSON.stringify(payload) + '\n\ndata: [DONE]\n\n');
}

async function runEventTask({
  input = event, sourcePattern = 'github/*', sourceEventTypes = [event.event_type], manualStatus = 200, manualBody,
  accessToken = 'fake-dios-token', backendToken, workspaceEnv, diosEvents, expectedExitCode = 0,
} = {}) {
  const cache = join(project, '.cache');
  await mkdir(cache, { recursive: true });
  await using scratch = await mkdtempDisposable(join(cache, 'publish-event-'));
  const workspace = scratch.path;
  if (workspaceEnv) await writeFile(join(workspace, '.env'), workspaceEnv);
  const submissions = [];
  const apiHeaders = [];
  const server = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const raw = Buffer.concat(chunks).toString();
    const payload = raw ? JSON.parse(raw) : undefined;

    if (request.url === '/v1/chat/completions') {
      const toolResult = payload.messages.find(message => message.role === 'tool');
      if (toolResult) {
        sendModelChunk(response, { content: toolResult.content }, 'stop');
        return;
      }
      if (!payload.tools?.some(tool => tool.function.name === 'publish_event')) {
        sendModelChunk(response, { content: 'publish_event is unavailable' }, 'stop');
        return;
      }
      sendModelChunk(response, { tool_calls: [{
        index: 0, id: 'call-event', type: 'function',
        function: { name: 'publish_event', arguments: JSON.stringify(input) },
      }] }, 'tool_calls');
      return;
    }

    apiHeaders.push(request.headers.authorization);
    response.setHeader('Content-Type', 'application/json');
    if (request.url === '/api/os/events/catalog' && request.method === 'GET') {
      response.end(JSON.stringify({ event_types: [{ type: event.event_type }] }));
    } else if (request.url === '/api/os/connectors/source-patterns' && request.method === 'GET') {
      response.end(JSON.stringify([{ source_pattern: sourcePattern, event_types: sourceEventTypes }]));
    } else if (request.url === '/api/os/events/manual' && request.method === 'POST') {
      submissions.push(payload);
      const body = manualBody ?? (manualStatus === 200 ? publishedEvent : { detail: 'Mock gateway refused the event' });
      response.writeHead(manualStatus).end(typeof body === 'string' ? body : JSON.stringify(body));
    } else {
      response.writeHead(404).end('{}');
    }
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  try {
    const baseURL = 'http://127.0.0.1:' + server.address().port;
    const configPath = join(workspace, 'task.json');
    const output = join(workspace, 'output');
    await writeFile(configPath, JSON.stringify({
      models: { default_model: 'test', models: { test: {
        provider: 'openai', model: 'test-model', base_url: baseURL + '/v1', api_key: 'fake-model-token',
      } } },
      task: { task: 'Publish one test event.', workspace, mcp_config_path: '', output_dir: output },
    }));
    const child = spawn(process.execPath, ['dist/task/main.js'], {
      cwd: project,
      env: { ...process.env, TASK_CONFIG: configPath, OUTPUT_DIR: output, TRIGGER_MODE: 'once',
        DIAGENT_ENABLE_DIOS_EVENTS: diosEvents,
        DIOS_API: baseURL, DIAGENT_EVENT_ACCESS_TOKEN: accessToken ?? undefined, DIOS_ACCESS_TOKEN: backendToken,
        DIAGENT_TASK_TIMEOUT_MS: '35000',
        NO_PROXY: '127.0.0.1', no_proxy: '127.0.0.1', TMPDIR: workspace, TMP: workspace, TEMP: workspace },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let diagnostics = '';
    child.stdout.on('data', chunk => { diagnostics += chunk; });
    child.stderr.on('data', chunk => { diagnostics += chunk; });
    const code = await new Promise((resolve, reject) => {
      child.once('error', reject);
      child.once('close', resolve);
    });
    assert.equal(code, expectedExitCode, diagnostics);
    if (code !== 0) return { diagnostics, apiHeaders };
    const [runDirectory] = await readdir(output);
    return { result: await readFile(join(output, runDirectory, 'task_result.txt'), 'utf8'),
      submissions, apiHeaders };
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
}

test('publish_event submits a cataloged event exactly once and returns the DiOS result', { timeout: 45_000 }, async () => {
  const { result, submissions, apiHeaders } = await runEventTask();

  assert.deepEqual(submissions, [event], 'The DSH tool must POST the original event once. Result: ' + result);
  assert.deepEqual(JSON.parse(result), { ok: true, ...publishedEvent });
  assert.deepEqual(apiHeaders, ['Bearer fake-dios-token', 'Bearer fake-dios-token', 'Bearer fake-dios-token']);
});

test('a deployment can disable publish_event for standalone tasks', { timeout: 45_000 }, async () => {
  const { result, apiHeaders } = await runEventTask({
    diosEvents: 'false', workspaceEnv: 'DIAGENT_ENABLE_DIOS_EVENTS=true\n',
  });

  assert.equal(result, 'publish_event is unavailable');
  assert.deepEqual(apiHeaders, [], 'Standalone task must not contact DiOS');
});

test('an invalid publish_event setting fails before publishing an event', { timeout: 45_000 }, async () => {
  const { diagnostics, apiHeaders } = await runEventTask({ diosEvents: 'flase', expectedExitCode: 2 });

  assert.match(diagnostics, /DIAGENT_ENABLE_DIOS_EVENTS must be true or false/);
  assert.deepEqual(apiHeaders, []);
});

test('publish_event rejects sources outside the DiOS rules without submitting', { timeout: 45_000 }, async () => {
  const { result, submissions } = await runEventTask({ input: { ...event, source: 'gitlab/team/repo' } });

  assert.deepEqual(submissions, []);
  assert.match(result, /^\[publish_event rejected\].*gitlab\/team\/repo/);
});

test('publish_event rejects unknown event types without submitting', { timeout: 45_000 }, async () => {
  const { result, submissions } = await runEventTask({ input: { ...event, event_type: 'unregistered' } });

  assert.deepEqual(submissions, []);
  assert.match(result, /^\[publish_event rejected\].*unregistered/);
});

test('publish_event rejects a cataloged event type that the matching source does not allow', { timeout: 45_000 }, async () => {
  const { result, submissions } = await runEventTask({ sourceEventTypes: ['git.issue.closed'] });

  assert.deepEqual(submissions, []);
  assert.match(result, /^\[publish_event rejected\].*not allowed for source/);
});

test('publish_event accepts a literal bracket in a DiOS fnmatch source rule', { timeout: 45_000 }, async () => {
  const input = { ...event, source: 'custom/[repo]' };
  const { result, submissions } = await runEventTask({ input, sourcePattern: 'custom/[[]repo[]]' });

  assert.deepEqual(submissions, [input], result);
});

test('publish_event reports a non-JSON DiOS HTTP failure without retrying', { timeout: 45_000 }, async () => {
  const { result, submissions } = await runEventTask({ manualStatus: 502, manualBody: '<html>Bad Gateway</html>' });

  assert.deepEqual(submissions, [event]);
  assert.match(result, /^\[publish_event failed\] HTTP 502\b/);
});

test('publish_event exposes a DiOS policy denial to the Agent', { timeout: 45_000 }, async () => {
  const { result, submissions } = await runEventTask({
    manualBody: { ...publishedEvent, status: 'denied', error: 'Denied by policy' },
  });

  assert.deepEqual(submissions, [event]);
  assert.deepEqual(JSON.parse(result), { ok: false, ...publishedEvent, status: 'denied', error: 'Denied by policy' });
});

test('publish_event uses a dedicated credential from deployment, ignoring the backend token and workspace .env', { timeout: 45_000 }, async () => {
  const { submissions, apiHeaders } = await runEventTask({
    accessToken: null, backendToken: 'fake-backend-token',
    workspaceEnv: 'DIAGENT_EVENT_ACCESS_TOKEN=stale-workspace-token\n',
  });

  assert.deepEqual(submissions, [event]);
  assert.deepEqual(apiHeaders, [undefined, undefined, undefined]);
});
