"""任务执行器：按 TaskConfig 构建 agent、执行单次任务、写 log 与 result 文件。"""

import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage, BaseMessage
from loguru import logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend

from ..config import get_settings
from ..core.agent import get_system_prompt
from ..llm import get_llm
from ..mcp.client import MCPClientManager
from ..mcp.tool_registry import ToolRegistry, wrap_tool_with_fallback, wrap_tools_with_fallback
from ..middleware.custom_middlewares import get_logging_middlewares
from ..tools import shell_tool, publish_event_tool

from .config_schema import TaskConfig, SubagentSpec

# 任务模式下的 app 根目录（与 agent 模块一致）
_APP_ROOT = Path(__file__).parent.parent.parent.resolve()


def _make_run_id(task: str, max_slug_len: int = 40) -> str:
    """根据任务内容生成本次运行的唯一目录名：任务摘要 + 随机 id，避免覆盖历史结果。"""
    slug = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", (task or "task").strip())[:max_slug_len].strip("_") or "task"
    return f"{slug}_{uuid.uuid4().hex[:8]}"


def _resolve_workspace_root(workspace: str) -> Path:
    """解析工作区根目录。"""
    raw = workspace.strip() or "workspace"
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    return (_APP_ROOT / raw).resolve()


def _single_message_to_log_lines(msg: BaseMessage) -> List[str]:
    """单条 message 转 log 行，用于实时追加写入。"""
    out: List[str] = []
    if isinstance(msg, HumanMessage):
        out.append(f"[user] {msg.content}")
    elif isinstance(msg, AIMessage):
        if msg.content:
            out.append(f"[assistant] {msg.content}")
        for tc in getattr(msg, "tool_calls", None) or []:
            name = tc.get("name", "?")
            args = tc.get("args", {}) or {}
            subagent_type = (args.get("subagent_type") if isinstance(args, dict) else None) or ""
            if name == "task" and subagent_type:
                desc = (args.get("description") or "")[:200]
                if len((args.get("description") or "")) > 200:
                    desc += "..."
                out.append(f"[subagent_call] {subagent_type} | description: {desc}")
            out.append(f"[tool_call] {name} args={args}")
    elif isinstance(msg, ToolMessage):
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        preview = content[:500] + "..." if len(content) > 500 else content
        out.append(f"[tool_result] {msg.name} -> {preview}")
    return out


def _messages_to_log_lines(messages: List[BaseMessage]) -> List[str]:
    """将 agent 的 messages 转为 log 文本行（含 tool 调用、subagent 委托与返回）。"""
    lines: List[str] = []
    for msg in messages:
        lines.extend(_single_message_to_log_lines(msg))
    return lines


