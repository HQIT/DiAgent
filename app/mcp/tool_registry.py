"""工具注册表 - 管理LangChain工具

基于 langchain-mcp-adapters，MCP工具已自动转换为LangChain工具
此模块提供额外的工具管理和自定义工具注册功能
"""

import hashlib
from typing import List, Dict, Optional, Callable, Any

import httpx
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel
from loguru import logger

from .client import MCPClientManager
from ..config import get_settings


# 瞬态异常（超时/连接类）：重试可能成功，返回可重试标记；其余向上抛
_TRANSIENT_EXC_TYPES: tuple = (TimeoutError, ConnectionError)


def _is_transient_error(e: BaseException) -> bool:
    """判断异常是否属于瞬态错误（超时、连接、限流、5xx）。"""
    if isinstance(e, _TRANSIENT_EXC_TYPES):
        return True
    # httpx 的超时/传输异常不从内建 TimeoutError/ConnectionError 继承
    if isinstance(e, (httpx.TimeoutException, httpx.TransportError)):
        return True
    # 自定义工具直接抛 httpx.HTTPStatusError / openai 异常时状态码的挂载位置
    status = getattr(e, "status_code", None)
    if status is None:
        response = getattr(e, "response", None)
        status = getattr(response, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _args_digest(kwargs: Dict[str, Any]) -> str:
    """参数摘要（哈希），日志不落参数明文。"""
    raw = repr(sorted(kwargs.items(), key=lambda kv: str(kv[0])))
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()[:12]


def _sanitize_detail(e: BaseException) -> str:
    """给模型看的错误摘要：异常类名 + 消息，不含 traceback。"""
    msg = str(e)
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


def wrap_tool_with_fallback(tool: BaseTool) -> BaseTool:
    """包装工具：瞬态错误返回可重试文本，其余异常向上抛（TOOL_ERROR_SWALLOW=1 恢复旧行为）。"""
    _inner = tool

    class _ToolWithErrorSemantics(BaseTool):
        name: str = _inner.name
        description: str = (_inner.description or "") + " (瞬态错误返回可重试标记。)"
        args_schema: type = _inner.args_schema

        def _handle_error(self, kwargs: Dict[str, Any], e: BaseException) -> Optional[str]:
            swallow = get_settings().tool_error_swallow
            transient = _is_transient_error(e)
            logger.warning(
                "Tool {} 执行失败(tool_error, args_digest={}, transient={}, swallow={}): {}",
                _inner.name, _args_digest(kwargs), transient, swallow, _sanitize_detail(e),
            )
            if swallow:
                return f"[Tool execution failed] {_sanitize_detail(e)}"
            if transient:
                return f"[Tool error, retryable] {_sanitize_detail(e)}"
            return None  # 向上抛

        def _run(self, **kwargs: Any) -> str:
            try:
                return _inner.invoke(kwargs)
            except Exception as e:
                handled = self._handle_error(kwargs, e)
                if handled is not None:
                    return handled
                raise

        async def _arun(self, **kwargs: Any) -> str:
            try:
                return await _inner.ainvoke(kwargs)
            except Exception as e:
                handled = self._handle_error(kwargs, e)
                if handled is not None:
                    return handled
                raise

    return _ToolWithErrorSemantics()


def wrap_tools_with_fallback(tools: List[BaseTool]) -> List[BaseTool]:
    """对工具列表中的每个工具做容错包装。"""
    return [wrap_tool_with_fallback(t) for t in tools]


class ToolRegistry:
    """工具注册表
    
    管理MCP工具和自定义工具
    """
    
    def __init__(self, mcp_client: MCPClientManager):
        self.mcp_client = mcp_client
        self._custom_tools: Dict[str, BaseTool] = {}
    
    def get_langchain_tools(
        self, 
        tool_names: Optional[List[str]] = None
    ) -> List[BaseTool]:
        """获取LangChain工具列表
        
        Args:
            tool_names: 工具名称列表，None表示所有工具
            
        Returns:
            LangChain工具列表
        """
        # 获取MCP工具
        mcp_tools = self.mcp_client.get_tools_by_names(tool_names)
        
        # 获取自定义工具
        if tool_names is None:
            custom_tools = list(self._custom_tools.values())
        else:
            custom_tools = [
                self._custom_tools[name] 
                for name in tool_names 
                if name in self._custom_tools
            ]
        
        return mcp_tools + custom_tools
    
    def get_all_tool_names(self) -> List[str]:
        """获取所有工具名称"""
        mcp_names = [tool.name for tool in self.mcp_client.get_tools()]
        custom_names = list(self._custom_tools.keys())
        return mcp_names + custom_names
    
    def register_custom_tool(
        self,
        name: str,
        func: Callable,
        description: str,
        args_schema: Optional[type[BaseModel]] = None
    ) -> None:
        """注册自定义工具（非MCP）
        
        Args:
            name: 工具名称
            func: 工具函数
            description: 工具描述
            args_schema: 参数Schema
        """
        tool = StructuredTool.from_function(
            func=func,
            name=name,
            description=description,
            args_schema=args_schema
        )
        self._custom_tools[name] = tool
        logger.info(f"注册自定义工具: {name}")
    
    def unregister_custom_tool(self, name: str) -> bool:
        """注销自定义工具
        
        Args:
            name: 工具名称
            
        Returns:
            是否成功注销
        """
        if name in self._custom_tools:
            del self._custom_tools[name]
            logger.info(f"注销自定义工具: {name}")
            return True
        return False
