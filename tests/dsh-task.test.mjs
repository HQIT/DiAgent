/** 通过真实 DSH 子进程验证一次性任务，模型和 MCP 服务使用本机模拟端点。 */
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdir, mkdtempDisposable, readFile, readdir, writeFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const project = fileURLToPath(new URL('../', import.meta.url));

test('DSH task preserves the input, MCP and result contract with DiOS events disabled', { timeout: 90_000 }, async () => {
  const cacheDir = join(project, '.cache');
  await mkdir(cacheDir, { recursive: true });
  await using scratch = await mkdtempDisposable(join(cacheDir, 'diagent-smoke-'));
  const workspace = scratch.path;
  const skillDirectory = join(workspace, 'skills', 'smoke-skill');
  await mkdir(skillDirectory, { recursive: true });
  await writeFile(join(skillDirectory, 'SKILL.md'),
    '---\nname: smoke-skill\ndescription: DiAgent smoke skill marker\n---\nTest instructions.\n');

  const modelRequests = [];
  const mcpRequests = [];
  const server = createServer(async (request, response) => {
    if (request.method !== 'POST') {
      response.writeHead(405).end();
      return;
    }
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const body = JSON.parse(Buffer.concat(chunks).toString());

    if (request.url === '/mcp') {
      mcpRequests.push({ method: body.method, authorization: request.headers.authorization });
      // 模拟工具发现晚于连接建立。测试直接检查模型首轮请求里的工具声明。
      if (body.method === 'tools/list') await delay(1500);
      const results = {
        initialize: { protocolVersion: body.params?.protocolVersion, capabilities: { tools: {} },
          serverInfo: { name: 'smoke', version: '1' } },
        'tools/list': { tools: [{ name: 'lookup', description: 'Look up a test value',
          inputSchema: { type: 'object', properties: {} } }] },
        'tools/call': { content: [{ type: 'text', text: 'mcp-ok' }] },
      };
      if (body.id === undefined) {
        response.writeHead(202).end();
      } else if (Object.hasOwn(results, body.method)) {
        response.writeHead(200, { 'Content-Type': 'application/json' })
          .end(JSON.stringify({ jsonrpc: '2.0', id: body.id, result: results[body.method] }));
      } else {
        response.writeHead(200, { 'Content-Type': 'application/json' })
          .end(JSON.stringify({ jsonrpc: '2.0', id: body.id, error: { code: -32601, message: 'Method not found' } }));
      }
      return;
    }

    if (request.url !== '/v1/chat/completions') {
      response.writeHead(404).end();
      return;
    }
    modelRequests.push(body);
    if (body.messages.some(message => message.role === 'user' && message.content === 'fail-smoke')) {
      response.writeHead(400, { 'Content-Type': 'application/json' })
        .end(JSON.stringify({ error: { message: 'intentional provider failure' } }));
      return;
    }

    const toolResults = body.messages.filter(message => message.role === 'tool');
    const isBudgetTask = body.messages.some(message => message.role === 'user' && message.content === 'tool-budget');
    const hasToolResult = toolResults.length > 0;
    const toolCall = { index: 0, id: 'call-smoke', type: 'function',
      function: { name: 'mcp__smoke__lookup', arguments: '{}' } };
    const needsTool = isBudgetTask ? toolResults.length < 3 : !hasToolResult;
    const toolCalls = isBudgetTask && !hasToolResult
      ? [toolCall, { ...toolCall, index: 1, id: 'call-smoke-second' }]
      : [{ ...toolCall, id: isBudgetTask ? 'call-smoke-next-round' : toolCall.id }];
    const delta = needsTool ? { tool_calls: toolCalls } : {
      content: isBudgetTask ? toolResults.map(message => message.content).join('\n') : 'pilot-ok',
    };
    const base = { id: 'chatcmpl-smoke', object: 'chat.completion.chunk', created: 1, model: 'smoke-model' };
    response.writeHead(200, { 'Content-Type': 'text/event-stream' });
    for (const [part, finish] of [[{ role: 'assistant' }, null], [delta, null], [{}, needsTool ? 'tool_calls' : 'stop']]) {
      response.write('data: ' + JSON.stringify({
        ...base, choices: [{ index: 0, delta: part, finish_reason: finish }],
      }) + '\n\n');
    }
    response.end('data: [DONE]\n\n');
  });

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });

  const baseURL = 'http://127.0.0.1:' + server.address().port;
  await writeFile(join(workspace, 'mcp.json'), JSON.stringify({
    smoke: { transport: 'streamable_http', url: baseURL + '/mcp', headers: { Authorization: 'Bearer smoke-mcp' } },
  }));

  async function run(prompt, label, mcpPath, taskOptions = {}) {
    const taskConfig = join(workspace, label + '.json');
    const outputRoot = join(workspace, label);
    await writeFile(taskConfig, JSON.stringify({
      models: { default_model: 'alias', models: { alias: {
        provider: 'openai', model: 'smoke-model', base_url: baseURL + '/v1', api_key: 'smoke-model-key',
      } } },
      task: {
        task: prompt, workspace, system_prompt: 'Smoke system prompt.',
        skill_names: ['smoke-skill'], mcp_config_path: mcpPath, output_dir: outputRoot,
        output: { log_file: 'task.log', result_file: 'task_result.md' }, trigger: { mode: 'once' },
        ...taskOptions,
      },
    }));
    const child = spawn(process.execPath, ['dist/task/main.js'], {
      cwd: project,
      env: { ...process.env, TASK_CONFIG: taskConfig, OUTPUT_DIR: outputRoot, TRIGGER_MODE: 'once',
        DIAGENT_ENABLE_DIOS_EVENTS: 'false',
        DIAGENT_TASK_TIMEOUT_MS: '35000', NO_PROXY: '127.0.0.1', no_proxy: '127.0.0.1',
        TMPDIR: workspace, TEMP: workspace, TMP: workspace },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    child.stdout.on('data', chunk => { output += chunk; });
    child.stderr.on('data', chunk => { output += chunk; });
    const code = await new Promise((resolve, reject) => {
      child.once('error', reject);
      child.once('close', resolve);
    });
    if (code === 2) return { code, output };
    const [runDirectory] = await readdir(outputRoot);
    return {
      code, output,
      result: await readFile(join(outputRoot, runDirectory, 'task_result.md'), 'utf8'),
      log: await readFile(join(outputRoot, runDirectory, 'task.log'), 'utf8'),
    };
  }

  try {
    const success = await run('/literal-smoke', 'success', 'mcp.json');
    assert.equal(success.code, 0, success.output);
    assert.equal(success.result, 'pilot-ok');
    assert.match(success.log, /\[complete\]/);
    assert.equal(modelRequests[0].model, 'smoke-model');
    assert.ok(modelRequests[0].tools?.some(tool => tool.function.name === 'mcp__smoke__lookup'),
      'The first model request must include the MCP tool after initial discovery');
    assert.match(JSON.stringify(modelRequests[0].messages), /Smoke system prompt/);
    assert.ok(modelRequests[0].messages.some(message => message.role === 'user' && message.content === '/literal-smoke'));
    assert.match(JSON.stringify(modelRequests[0]), /DiAgent smoke skill marker/);
    assert.ok(modelRequests.some(request => request.messages.some(message =>
      message.role === 'tool' && message.content.includes('mcp-ok'))));
    assert.ok(mcpRequests.some(request => request.method === 'tools/call' && request.authorization === 'Bearer smoke-mcp'));

    const failure = await run('fail-smoke', 'failure', '');
    assert.equal(failure.code, 1, failure.output);
    assert.match(failure.result, /任务执行失败/);
    assert.match(failure.log, /\[error\]/);
    assert.doesNotMatch(success.output + failure.output + success.log + failure.log, /smoke-model-key|smoke-mcp/);

    const previousCalls = mcpRequests.filter(request => request.method === 'tools/call').length;
    const budget = await run('tool-budget', 'budget', 'mcp.json', { max_tool_rounds: 1 });
    assert.equal(budget.code, 0, budget.output);
    assert.equal(mcpRequests.filter(request => request.method === 'tools/call').length - previousCalls, 2);
    assert.match(budget.result, /max_tool_rounds/);

    const invalidBudget = await run('tool-budget', 'invalid-budget', 'mcp.json', { max_tool_rounds: 0 });
    assert.equal(invalidBudget.code, 2, invalidBudget.output);
    assert.match(invalidBudget.output, /task\.max_tool_rounds must be a positive integer/);
  } finally {
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
});
