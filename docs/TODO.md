# DiAgent v0.1 待办

按 [兼容基线](2026-11-diagent-v0.1-compatibility-baseline.md) 跟踪实现、测试、评审和部署验证。依赖同一入口的功能按顺序推进，每项验收证据在完成后补齐。

## 当前 ticket

- [x] `publish_event` 通过本地 Linux 容器联调。DiAgent `4ec0ca3`、DiOS `f2433d9`、模拟模型、空 SQLite，无全局访问令牌。手动启动任务容器，合法事件返回 `dispatched`，非法来源被拒绝，需审批的事件返回 `approval_required`。三次运行共落库两条事件，均为合法来源，任务产物写入宿主机挂载的工作区。验收时为构建下载临时启用代理和重试，并给本地 DiOS 验收镜像补装 `sqlalchemy[asyncio]`，以满足其当前解析到的 SQLAlchemy 版本。
- [x] DiOS A2A 调度器启动 Linux 试点镜像。使用相同镜像、临时数据库及模拟模型与直连 MCP，通过 `message/send` 提交、`tasks/get` 查终态。成功用例 `f94a7feb52ea` 验证了 DiOS 生成配置、挂载共享 Skill、实际调用 Skill 和 MCP、落盘日志及登记 `task_result.md`。失败用例 `d1d5e35e5297` 模拟模型返回 HTTP 400，DiOS 登记退出码 1 和 `failed`。宿主机的 Docker Desktop 路径通过 `DIOS_HOST_WORKSPACE_ROOT` 显式映射。
- [x] 首轮直连 MCP 工具可见性已复验。早期模拟服务在处理缺少 `params` 的请求时抛错。修正响应后，延迟 `tools/list` 1.5 秒的回归在 Windows 和 Linux 均验证首个模型请求包含工具。DiOS 调度用例 `6b3fe7ab3f67` 将延迟拉到 3 秒，同样通过。双评审确认由现有 DSH 启动流程负责等待初始工具发现。
- [ ] 合入 DiOS `fix/e2ag-mcp-discovery`。DiOS `f2433d9` 在 enforce 模式下对 DSH 首发的 `server/discover` 返回 HTTP 403，模型收不到获准工具。修复在授权校验和审计后返回 JSON-RPC `-32601`，让 DSH 回退到 `initialize`。DiOS E2AG 33 项测试通过。本机用包含分支源码的 DiOS 镜像复验任务 `e72ec824b951`，首轮只显示获准的 `lookup`，越权请求返回 `MCP_TOOL_NOT_GRANTED`，任务结束后旧授权返回 `TOOL_GRANT_NOT_ACTIVE`。临时凭据文件已删除，上游只收到一次获准调用。
- [ ] 验证启用访问令牌的 DiOS 部署。接通限权事件凭据或可信网关，验证正确凭据成功、错误凭据返回 401。当前 DiOS 的后端全局令牌覆盖所有 API，调度器只将对应的 `Agent.env` 转交任务容器。

## 待推进

- [ ] 完成 task 配置映射。验证具名子 Agent、显式 MCP 工具名单、模型参数与原有 Shell 接口。
- [ ] 接通 service 的健康检查、普通 Chat 与 A2A service。
- [ ] 提供独立任务提交入口。外部调度器可提交任务、读取运行状态与结果。验收一个未部署 DiOS 的调用方使用自己的模型、MCP 和工作区完成任务。接口字段待定。
- [ ] 接通多轮会话、SSE、工具事件和人工审批提示，验证中断、会话隔离和旧历史迁移。
- [ ] 核实仍在使用的独立入口和配置，验证灰度与旧镜像回滚。

## 已验证的本地基线

- TypeScript task 试点可启动固定版本的 DSH。已有测试覆盖指定 Skill、Streamable HTTP MCP、成功产物及模型失败退出。
- `npm run test:task` 在 Windows / Node 24.9 上构建成功，11 项集成测试全部通过。测试使用真实 DSH 子进程和本机模拟服务，覆盖合法事件提交一次、拒绝时零提交、HTTP 502 不重试、策略拒绝回显和专用凭据来源。
- `DIAGENT_ENABLE_DIOS_EVENTS=false` 可关闭一次性任务的 `publish_event`。红绿测试覆盖工具从模型列表移除、工作区 `.env` 无法改回启用、DiOS 零请求和非法值报错。双评审确认该开关适合在 profile 装配时处理，MCP 保持独立装配。
- `publish_event` 的代码评审发现自定义来源规则的字面方括号与 Python `fnmatch` 不兼容，已用红测复现并修复。倒序字符范围继续拒绝。另补了目录已注册且来源匹配、但来源未开放该类型时零次提交的覆盖。
- `publish_event` 的 HLD 评审确认沿用 Cordis 插件接口。后续 Chat 可直接复用插件，届时按实际调用提取公共装配逻辑，各入口仍按各自的工具选择规则启用。DiOS 负责审批、去重与派发。
