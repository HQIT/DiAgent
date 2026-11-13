# DiAgent

基于 LangChain + LangGraph + DeepAgents 的智能体任务执行框架，通过 Docker 容器运行复杂的 AI 任务。

## TypeScript / DSH 常驻服务试点

使用 Node.js 24.9 或更高版本。执行 `npm run build` 后运行 `npm run service:dsh`，服务在端口 `8000` 提供 `GET /health`，响应为 `{"status":"healthy"}`。执行 `npm run test:service` 验证 HTTP 契约。

`POST /v1/chat/completions` 支持非流式、无工具的单轮文本问答，返回 `choices[0].message.content`。模型从 `LLM_MODELS_CONFIG_PATH` 指定的 YAML 加载，工作区由 `AGENT_WORKSPACE` 指定。请求可指定模型，也可使用部署配置的默认模型或唯一已配置模型。省略系统消息时使用 `AGENT_SYSTEM_PROMPT`。多轮历史、工具选择和 SSE 仍在迁移中。

本机可用 `docker build --target service -f docker/agent-task-dsh/Dockerfile -t diagent-service:dsh-dev .` 构建常驻镜像。DiOS 通过 `DIOS_DIAGENT_SERVICE_IMAGE` 选择该镜像，并挂载工作区和模型配置。一次性任务仍使用同一 Dockerfile 的默认构建目标。

## TypeScript / DSH 一次性任务试点

使用 Node.js 24.9 或更高版本。安装锁定依赖后，执行使用本机模拟模型、MCP 和 DiOS 的集成测试。

```powershell
npm ci --ignore-scripts
npm run test:task
```

本地运行时，先执行 `npm run build`，设置 `TASK_CONFIG` 指向一次性任务的 JSON/YAML 文件，再执行 `npm run task:dsh`。试点 Dockerfile 位于 `docker/agent-task-dsh/Dockerfile`，可用 `docker build -f docker/agent-task-dsh/Dockerfile -t diagent-task:dsh-dev .` 单独构建。现有 Compose 仍使用 Python 镜像。

试点支持 OpenAI-compatible 模型、指定 Skills 与 Streamable HTTP MCP，保留配置的结果文件名和任务退出码。一次性任务的每轮模型请求使用 `task.temperature`，允许显式设置为 `0`，省略时沿用旧版默认值 `0.7`。具名子 Agent 的存量配置、独立触发器及 Chat/SSE 按兼容基线验收。 [v0.1 兼容基线](docs/2026-11-diagent-v0.1-compatibility-baseline.md)

一次性任务的 `task.tools` 使用 MCP 服务公布的原始工具名。省略时使用所有已发现的 MCP 工具，空数组关闭 MCP，非空数组从任务启动时发现的工具中选取。文件等内置工具仍按任务配置提供。非空名单要求服务名和工具名能唯一转换成 DSH 工具名，存在歧义或需归一化的配置会报错。DiOS 网关仍负责上游工具授权。

任务内可通过 `publish_event` 向 DiOS 提交事件。插件先检查事件目录和来源规则，每次工具调用最多提交一次，且不会重试。部署环境用 `DIOS_API` 指定 DiOS 地址，默认 `http://backend:8000`。插件可从任务容器环境读取专用于事件 API 的 `DIAGENT_EVENT_ACCESS_TOKEN`，以 Bearer 形式发送。全局令牌 `DIOS_ACCESS_TOKEN` 只配置在 DiOS backend。启用该鉴权的环境需要先接通限权事件凭据或可信网关，并验证实际注入和发布行为。

独立部署时，在启动 DiAgent 的环境设置 `DIAGENT_ENABLE_DIOS_EVENTS=false`，模型的工具列表中就不会出现 `publish_event`。该变量只接受 `true` 和 `false`，其他值会在任务启动时报告配置错误。省略时默认启用，以兼容现有 DiOS 任务。

可选的 `task.max_tool_rounds` 为正整数。模型在同一步尝试一个或多个工具调用时，共用一个轮次额度。超额的调用会在执行前被拒绝，模型仍可根据已有结果完成回答。模型若持续尝试，任务仍受 `task.recursion_limit` 和运行超时限制。

