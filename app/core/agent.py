"""Agent核心服务"""

from pathlib import Path
from typing import AsyncGenerator, Optional, List, Dict, Any, Union
from dataclasses import dataclass
from datetime import datetime
from loguru import logger

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from ..schemas.extended_request import ExtendedChatRequest
from ..schemas.openai_types import ChatCompletionResponse, ChatMessage
from ..llm import get_llm, BaseLLMAdapter
from ..mcp.client import MCPClientManager, get_mcp_client
from ..mcp.tool_registry import ToolRegistry
from ..middleware.custom_middlewares import get_logging_middlewares
from ..tools import shell_tool
from .preprocessor import RequestPreprocessor, ProcessedRequest
from .response_formatter import ResponseFormatter
from ..config import get_settings

# 项目根目录（app 所在仓库根，用于解析相对路径）
_APP_ROOT = Path(__file__).parent.parent.parent.resolve()


def get_workspace_root() -> Path:
    """解析 agent 工作区根目录（backend 根、skills 所在目录）。
    
    由配置 AGENT_WORKSPACE 指定：相对路径相对项目根解析，绝对路径直接使用。
    默认 "workspace" 表示项目根下的 workspace 目录。
    """
    settings = get_settings()
    raw = settings.agent_workspace.strip() or "workspace"
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    return (_APP_ROOT / raw).resolve()


def get_system_prompt() -> str:
    """生成动态系统提示词
    
    如果设置了 AGENT_SYSTEM_PROMPT 环境变量，使用该值（附加当前时间）。
    否则使用默认提示词。
    """
    settings = get_settings()
    now = datetime.now()
    if settings.agent_system_prompt:
        current_time = now.strftime("%Y年%m月%d日 %H:%M:%S")
        weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        weekday = weekday_names[now.weekday()]
        return f"{settings.agent_system_prompt}\n\n当前时间：{current_time} {weekday}"
    
    current_time = now.strftime("%Y年%m月%d日 %H:%M:%S")
    weekday_names = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    weekday = weekday_names[now.weekday()]
    
    return f"""你是用户的个人助理，风格活泼、亲切、像朋友一样好相处。

## 当前信息
- 现在：{current_time} {weekday}

## 你的风格
- 语气轻松自然，可以适当用口语、emoji 或短句，但别啰嗦
- 像在跟朋友聊天：可以说「好嘞」「没问题」「搞定」这类话
- 需要帮忙时主动一点，比如「我来帮你查一下」「交给我」
- 回答时用用户用的语言（中文或英文），保持同频

## 做事方式
- 要用工具前，简单说一句你在干嘛（比如「我先帮你查一下邮件」），再用工具
- 工具跑完后，用结果直接给出清晰好懂的结论或建议
- 搞不定就老实说，并给一点替代建议
- 信息说清楚就行，不堆废话"""


@dataclass
class AgentContext:
    """Agent执行上下文"""
    request: ProcessedRequest
    messages: List[ChatMessage]
    tools: List[Any]
    user_context: Dict[str, Any]
    custom_fields: Dict[str, Any]


