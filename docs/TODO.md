# DiAgent v0.1 待办

按 [兼容基线](2026-11-diagent-v0.1-compatibility-baseline.md) 跟踪实现、测试、评审和部署验证。依赖同一入口的功能按顺序推进，每项验收证据在完成后补齐。

## 当前 ticket

- [x] `publish_event` 通过本地 Linux 容器联调。DiAgent `4ec0ca3`、DiOS `f2433d9`、模拟模型、空 SQLite，无全局访问令牌。手动启动任务容器，合法事件返回 `dispatched`，非法来源被拒绝，需审批的事件返回 `approval_required`。三次运行共落库两条事件，均为合法来源，任务产物写入宿主机挂载的工作区。验收时为构建下载临时启用代理和重试，并给本地 DiOS 验收镜像补装 `sqlalchemy[asyncio]`，以满足其当前解析到的 SQLAlchemy 版本。
- [ ] 验证启用访问令牌的 DiOS 部署。接通限权事件凭据或可信网关，验证正确凭据成功、错误凭据返回 401。当前 DiOS 的后端全局令牌覆盖所有 API，调度器只将对应的 `Agent.env` 转交任务容器。

## 待推进

- [ ] 完成 task 配置映射。验证具名子 Agent、显式 MCP 工具名单、模型参数与原有 Shell 接口。
- [ ] 通过 DiOS 调度器启动 Linux 试点镜像，验证实际下发的配置、挂载、模型、Skills、工具、产物登记和退出状态。
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
