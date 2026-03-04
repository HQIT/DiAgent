# Agent 任务模式镜像

以**任务模式**运行 Agent：通过**统一配置文件**定义输入（任务描述、skills、MCP、subagents）和输出（log 文件、结果文件），支持立即执行、定时(cron)、周期(interval) 三种触发方式。

## 统一配置文件与 workspace

- **只挂载一个 workspace**：compose 仅挂载 `./workspace:/workspace`，配置与输出都在 workspace 内。
- **环境变量**：`TASK_CONFIG=/workspace/agent-task.yaml`、`OUTPUT_DIR=/workspace/output`，即配置文件和输出目录均在 workspace 下。
- **workspace 内建议**：`agent-task.yaml`（统一配置）、`skills/`、`mcp_servers.json`、`output/`（写 log/result）。

配置结构：

- **`app`**：应用配置（`AGENT_WORKSPACE`、`SKILLS_DIR`、Sandbox 等），注入进程供 `get_settings()` 使用。
- **`models`**：模型配置（与 `models.yaml` 一致：`default_model` + `models` 字典），内联后无需单独文件。
- **`task`**：任务与 Agent 配置：`task`（任务描述）、`system_prompt`（Agent 提示词）、`workspace`、`skills_dir`、`skill_names`（可选）、`mcp_config_path`（MCP 配置文件路径，相对 workspace 或绝对路径）、`output`、`trigger` 等。

## 使用 docker-compose（推荐）

```bash
# 准备 workspace：将 configs/agent-task.yaml 复制到 workspace/ 并放入 skills/、mcp_servers.json 等
cp configs/agent-task.yaml workspace/agent-task.yaml
mkdir -p workspace/skills workspace/output

# 启动（只挂载一个 workspace）
docker compose up -d
docker compose logs -f agent-task
```

运行后 log 与 result 写入 `workspace/output/`。更换任务时只需换挂载的 workspace 目录或改 `workspace/agent-task.yaml`。

## 构建

在项目根目录执行：

```bash
docker build -t agent-task:latest -f docker/agent-task/Dockerfile .
```

## 运行前准备

1. **workspace 目录**：内放 `agent-task.yaml`（统一配置）、`skills/`、`mcp_servers.json`、`output/`（空目录即可，用于写 task.log、task_result.txt）。
2. **环境变量**：compose 已设 `TASK_CONFIG=/workspace/agent-task.yaml`、`OUTPUT_DIR=/workspace/output`，无需改。

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `TASK_CONFIG` | 是 | 配置文件在容器内的路径，compose 默认 `/workspace/agent-task.yaml` |
| `OUTPUT_DIR` | 否 | 输出目录，compose 默认 `/workspace/output` |
| `TRIGGER_MODE` | 否 | 覆盖配置文件中的触发方式：`once` \| `schedule` \| `interval` |
| `CRON` | 条件 | `TRIGGER_MODE=schedule` 时的 cron 表达式 |
| `INTERVAL_SECONDS` | 条件 | `TRIGGER_MODE=interval` 时的间隔秒数 |

其余配置均在 `agent-task.yaml` 的 app / models / task 中，无需 `.env`。

## 运行示例

### 立即执行一次（只挂载一个 workspace）

```bash
docker run --rm \
  -v /host/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.yaml \
  -e OUTPUT_DIR=/workspace/output \
  -e TRIGGER_MODE=once \
  agent-task:latest
```

### 周期 / 定时

```bash
# 周期
docker run --rm -v /host/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.yaml -e OUTPUT_DIR=/workspace/output \
  -e TRIGGER_MODE=interval -e INTERVAL_SECONDS=3600 \
  agent-task:latest

# 定时（cron）
docker run --rm -v /host/workspace:/workspace \
  -e TASK_CONFIG=/workspace/agent-task.yaml -e OUTPUT_DIR=/workspace/output \
  -e TRIGGER_MODE=schedule -e CRON="0 9 * * *" \
  agent-task:latest
```

## 配置文件示例

- **统一配置**：放在 workspace 内 `agent-task.yaml`（含 app、models、task；MCP 用 task.mcp_config_path 指向同目录下 JSON）
- **仅任务配置**：`configs/task_example.yaml`（整文件即 task，MCP 可内联或另配）