class AgentService:
    """Agent服务核心
    
    处理聊天请求，协调LLM、工具
    """
    
    def __init__(
        self,
        mcp_client: MCPClientManager,
        middlewares: Optional[List[AgentMiddleware]] = None
    ):
        self.mcp_client = mcp_client
        self.tool_registry = ToolRegistry(mcp_client)
        self.preprocessor = RequestPreprocessor()
        self.middlewares = middlewares or []
    
    async def chat(
        self,
        request: ExtendedChatRequest
    ) -> Union[ChatCompletionResponse, AsyncGenerator[str, None]]:
        """处理聊天请求
        
        Args:
            request: 扩展请求
            
        Returns:
            响应对象或流式生成器
        """
        
        # 1. 预处理请求
        processed = self.preprocessor.process(request)
        
        # 2. 获取选择的工具（空列表表示不启用工具；不再默认注入 shell）
        selected_tool_ids = processed.selected_tool_ids or []
        tools = self.tool_registry.get_langchain_tools(selected_tool_ids)
        if "shell" in selected_tool_ids:
            tools = list(tools) + [shell_tool]

        logger.info(f"处理请求: model={processed.model}, "
                   f"messages={len(processed.messages)}, "
                   f"tools={len(tools)}, "
                   f"stream={processed.stream}")
        
        # 3. 创建响应格式化器
        formatter = ResponseFormatter(processed.model)
        
        # 4. 执行Agent
        try:
            if processed.stream:
                return self._stream_chat(
                    processed, processed.messages, tools, formatter
                )
            else:
                return await self._invoke_chat(
                    processed, processed.messages, tools, formatter
                )
        except Exception as e:
            logger.error(f"Agent执行失败: {e}")
            raise
    
    async def _invoke_chat(
        self,
        processed: ProcessedRequest,
        messages: List[ChatMessage],
        tools: List[Any],
        formatter: ResponseFormatter
    ) -> ChatCompletionResponse:
        """非流式聊天
        
        Args:
            processed: 预处理后的请求
            messages: 消息列表
            tools: 工具列表
            formatter: 响应格式化器
            
        Returns:
            聊天响应
        """
        # 获取LLM
        llm = get_llm(processed.model, temperature=processed.temperature)

        # deepagents 模式下，system prompt 通过 system_prompt 字段传入；
        # 输入 messages 中不再保留 system，避免 ECNU 侧出现多 system。
        tool_system_prompt, tool_messages = self._split_system_prompt(messages)
        lc_messages = self._to_langchain_messages(tool_messages if tools else messages)
        
        if tools:
            # 使用 deepagents 的 create_deep_agent（规划、文件系统、子agent等能力）
            workspace_root = get_workspace_root()
            logger.info(f"[workspace_root] {workspace_root}")
            backend = FilesystemBackend(
                root_dir=str(workspace_root),
                virtual_mode=False,
            )
            settings = get_settings()
            skills_path = f"{workspace_root}/{settings.skills_dir}/"
            agent_kwargs = {
                "model": llm.client,
                "tools": tools,
                "system_prompt": tool_system_prompt,
                "backend": backend,
                "skills": [skills_path],
            }
            middlewares = self._resolve_middlewares(processed)
            if middlewares:
                agent_kwargs["middleware"] = middlewares
            
            agent = create_deep_agent(**agent_kwargs)
            
            recursion_limit = self._resolve_recursion_limit(processed)
            config = {"recursion_limit": recursion_limit}
            result = await agent.ainvoke(
                {"messages": lc_messages},
                config=config
            )
            
            # 提取最终响应
            final_message = result.get("messages", [])[-1] if result.get("messages") else None
            content = final_message.content if final_message else ""
        else:
            # 无工具，直接调用LLM
            content = await llm.invoke(
                [msg.model_dump(exclude_none=True) for msg in messages]
            )
        
        return formatter.format_response(content)
    
    async def _stream_chat(
        self,
        processed: ProcessedRequest,
        messages: List[ChatMessage],
        tools: List[Any],
        formatter: ResponseFormatter
    ) -> AsyncGenerator[str, None]:
        """流式聊天 - 优化版本
        
        策略：
        - 工具调用轮次：缓冲内容，作为 reasoning 一次性发送（非流式）
        - 最终回答轮次：真正的 token-by-token 流式输出
        
        Args:
            processed: 预处理后的请求
            messages: 消息列表
            tools: 工具列表
            formatter: 响应格式化器
            
        Yields:
            SSE格式响应块
        """
        import time as time_module
        import uuid
        
        # 获取LLM
        llm = get_llm(processed.model, temperature=processed.temperature)

        # deepagents 模式下，system prompt 通过 system_prompt 字段传入；
        # 输入 messages 中不再保留 system，避免 ECNU 侧出现多 system。
        tool_system_prompt, tool_messages = self._split_system_prompt(messages)
        lc_messages = self._to_langchain_messages(tool_messages if tools else messages)
        
        # 最终回答收集
        collected_content = []
        role_sent = False
        
        # 当前轮次状态
        current_round_buffer = []  # 当前轮次的内容缓冲
        current_round_has_tools = False  # 当前轮次是否有工具调用
        tool_start_times = {}  # 记录工具开始时间
        
        if tools:
            # 使用 deepagents 的 create_deep_agent（支持流式输出）
            workspace_root = get_workspace_root()
            logger.info(f"[workspace_root] {workspace_root}")
            backend = FilesystemBackend(
                root_dir=str(workspace_root),
                virtual_mode=False,
            )
            settings = get_settings()
            skills_path = f"{workspace_root}/{settings.skills_dir}/"
            agent_kwargs = {
                "model": llm.client,
                "tools": tools,
                "system_prompt": tool_system_prompt,
                "backend": backend,
                "skills": [skills_path],
            }
            middlewares = self._resolve_middlewares(processed)
            if middlewares:
                agent_kwargs["middleware"] = middlewares
            
            agent = create_deep_agent(**agent_kwargs)
            
            # 使用astream_events获取流式输出
            current_mode = None
            pending_chunks = []
            
            recursion_limit = self._resolve_recursion_limit(processed)
            config = {"recursion_limit": recursion_limit}
            try:
                async for event in agent.astream_events(
                    {"messages": lc_messages},
                    version="v2",
                    config=config
                ):
                    kind = event.get("event")
                    # 打印 event metadata，便于调试流式输出与过滤逻辑（仅工具/模型结束等关键事件）
                    if kind in ("on_tool_start", "on_tool_end", "on_tool_error", "on_chat_model_end"):
                        _meta = {
                            "event": kind,
                            "name": event.get("name"),
                            "run_id": str(event.get("run_id", "")),
                            "parent_run_id": str(event.get("parent_run_id", "")),
                            "tags": event.get("tags", []),
                            "metadata": event.get("metadata", {}),
                        }
                        logger.info(f"[stream_event] {_meta}")

                    if kind == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk")
                        if chunk:
                            content = getattr(chunk, "content", None)
                            tool_calls = getattr(chunk, "tool_calls", None)
                            tool_call_chunks = getattr(chunk, "tool_call_chunks", None)
                            if tool_calls or tool_call_chunks:
                                if current_mode != "reasoning":
                                    current_mode = "reasoning"
                                    logger.info("🔄 检测到工具调用，切换到推理模式")
                            if content:
                                if current_mode == "reasoning":
                                    current_round_buffer.append(content)
                                elif current_mode == "answering":
                                    collected_content.append(content)
                                    yield formatter._format_content_chunk(content)
                                else:
                                    pending_chunks.append(content)
                    
                    elif kind == "on_chat_model_end":
                        output = event.get("data", {}).get("output")
                        if output:
                            has_tool_calls = bool(getattr(output, "tool_calls", None))
                            if has_tool_calls:
                                current_mode = "reasoning"
                                if pending_chunks:
                                    current_round_buffer.extend(pending_chunks)
                                    pending_chunks = []
                            else:
                                if current_mode != "answering":
                                    current_mode = "answering"
                                    if not role_sent:
                                        yield formatter._format_role_chunk()
                                        role_sent = True
                                    if pending_chunks:
                                        for c in pending_chunks:
                                            collected_content.append(c)
                                            yield formatter._format_content_chunk(c)
                                        pending_chunks = []
                    
                    elif kind == "on_tool_start":
                        tool_name = event.get("name", "unknown")
                        run_id = event.get("run_id", str(uuid.uuid4()))
                        tool_input = event.get("data", {}).get("input", {})
                        tool_start_times[run_id] = time_module.time()
                        if current_round_buffer:
                            reasoning_content = "".join(current_round_buffer)
                            yield formatter._format_reasoning_content_chunk(reasoning_content)
                            logger.info(f"💭 [推理] {reasoning_content[:100]}...")
                            current_round_buffer = []
                        logger.info(f"🔧 [工具] 调用开始: {tool_name}")
                        yield formatter.format_tool_call_start(
                            tool_call_id=run_id,
                            tool_name=tool_name,
                            arguments=tool_input if isinstance(tool_input, dict) else {"input": tool_input}
                        )
                    
                    elif kind == "on_tool_end":
                        tool_name = event.get("name", "unknown")
                        run_id = event.get("run_id", "")
                        output = event.get("data", {}).get("output", "")
                        start_time = tool_start_times.pop(run_id, time_module.time())
                        duration_ms = (time_module.time() - start_time) * 1000
                        result_str = str(output)[:500] if output else ""
                        logger.info(f"✓  [工具] 调用完成: {tool_name} ({duration_ms:.0f}ms)")
                        yield formatter.format_tool_call_end(
                            tool_call_id=run_id,
                            tool_name=tool_name,
                            result=result_str,
                            duration_ms=duration_ms
                        )
                        current_mode = None
                        current_round_buffer = []
                        pending_chunks = []
                    
                    elif kind == "on_tool_error":
                        tool_name = event.get("name", "unknown")
                        run_id = event.get("run_id", "")
                        error = str(event.get("data", {}).get("error", "Unknown error"))
                        logger.error(f"✗  [工具] 调用失败: {tool_name} - {error}")
                        yield formatter.format_tool_call_error(
                            tool_call_id=run_id,
                            tool_name=tool_name,
                            error=error
                        )
                        current_mode = None
                        current_round_buffer = []
                        pending_chunks = []
            finally:
                pass
                
        else:
            # 无工具，直接流式调用LLM（全程真流式）
            yield formatter._format_role_chunk()
            role_sent = True
            
            msg_dicts = [msg.model_dump(exclude_none=True) for msg in messages]
            async for chunk in llm.stream(msg_dicts):
                collected_content.append(chunk)
                yield formatter._format_content_chunk(chunk)
        
        # 发送结束标记
        yield formatter._format_finish_chunk()
        yield "data: [DONE]\n\n"
        
    
    def _to_langchain_messages(self, messages: List[ChatMessage]) -> List:
        """转换为LangChain消息格式"""
        result = []
        for msg in messages:
            if msg.role == "system":
                result.append(SystemMessage(content=msg.content or ""))
            elif msg.role == "user":
                result.append(HumanMessage(content=msg.content or ""))
            elif msg.role == "assistant":
                result.append(AIMessage(content=msg.content or ""))
        return result

    def _resolve_recursion_limit(self, processed: ProcessedRequest) -> int:
        """优先使用请求中的 reasoning.recursion_limit，否则使用全局配置。"""
        limit = get_settings().agent_recursion_limit
        reasoning = (processed.custom_fields or {}).get("reasoning", {})
        if isinstance(reasoning, dict):
            val = reasoning.get("recursion_limit")
            if isinstance(val, int) and val > 0:
                return val
            if isinstance(val, str) and val.isdigit() and int(val) > 0:
                return int(val)
        return limit

    def _resolve_middlewares(self, processed: ProcessedRequest) -> List[AgentMiddleware]:
        """按请求中的 middleware_config.enabled 过滤中间件。"""
        default = list(self.middlewares or [])
        cfg = processed.middleware_config or {}
        enabled = cfg.get("enabled") if isinstance(cfg, dict) else None
        if not enabled:
            return default
        enabled_set = {str(x).strip() for x in enabled if str(x).strip()}
        if not enabled_set:
            return default
        filtered = [m for m in default if getattr(m, "__name__", "") in enabled_set]
        return filtered

    def _split_system_prompt(self, messages: List[ChatMessage]) -> tuple[str, List[ChatMessage]]:
        """拆分 system prompt 与非 system 消息。

        deepagents 会通过 `system_prompt` 管理系统提示，若同时把 system 放在
        messages 里，会在部分 OpenAI 兼容网关（如 ECNU）触发多 system 问题。
        """
        system_parts: List[str] = []
        rest: List[ChatMessage] = []
        for msg in messages:
            if msg.role == "system":
                if msg.content:
                    system_parts.append(msg.content)
            else:
                rest.append(msg)
        if system_parts:
            return "\n\n".join(system_parts), rest
        return get_system_prompt(), rest

    def add_middleware(self, middleware: AgentMiddleware) -> None:
        """添加中间件
        
        Args:
            middleware: LangChain中间件
        """
        self.middlewares.append(middleware)


# 全局单例
_agent_service: Optional[AgentService] = None


async def get_agent_service() -> AgentService:
    """获取Agent服务单例"""
    global _agent_service
    if _agent_service is None:
        mcp_client = await get_mcp_client()
        
        # 默认启用日志中间件（装饰器式），方便调试
        default_middlewares = [
            *get_logging_middlewares(),
        ]
        
        _agent_service = AgentService(
            mcp_client=mcp_client,
            middlewares=default_middlewares
        )
        logger.info(f"Agent服务已初始化，已启用 {len(default_middlewares)} 个日志中间件")
    
    return _agent_service
