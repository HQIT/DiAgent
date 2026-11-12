/** 生成一次运行的 DSH 配置，避免任务之间共享工具注册和凭据状态。 */
import { mkdir, readFile, stat, symlink, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TaskConfigError, type TaskConfig } from '../task/config.js';

const disabledRows = [
  'session-log-deepseek', 'session-telemetry-otel', 'plugin-package-inventory-deepseek',
  'tool-web', 'tool-plugin-manager', 'tool-schedule', 'tool-ask-user', 'tool-goal',
  'tool-office', 'skill-office', 'agent-instructions',
];

async function skillRoots(config: TaskConfig, home: string): Promise<string[]> {
  if (config.skillNames.length === 0) return [config.skillsDir];

  const selectedRoot = join(home, 'selected-skills');
  await mkdir(selectedRoot);
  for (const name of config.skillNames) {
    const directory = join(config.skillsDir, name);
    try {
      if (!(await stat(join(directory, 'SKILL.md'))).isFile()) throw new Error('Not a file');
    } catch {
      throw new TaskConfigError('Selected skill has no readable SKILL.md: ' + name);
    }
    await symlink(directory, join(selectedRoot, name), process.platform === 'win32' ? 'junction' : 'dir');
  }
  return [selectedRoot];
}

async function mcpRows(path: string | undefined): Promise<object[]> {
  if (!path) return [];
  let servers: unknown;
  try {
    servers = JSON.parse((await readFile(path, 'utf8')).replace(/^\uFEFF/, ''));
  } catch {
    throw new TaskConfigError('Cannot read or parse MCP config: ' + path);
  }
  if (!servers || typeof servers !== 'object' || Array.isArray(servers)) {
    throw new TaskConfigError('MCP config must be a server map');
  }
  return Object.entries(servers).map(([name, server]) => {
    if (!/^[A-Za-z0-9_-]{1,32}$/.test(name) || !server || typeof server !== 'object'
      || Array.isArray(server) || !['streamable_http', 'streamable-http', 'http'].includes(server.transport)
      || typeof server.url !== 'string' || !URL.canParse(server.url)
      || !['http:', 'https:'].includes(new URL(server.url).protocol)) {
      throw new TaskConfigError('Unsupported MCP configuration for server ' + name + '; expected Streamable HTTP');
    }
    if (server.headers != null && (typeof server.headers !== 'object' || Array.isArray(server.headers)
      || !Object.values(server.headers).every(value => typeof value === 'string'))) {
      throw new TaskConfigError('MCP headers must be strings for server ' + name);
    }
    return {
      id: 'diagent-mcp-' + name,
      name: '@deepseek-ai/dsh-mcp-client',
      config: {
        serverName: name,
        transport: 'streamable-http',
        url: server.url,
        headers: server.headers,
        failOnStartupError: true,
      },
    };
  });
}

/** 将任务的工具和模型配置写到私有临时目录，返回启动时要加载的配置路径。 */
export async function writeTaskProfile(config: TaskConfig, home: string, runDirectory: string): Promise<string> {
  const skills = await skillRoots(config, home);
  const plugins = await mcpRows(config.mcpConfigPath);
  if (config.isDiosEventPublishingEnabled) {
    plugins.unshift({
      id: 'diagent-publish-event',
      name: fileURLToPath(new URL('./plugins/publish-event.js', import.meta.url)),
    });
  }
  const file = join(home, 'task.cordis.yml');
  const rows = [
    ...disabledRows.map(id => ({ id, disabled: true })),
    { id: 'system-prompt', config: {
      personaPrefix: config.systemPrompt + '\n\n本次任务的文件产物请写到：' + runDirectory,
    } },
    { id: 'skill-filesystem', config: { includeDefaultRoots: false, customSkillDirs: skills, watch: false } },
    { id: 'llm-pi-ai', config: { providers: { 'diagent-model': {
      apiKeyEnv: 'DIAGENT_MODEL_API_KEY',
      api: 'openai-completions',
      baseURL: config.model.baseURL,
      compat: { supportsDeveloperRole: false, maxTokensField: 'max_tokens' },
      models: [{ id: config.model.name, contextWindow: config.model.contextWindow }],
    } } } },
  ];
  // JSON 可由 YAML 解析器读取。配置值始终按字面量传递，避免任务内容被解释为 Cordis 表达式。
  await writeFile(file, JSON.stringify([...rows, { insert: plugins }]), { mode: 0o600 });
  return file;
}
