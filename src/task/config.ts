/** 将一次性任务文件和部署环境转换为 DSH 执行配置，保留 DiOS 的输入兼容性。 */
import { readFile, stat } from 'node:fs/promises';
import { basename, extname, isAbsolute, resolve } from 'node:path';
import { parse } from 'yaml';

type ConfigObject = Record<string, unknown>;

/** 已校验的任务配置。路径按各字段的约定解析，事件工具开关由部署环境决定。 */
export interface TaskConfig {
  prompt: string;
  systemPrompt: string;
  workspace: string;
  outputDir: string;
  resultFile: string;
  logFile: string;
  stepLimit: number;
  temperature?: number;
  skillsDir: string;
  skillNames: string[];
  mcpConfigPath?: string;
  isDiosEventPublishingEnabled: boolean;
  model: {
    name: string;
    baseURL: string;
    apiKey: string;
    contextWindow?: number;
  };
}

/** 标识任务无法启动的输入错误，由命令入口映射为退出码 2。 */
export class TaskConfigError extends Error {}

function object(value: unknown, field: string): ConfigObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TaskConfigError(field + ' must be an object');
  }
  return value as ConfigObject;
}

function optionalObject(value: unknown, field: string): ConfigObject {
  return value == null ? {} : object(value, field);
}

function text(value: unknown, field: string, fallback = ''): string {
  if (value == null) return fallback;
  if (typeof value !== 'string') throw new TaskConfigError(field + ' must be a string');
  return value;
}

function requiredText(value: unknown, field: string): string {
  const result = text(value, field);
  if (!result.trim()) throw new TaskConfigError(field + ' is required');
  return result;
}

function positiveInteger(value: unknown, field: string): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 1) {
    throw new TaskConfigError(field + ' must be a positive integer');
  }
  return value;
}

function stringList(value: unknown, field: string): string[] {
  if (value == null) return [];
  if (!Array.isArray(value) || !value.every(item => typeof item === 'string')) {
    throw new TaskConfigError(field + ' must be a list of strings');
  }
  return value;
}

function fileName(value: unknown, field: string, fallback: string): string {
  const name = requiredText(value ?? fallback, field);
  if (isAbsolute(name) || basename(name) !== name || name === '.' || name === '..') {
    throw new TaskConfigError(field + ' must be a file name within the run directory');
  }
  return name;
}

async function readConfig(path: string): Promise<ConfigObject> {
  const format = extname(path).toLowerCase();
  try {
    const source = (await readFile(path, 'utf8')).replace(/^\uFEFF/, '');
    return object(format === '.yaml' || format === '.yml' ? parse(source) : JSON.parse(source), 'config');
  } catch (error) {
    if (error instanceof TaskConfigError) throw error;
    throw new TaskConfigError('Cannot read or parse task configuration: ' + path);
  }
}

/**
 * 从部署环境中的 `TASK_CONFIG` 读取一次性任务。
 * @throws TaskConfigError 配置不可读、字段无效，或任务要求当前执行器尚未支持的行为。
 */