class TaskRunner:
    """按 TaskConfig 执行单次任务并写出 log / result。"""

    def __init__(self, config: TaskConfig):
        self.config = config
        self._mcp_client: Optional[MCPClientManager] = None
        self._subagent_mcp_clients: Dict[str, MCPClientManager] = {}

    def _resolve_mcp_config_path(self, workspace_root: Path, path_str: Optional[str] = None) -> Optional[str]:
        """解析 MCP 配置路径。path_str 为空时用主 task 的。
        - 主 task：mcp_config_path 显式写 '' 表示不用 MCP；未填(None)则用 app 默认且相对项目根解析；否则相对 workspace。
        - subagent(path_str 非空)：相对 workspace 解析。
        """
        if path_str is not None:
            raw = (path_str or "").strip() or None
            base = workspace_root
        else:
            task_path = self.config.mcp_config_path
            if task_path is not None and (not isinstance(task_path, str) or not task_path.strip()):
                raw = None
                base = workspace_root
            else:
                raw = (task_path or get_settings().mcp_config_path) or None
                raw = (raw.strip() or None) if raw else None
                base = _APP_ROOT if task_path is None else workspace_root
        if not raw:
            return None
        p = Path(raw)
        if not p.is_absolute():
            p = (base / raw).resolve()
        return str(p)

    def _load_mcp_config_with_workspace_cwd(self, workspace_root: Path) -> Optional[Dict[str, Any]]:
        """加载 MCP 配置，并将其中相对路径的 cwd 解析为相对于 workspace 的绝对路径（任务/Docker 下避免 FileNotFoundError）。"""
        path = self._resolve_mcp_config_path(workspace_root, None)
        if not path or not Path(path).exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        out: Dict[str, Any] = {}
        for name, server in raw.items():
            if not isinstance(server, dict):
                out[name] = server
                continue
            cwd = server.get("cwd")
            if cwd and not Path(cwd).is_absolute():
                server = {**server, "cwd": str((workspace_root / cwd).resolve())}
            out[name] = server
        return out

    def _load_mcp_config_for_path(self, workspace_root: Path, path_str: str) -> Optional[Dict[str, Any]]:
        """按给定路径加载 MCP 配置（相对 workspace），并将 cwd 解析为绝对路径。"""
        path = self._resolve_mcp_config_path(workspace_root, path_str)
        if not path or not Path(path).exists():
            return None
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        out: Dict[str, Any] = {}
        for name, server in raw.items():
            if not isinstance(server, dict):
                out[name] = server
                continue
            cwd = server.get("cwd")
            if cwd and not Path(cwd).is_absolute():
                server = {**server, "cwd": str((workspace_root / cwd).resolve())}
            out[name] = server
        return out

    async def _get_mcp_client_for_path(self, workspace_root: Path, path_str: str) -> MCPClientManager:
        """获取指定 MCP 配置对应的客户端（用于 subagent 独立 MCP），按 path_str 缓存。"""
        if path_str in self._subagent_mcp_clients:
            return self._subagent_mcp_clients[path_str]
        server_configs = self._load_mcp_config_for_path(workspace_root, path_str)
        if server_configs:
            client = MCPClientManager(server_configs=server_configs)
        else:
            path = self._resolve_mcp_config_path(workspace_root, path_str)
            client = MCPClientManager(config_path=path)
        await client.connect_all()
        self._subagent_mcp_clients[path_str] = client
        return client

    async def _get_mcp_client(self, workspace_root: Path) -> MCPClientManager:
        if self._mcp_client is not None:
            return self._mcp_client
        # 任务模式：加载配置并把相对 cwd 解析为 workspace 内绝对路径，再传内联配置
        server_configs = self._load_mcp_config_with_workspace_cwd(workspace_root)
        if server_configs:
            client = MCPClientManager(server_configs=server_configs)
        else:
            path = self._resolve_mcp_config_path(workspace_root)
            client = MCPClientManager(config_path=path)
        await client.connect_all()
        self._mcp_client = client
        return client

    async def run(self, output_dir: Optional[Path] = None) -> str:
        """
        执行一次任务：构建 agent、invoke、写 log 与 result 文件。
        output_dir: 输出目录；每次运行会在其下创建「任务摘要_随机id」子目录，log/result 写入该子目录，避免覆盖。
        返回最终答案文本。
        """
        output_dir = output_dir or Path.cwd()
        run_id = _make_run_id(self.config.task)
        run_output_dir = output_dir / run_id
        log_path = run_output_dir / self.config.output.log_file
        result_path = run_output_dir / self.config.output.result_file
        logger.info("本次输出目录: {} (run_id={})", run_output_dir, run_id)

        workspace_root = _resolve_workspace_root(self.config.workspace)
        settings = get_settings()

        # 模型与工具
        model_str = self.config.model or settings.llm_default_model
        llm = get_llm(model_str, temperature=self.config.temperature)
        mcp_client = await self._get_mcp_client(workspace_root)
        registry = ToolRegistry(mcp_client)
        tools = wrap_tools_with_fallback(registry.get_langchain_tools(self.config.tools))
        tools = list(tools) + [shell_tool, publish_event_tool]

        # Skills 路径
        if self.config.skill_names:
            skills_paths = [
                f"{workspace_root}/{self.config.skills_dir}/{name}/"
                for name in self.config.skill_names
            ]
        else:
            skills_paths = [f"{workspace_root}/{self.config.skills_dir}/"]

        backend = FilesystemBackend(root_dir=str(workspace_root), virtual_mode=False)
        middlewares = list(get_logging_middlewares())
        enabled_middlewares = (self.config.middleware_config or {}).get("enabled") if self.config.middleware_config else None
        if enabled_middlewares:
            enabled_set = {str(x).strip() for x in enabled_middlewares if str(x).strip()}
            middlewares = [m for m in middlewares if getattr(m, "__name__", "") in enabled_set]

        # Subagents（转为 deepagents 期望的 dict；支持单独 mcp_config_path、skills_dir、skill_names）
        subagents_list: Optional[List[dict]] = None
        if self.config.subagents:
            subagents_list = []
            for s in self.config.subagents:
                # 工具：独立 MCP 时用该配置的工具列表，否则用主 registry 按 s.tools 过滤
                if s.mcp_config_path:
                    sub_mcp = await self._get_mcp_client_for_path(workspace_root, s.mcp_config_path)
                    sub_registry = ToolRegistry(sub_mcp)
                    sub_tools = wrap_tools_with_fallback(
                        sub_registry.get_langchain_tools(s.tools if s.tools else None)
                    )
                else:
                    sub_tools = wrap_tools_with_fallback(
                        registry.get_langchain_tools(s.tools if s.tools else None)
                    )
                # Skills：单独配置则用 subagent 的目录/列表，否则与主 task 一致
                if s.skills_dir is not None or s.skill_names is not None:
                    sd = s.skills_dir if s.skills_dir is not None else self.config.skills_dir
                    if s.skill_names:
                        sub_skills = [f"{workspace_root}/{sd}/{name}/" for name in s.skill_names]
                    else:
                        sub_skills = [f"{workspace_root}/{sd}/"]
                else:
                    sub_skills = skills_paths
                # model：传 LLM 实例而非字符串，避免 deepagents 无法从 "ecnu-max" 等推断 provider
                sub_model: Any = None
                if s.model:
                    sub_llm = get_llm(s.model, temperature=self.config.temperature)
                    sub_model = sub_llm.client
                entry = {
                    "name": s.name,
                    "description": s.description,
                    "system_prompt": s.prompt,
                    "tools": sub_tools,
                    "skills": sub_skills,
                    "model": sub_model,
                    **({"task": s.task} if s.task else {}),
                }
                # 与主 agent 一致：产出物写入本次任务 output 目录
                try:
                    _rel_out = run_output_dir.relative_to(workspace_root)
                except ValueError:
                    _rel_out = run_output_dir
                out_hint = f"\n\n【本次任务产出目录】所有生成的文件（论文草稿、技术方案、报告等）请统一写入此目录。绝对路径：{run_output_dir}；相对 workspace 的路径：{_rel_out}（write 等工具请使用此相对路径）。"
                entry["system_prompt"] = entry["system_prompt"].rstrip() + out_hint
                subagents_list.append(entry)

        try:
            rel_output = run_output_dir.relative_to(workspace_root)
        except ValueError:
            rel_output = run_output_dir
        output_dir_hint = f"\n\n【本次任务产出目录】所有产出文件（含子 agent 生成的草稿、报告等）请统一写入此目录。绝对路径：{run_output_dir}；相对 workspace：{rel_output}（write 等工具请使用此相对路径）。委托子 agent 时请说明该路径，确保文件都写在此目录下。"
        system_prompt = (self.config.system_prompt if self.config.system_prompt else get_system_prompt()).rstrip() + output_dir_hint
        agent_kwargs: dict = {
            "model": llm.client,
            "tools": tools,
            "system_prompt": system_prompt,
            "backend": backend,
            "skills": skills_paths,
            "middleware": middlewares,
        }
        if subagents_list is not None:
            agent_kwargs["subagents"] = subagents_list

        agent = create_deep_agent(**agent_kwargs)
        run_config = {"recursion_limit": self.config.recursion_limit}
        if self.config.max_tool_rounds is not None:
            run_config["max_tool_rounds"] = int(self.config.max_tool_rounds)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        result: Dict[str, Any] = {}

        try:
            try:
                input_messages = [HumanMessage(content=self.config.task)]
                try:
                    stream = agent.astream(
                        {"messages": input_messages},
                        config=run_config,
                        stream_mode=["updates", "values"],
                    )
                except (TypeError, ValueError):
                    stream = None
                if stream is not None:
                    latest_messages: List[BaseMessage] = []
                    with open(log_path, "w", encoding="utf-8") as log_file:
                        log_file.write(f"[start] task: {self.config.task[:200]}...\n" if len(self.config.task) > 200 else f"[start] task: {self.config.task}\n")
                        log_file.flush()
                        async for chunk in stream:
                            if not isinstance(chunk, (list, tuple)) or len(chunk) < 2:
                                continue
                            if len(chunk) == 3:
                                namespace, mode, data = chunk[0], chunk[1], chunk[2]
                                if namespace and namespace != ():
                                    continue
                            else:
                                mode, data = chunk[0], chunk[1]
                            if mode not in ("updates", "values"):
                                continue
                            if mode == "values" and isinstance(data, dict):
                                result = data
                            elif mode == "updates" and data:
                                node_update = data if isinstance(data, (list, tuple)) and len(data) == 2 else (None, data)
                                update = node_update[1] if isinstance(node_update, (list, tuple)) and len(node_update) == 2 else data
                                if isinstance(update, dict):
                                    update_messages = update.get("messages") or []
                                    if update_messages:
                                        latest_messages = list(update_messages)
                                    for msg in update_messages:
                                        for line in _single_message_to_log_lines(msg):
                                            log_file.write(line + "\n")
                                        log_file.flush()
                    if not result:
                        # astream 已经执行过任务，避免再触发一次 ainvoke 导致重复副作用。
                        result = {"messages": latest_messages}
                else:
                    result = await agent.ainvoke({"messages": input_messages}, config=run_config)
                    messages = result.get("messages", [])
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text("\n".join(_messages_to_log_lines(messages)), encoding="utf-8")
            finally:
                pass

            logger.info("已写入 log: {}", log_path)
            messages = result.get("messages", [])
            final_message = messages[-1] if messages else None
            result_text = (final_message.content if hasattr(final_message, "content") and final_message else "") or ""
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(result_text, encoding="utf-8")
            logger.info("已写入 result: {}", result_path)
            return result_text

        except Exception as e:
            logger.exception("任务执行失败: {}", e)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(f"\n[error] 任务执行失败: {e}\n")
            except Exception:
                pass
            result_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                result_path.write_text(f"任务执行失败:\n{type(e).__name__}: {e}", encoding="utf-8")
            except Exception:
                pass
            raise

    async def close(self) -> None:
        for client in self._subagent_mcp_clients.values():
            await client.disconnect_all()
        self._subagent_mcp_clients.clear()
        if self._mcp_client:
            await self._mcp_client.disconnect_all()
            self._mcp_client = None


async def run_task(config: TaskConfig, output_dir: Optional[Path] = None) -> str:
    """执行单次任务并返回最终答案。"""
    runner = TaskRunner(config)
    try:
        return await runner.run(output_dir=output_dir)
    finally:
        await runner.close()