Linux 一次性任务提供旧名 `shell(command, cwd?, timeout?)`。相对工作目录以任务工作区为起点，超时单位为秒，默认 300 秒、最长 1800 秒。命令由 DSH Bash 前台执行，返回旧版的 `exit_code`、`stdout` 和 `stderr` 文本。命令使用 DSH 的非登录 Bash、权限策略、环境变量过滤和输出截尾规则。依赖登录环境或特定输出截断行为的存量调用仍须验证。

旧 Git 工作流可通过容器环境注入 `GIT_PLATFORM_TOKEN`。DiAgent 仅在兼容 `shell` 委派的 Bash 调用中显式注入该值。任务工作区的 `.env` 无法为它提供值。执行的脚本应避免把凭据写入输出或文件。

## 特性

- **多模型支持**: 支持 Ollama、vLLM、OpenAI 及兼容 API 的 LLM 提供商
- **MCP 集成**: 通过 langchain-mcp-adapters 连接外部工具服务器（支持 stdio、http 等协议）
- **DeepAgents 能力**: 集成规划、文件系统操作、子 Agent 委托等高级能力
- **Skills 系统**: 支持加载自定义技能模板（SKILL.md）
- **子 Agent 架构**: 支持配置多个专业子 Agent，主 Agent 按需委托任务
- **多触发方式**: 支持 once（单次）/ schedule（定时）/ interval（周期）执行
- **Docker 部署**: 开箱即用的容器化执行，无需本地环境配置

## 快速开始

### 1. 准备配置文件

创建 `workspace/agent-task.json` 配置文件：

```json
{
  "models": {
    "default_model": "your-model",
    "models": {
      "your-model": {
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "api_key": "sk-xxx"
      }
    }
  },
  "task": {
    "task": "你的任务描述",
    "model": "your-model"
  }
}
```

### 2. 构建 Docker 镜像

```bash
docker build -t agent-task:latest -f docker/agent-task/Dockerfile .
```

### 3. 运行任务

```bash
docker run --rm \
  -v $(pwd)/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.json \
  agent-task:latest
```

或使用 docker-compose：

```bash
docker-compose up
```

## 配置文件详解

配置文件为 JSON 或 YAML 格式，包含 `models` 和 `task` 两个主要部分。

### models 配置

定义可用的 LLM 模型。

