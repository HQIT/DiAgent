# 任务模式 workspace

compose 只挂载本目录到容器 `/workspace`，配置与输出均在此目录内。

## 目录结构

```
workspace/
├── agent-task.json   # 统一配置文件（必放，JSON）；或使用 agent-task.yaml；compose 默认 TASK_CONFIG=/workspace/agent-task.json
├── output/           # 输出目录（可空，运行时会写入 task.log、task_result.txt）；OUTPUT_DIR=/workspace/output
├── skills/           # Agent 可用的 skills，每个子目录含 SKILL.md
│   ├── web-search/
│   │   └── SKILL.md
│   └── ...
├── mcp_servers.json  # MCP 配置（task.mcp_config_path 如 "mcp_servers.json"）
├── resume_mcp/       # 若 MCP 配置里 cwd 为 "resume_mcp"，请把该目录放到此处（任务模式会把相对 cwd 解析为 workspace 内绝对路径）
└── README.md
```

首次使用可复制本目录下的 `agent-task.json` 并按需修改，或使用 `agent-task.yaml`（YAML/JSON 均支持）。MCP 配置中的 **cwd** 若为相对路径，会在任务模式中自动解析为 **相对于 workspace 的绝对路径**，因此请将 MCP 服务所需目录（如 `resume_mcp`）放在本 workspace 内。