export async function loadTaskConfig(env: NodeJS.ProcessEnv): Promise<TaskConfig> {
  const configPath = resolve(requiredText(env.TASK_CONFIG, 'TASK_CONFIG'));
  const config = await readConfig(configPath);
  const task = typeof config.task === 'string' ? config : object(config.task, 'task');
  const app = optionalObject(config.app, 'app');
  const output = optionalObject(task.output, 'task.output');
  const trigger = optionalObject(task.trigger, 'task.trigger');
  const mode = env.TRIGGER_MODE ?? trigger.mode ?? 'once';
  if (mode !== 'once') throw new TaskConfigError('The DSH task runner currently supports trigger.mode=once');
  const diosEvents = env.DIAGENT_ENABLE_DIOS_EVENTS ?? 'true';
  if (diosEvents !== 'true' && diosEvents !== 'false') {
    throw new TaskConfigError('DIAGENT_ENABLE_DIOS_EVENTS must be true or false');
  }
  if (task.subagents != null && (!Array.isArray(task.subagents) || task.subagents.length > 0)) {
    throw new TaskConfigError('Configured subagents are not supported by the DSH task runner yet');
  }
  if (task.thread_id || task.max_tool_rounds != null || task.middleware_config != null) {
    throw new TaskConfigError('Task checkpoints, max_tool_rounds and middleware_config require the Python runner');
  }

  const workspace = resolve(text(task.workspace, 'task.workspace', 'workspace'));
  try {
    if (!(await stat(workspace)).isDirectory()) throw new Error('Not a directory');
  } catch {
    throw new TaskConfigError('Workspace is not an accessible directory: ' + workspace);
  }

  const modelsFile = text(app.LLM_MODELS_CONFIG_PATH ?? env.LLM_MODELS_CONFIG_PATH, 'LLM_MODELS_CONFIG_PATH');
  const models = config.models == null && modelsFile
    ? await readConfig(resolve(modelsFile))
    : object(config.models, 'models');
  const modelKey = requiredText(
    text(task.model, 'task.model') || app.LLM_DEFAULT_MODEL || models.default_model || env.LLM_DEFAULT_MODEL,
    'task.model or models.default_model',
  );
  const model = object(object(models.models, 'models.models')[modelKey], 'model ' + modelKey);
  const provider = requiredText(model.provider, 'model.provider').toLowerCase();
  if (provider !== 'openai' && provider !== 'vllm') {
    throw new TaskConfigError('Unsupported model provider for the DSH task runner: ' + provider);
  }
  const baseURL = requiredText(model.base_url, 'model.base_url');
  if (!URL.canParse(baseURL) || !['http:', 'https:'].includes(new URL(baseURL).protocol)) {
    throw new TaskConfigError('model.base_url must be an HTTP(S) URL');
  }

  const skillsDir = resolve(workspace, text(task.skills_dir, 'task.skills_dir', 'skills'));
  const skillNames = [...new Set(stringList(task.skill_names, 'task.skill_names'))];
  if (skillNames.some(name => !name || name === '.' || name === '..' || /[\\/:]/.test(name))) {
    throw new TaskConfigError('task.skill_names must contain directory names');
  }

  const selectedTools = stringList(task.tools, 'task.tools');
  if (selectedTools.length > 0) {
    throw new TaskConfigError('Explicit MCP tool lists require tool-name mapping in the DSH runner');
  }
  const taskMcpPath = text(task.mcp_config_path, 'task.mcp_config_path');
  const defaultMcpPath = text(app.MCP_CONFIG_PATH ?? env.MCP_CONFIG_PATH, 'MCP_CONFIG_PATH');
  // 显式空工具列表或空 MCP 路径表示关闭 MCP。省略时才允许使用部署默认路径。
  const mcpConfigPath = Array.isArray(task.tools) || task.mcp_config_path === '' ? undefined
    : taskMcpPath ? resolve(workspace, taskMcpPath)
    : defaultMcpPath ? resolve(defaultMcpPath) : undefined;

  const temperature = task.temperature;
  if (temperature != null && (typeof temperature !== 'number'
    || !Number.isFinite(temperature) || temperature < 0 || temperature > 2)) {
    throw new TaskConfigError('task.temperature must be a number between 0 and 2');
  }
  const outputDir = env.OUTPUT_DIR ? resolve(env.OUTPUT_DIR)
    : task.output_dir ? resolve(workspace, requiredText(task.output_dir, 'task.output_dir'))
    : process.cwd();
  const resultFile = fileName(output.result_file, 'task.output.result_file', 'task_result.txt');
  const logFile = fileName(output.log_file, 'task.output.log_file', 'task.log');
  if (resultFile.toLowerCase() === logFile.toLowerCase()) {
    throw new TaskConfigError('Task result and log must use different files');
  }

  return {
    prompt: requiredText(task.task, 'task.task'),
    systemPrompt: text(task.system_prompt || app.AGENT_SYSTEM_PROMPT || env.AGENT_SYSTEM_PROMPT,
      'task.system_prompt', '你是用户的助理。按用户给定的任务完成工作，并清楚说明结果。'),
    workspace,
    outputDir,
    resultFile,
    logFile,
    stepLimit: positiveInteger(task.recursion_limit ?? 100, 'task.recursion_limit'),
    temperature: temperature ?? undefined,
    skillsDir,
    skillNames,
    mcpConfigPath,
    isDiosEventPublishingEnabled: diosEvents === 'true',
    model: {
      name: requiredText(model.model, 'model.model'),
      baseURL,
      apiKey: text(model.api_key || app.LLM_OPENAI_API_KEY || env.LLM_OPENAI_API_KEY || env.OPENAI_API_KEY,
        'model.api_key', 'not-needed'),
      contextWindow: model.context_length == null ? undefined
        : positiveInteger(model.context_length, 'model.context_length'),
    },
  };
}
