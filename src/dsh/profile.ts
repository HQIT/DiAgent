/** 生成任务私有的 DSH profile 补丁，限定本次运行的模型、Skills 和工具。 */
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

async function mcpRows(path: string | undefined) {
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

/**
 * 在本次运行的 DSH home 写入 profile 补丁。
 * @param home - 由调用方创建并清理的任务私有目录。
 * @returns 启动 DSH 时加载的补丁路径。
 * @throws TaskConfigError 指定的 Skill 不可用，或 MCP 配置无效。
 */
export async function writeTaskProfile(config: TaskConfig, home: string, runDirectory: string): Promise<string> {
  const skills = await skillRoots(config, home);
  const mcpPlugins = await mcpRows(config.mcpConfigPath);
  const plugins: object[] = [...mcpPlugins];
  // DSH 在原生 Windows 上提供 PowerShell，Linux 镜像才是本工具的交付环境。
  if (process.platform === 'linux') {
    plugins.push({
      id: 'diagent-legacy-shell',
      name: fileURLToPath(new URL('./plugins/legacy-shell.js', import.meta.url)),
    });
  }
  plugins.push({
    id: 'diagent-task-temperature',
    name: fileURLToPath(new URL('./plugins/task-temperature.js', import.meta.url)),
    config: { temperature: config.temperature },
  });
  if (mcpPlugins.length > 0 && config.mcpToolNames.length > 0) {
    const serverNames = mcpPlugins.map(plugin => plugin.config.serverName);
    // DSH 对原名做拼接和有损归一化。只接受能唯一对应原名的配置。
    if (serverNames.some(name => name.endsWith('_') || name.includes('__'))) {
      throw new TaskConfigError('Explicit MCP tool lists require unambiguous server names');
    }
    const toolNames = serverNames.flatMap(server => config.mcpToolNames.map(tool => `mcp__${server}__${tool}`));
    if (toolNames.some(name => name.length > 64 || /[^A-Za-z0-9_-]/.test(name) || /_[a-f0-9]{12}$/.test(name))) {
      throw new TaskConfigError('Explicit MCP tool lists require names that DSH can represent without normalization or alias ambiguity');
    }
    plugins.push({
      id: 'diagent-mcp-tool-selection',
      name: fileURLToPath(new URL('./plugins/mcp-tool-selection.js', import.meta.url)),
      config: { toolNames },
    });
  }
  if (config.maxToolRounds !== undefined) {
    plugins.push({
      id: 'diagent-tool-round-limit',
      name: fileURLToPath(new URL('./plugins/tool-round-limit.js', import.meta.url)),
      config: { maxToolRounds: config.maxToolRounds },
    });
  }
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
    ...(process.platform === 'linux' ? [
      { id: 'bash-sandbox', config: { maxTimeoutMs: 1_800_000 } },
      // 旧 shell 超时必须终止命令，底层 Bash 工具不能转入后台。
      { id: 'tool-bash', config: { promoteOnTimeout: false } },
    ] : []),
    { id: 'llm-pi-ai', config: { providers: { 'diagent-model': {
      apiKeyEnv: 'DIAGENT_MODEL_API_KEY',
      api: 'openai-completions',
      baseURL: config.model.baseURL,
      compat: { supportsDeveloperRole: false, maxTokensField: 'max_tokens' },
      models: [{ id: config.model.name, contextWindow: config.model.contextWindow }],
    } } } },
  ];
  // JSON 是 YAML 的子集，序列化可保留路径、提示词等字段里的换行和引号。
  await writeFile(file, JSON.stringify([...rows, { insert: plugins }]), { mode: 0o600 });
  return file;
}