```json
{
  "models": {
    "default_model": "ecnu-max",
    "models": {
      "ecnu-max": {
        "provider": "openai",
        "model": "ecnu-max",
        "base_url": "https://chat.ecnu.edu.cn/open/api/v1",
        "api_key": "sk-xxx",
        "display_name": "ECNU Max",
        "context_length": 128000
      }
    }
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `default_model` | string | 是 | 默认使用的模型 ID |
| `models` | object | 是 | 模型配置字典，key 为模型 ID |
| `models.<id>.provider` | string | 是 | 提供商：`openai` / `ollama` / `vllm` |
| `models.<id>.model` | string | 是 | 实际模型名称 |
| `models.<id>.base_url` | string | 是 | API 端点 URL |
| `models.<id>.api_key` | string | 否 | API 密钥 |
| `models.<id>.display_name` | string | 否 | 显示名称 |
| `models.<id>.context_length` | number | 否 | 上下文长度 |

### task 配置

定义要执行的任务。

```json
{
  "task": {
    "task": "帮我写一篇关于人工智能的论文",
    "model": "ecnu-max",
    "temperature": 0.7,
    "system_prompt": "你是一个专业的学术助手...",
    "workspace": "/workspace",
    "skills_dir": "skills",
    "skill_names": ["paper-structure", "experiment-design"],
    "mcp_config_path": "mcp_servers.json",
    "tools": [],
    "output": {
      "log_file": "task.log",
      "result_file": "task_result.md"
    },
    "output_dir": "output",
    "trigger": {
      "mode": "once"
    },
    "recursion_limit": 100,
    "subagents": []
  }
}
```

#### 基本字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `task` | string | 是 | - | 任务描述，作为用户消息传给 Agent |
| `model` | string | 否 | `default_model` | 使用的模型 ID |
| `temperature` | number | 否 | `0.7` | 生成温度 (0-2) |
| `system_prompt` | string | 否 | 内置提示词 | 自定义系统提示词 |
| `recursion_limit` | number | 否 | `100` | Agent 递归/步数上限 |

#### 工作区配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `workspace` | string | 否 | `workspace` | 工作区根目录（容器内路径，如 `/workspace`） |
| `skills_dir` | string | 否 | `skills` | Skills 目录名（相对 workspace） |
| `skill_names` | array | 否 | `[]` | 启用的技能列表，空表示启用全部 |
| `mcp_config_path` | string | 否 | `""` | MCP 配置文件路径（相对 workspace），空表示不使用 MCP |
| `tools` | array | 否 | 省略 | MCP 工具原始名称列表。省略启用全部，空数组关闭 MCP 工具 |

#### 输出配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `output.log_file` | string | 否 | `task.log` | 执行日志文件名 |
| `output.result_file` | string | 否 | `task_result.txt` | 最终结果文件名 |
| `output_dir` | string | 否 | 当前目录 | 输出目录（相对 workspace） |

#### 触发配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `trigger.mode` | string | 否 | `once` | 触发模式：`once` / `schedule` / `interval` |
| `trigger.cron` | string | 否 | - | Cron 表达式（mode=schedule 时使用） |
| `trigger.interval_seconds` | number | 否 | - | 执行间隔秒数（mode=interval 时使用） |

### subagents 配置

定义可供主 Agent 调用的子 Agent。

```json
{
  "subagents": [
    {
      "name": "researcher",
      "description": "联网调研与文献资料收集",
      "prompt": "你是论文调研人员，专门负责联网搜索与资料收集...",
      "tools": [],
      "model": "ecnu-max",
      "mcp_config_path": "mcp_servers.json",
      "skills_dir": "skills",
      "skill_names": []
    }
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | 是 | 子 Agent 名称（用于调用标识） |
| `description` | string | 是 | 描述（供主 Agent 决策是否调用） |
| `prompt` | string | 是 | 子 Agent 的系统提示词 |
| `tools` | array | 否 | 可用工具列表，空表示与主 Agent 一致 |
| `model` | string | 否 | 使用的模型，空表示与主 Agent 一致 |
| `mcp_config_path` | string | 否 | 独立的 MCP 配置路径 |
| `skills_dir` | string | 否 | Skills 目录 |
| `skill_names` | array | 否 | 启用的技能列表 |

### MCP 配置

MCP（Model Context Protocol）服务器配置文件，用于连接外部工具。

创建 `workspace/mcp_servers.json`：

```json
{
  "web-search": {
    "transport": "http",
    "url": "https://your-mcp-server/mcp",
    "headers": {
      "Authorization": "Bearer your_api_key"
    }
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `transport` | string | 是 | 传输协议：`stdio` / `http` / `sse` / `websocket` |
| `url` | string | 是* | HTTP/SSE/WebSocket 类型的服务器 URL |
| `command` | string | 是* | stdio 类型的启动命令 |
| `args` | array | 否 | stdio 类型的命令参数 |
| `cwd` | string | 否 | stdio 类型的工作目录 |
| `headers` | object | 否 | HTTP 请求头 |

## Docker 运行

### 环境变量

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `TASK_CONFIG` | 是 | - | 任务配置文件路径（容器内路径） |
| `OUTPUT_DIR` | 否 | 配置中的 `output_dir` | 输出目录覆盖 |
| `TRIGGER_MODE` | 否 | 配置中的 `trigger.mode` | 触发模式覆盖 |
| `CRON` | 否 | 配置中的 `trigger.cron` | Cron 表达式覆盖 |
| `INTERVAL_SECONDS` | 否 | 配置中的 `trigger.interval_seconds` | 间隔秒数覆盖 |

### 使用 docker run

```bash
# 单次执行
docker run --rm \
  -v $(pwd)/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.json \
  agent-task:latest

# 指定输出目录
docker run --rm \
  -v $(pwd)/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.json \
  -e OUTPUT_DIR=/workspace/output \
  agent-task:latest

# 定时执行（每天 9 点）
docker run -d \
  -v $(pwd)/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.json \
  -e TRIGGER_MODE=schedule \
  -e CRON="0 9 * * *" \
  agent-task:latest

# 周期执行（每小时）
docker run -d \
  -v $(pwd)/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.json \
  -e TRIGGER_MODE=interval \
  -e INTERVAL_SECONDS=3600 \
  agent-task:latest
```

### 使用 docker-compose

```yaml
version: '3.8'

services:
  agent-task:
    build:
      context: .
      dockerfile: docker/agent-task/Dockerfile
    volumes:
      - ./workspace:/workspace
    environment:
      - TASK_CONFIG=/workspace/agent-task.json
```

```bash
docker-compose up --build
```

## 项目结构

```
DiAgent/
├── app/
│   ├── config.py            # 配置管理
│   ├── core/                 # Agent 核心
│   │   ├── agent.py          # AgentService
│   │   ├── preprocessor.py   # 请求预处理
│   │   └── response_formatter.py
│   ├── llm/                  # LLM 适配器
│   │   ├── factory.py        # LLM 工厂
│   │   ├── ollama_adapter.py
│   │   ├── vllm_adapter.py
│   │   └── openai_adapter.py
│   ├── mcp/                  # MCP 客户端
│   │   ├── client.py         # MCPClientManager
│   │   └── tool_registry.py
│   ├── middleware/           # 中间件
│   │   └── custom_middlewares.py
│   └── task/                 # 任务模式
│       ├── entrypoint.py     # 入口
│       ├── runner.py         # 任务执行器
│       ├── config_schema.py  # 配置 Schema
│       └── triggers.py       # 触发器
├── workspace/                # 工作区（挂载到容器）
│   ├── agent-task.json       # 任务配置
│   ├── mcp_servers.json      # MCP 配置
│   ├── skills/               # 技能目录
│   │   └── */SKILL.md
│   └── output/               # 任务输出
├── docker/
│   └── agent-task/
│       └── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## Skills 系统

Skills 是预定义的技能模板，Agent 执行任务时可以参考。每个技能是一个目录，包含 `SKILL.md` 文件。

```
workspace/skills/
├── paper-review/
│   └── SKILL.md          # 论文审阅技能
├── experiment-design/
│   └── SKILL.md          # 实验设计技能
└── paper-structure/
    └── SKILL.md          # 论文结构技能
```

在配置中通过 `skill_names` 指定要启用的技能：

```json
{
  "task": {
    "skill_names": ["paper-structure", "experiment-design"]
  }
}
```

## 完整配置示例

```json
{
  "models": {
    "default_model": "ecnu-max",
    "models": {
      "ecnu-max": {
        "provider": "openai",
        "model": "ecnu-max",
        "base_url": "https://chat.ecnu.edu.cn/open/api/v1",
        "api_key": "sk-xxx",
        "context_length": 128000
      }
    }
  },
  "task": {
    "task": "帮我写一篇关于图像加密的论文",
    "model": "ecnu-max",
    "temperature": 0.7,
    "system_prompt": "你是论文编写项目的协调者...",
    "workspace": "/workspace",
    "skills_dir": "skills",
    "mcp_config_path": "",
    "output": {
      "log_file": "task.log",
      "result_file": "task_result.md"
    },
    "output_dir": "output",
    "trigger": {
      "mode": "once"
    },
    "recursion_limit": 100,
    "subagents": [
      {
        "name": "researcher",
        "description": "联网调研与文献资料收集",
        "prompt": "你是论文调研人员...",
        "model": "ecnu-max",
        "mcp_config_path": "mcp_servers.json"
      },
      {
        "name": "writer",
        "description": "论文撰写与修改",
        "prompt": "你是论文编写者...",
        "model": "ecnu-max",
        "skill_names": ["paper-structure", "experiment-design"]
      },
      {
        "name": "reviewer",
        "description": "论文审核",
        "prompt": "你是论文审核员...",
        "model": "ecnu-max",
        "skill_names": ["paper-review"]
      }
    ]
  }
}
```

## License

MIT
