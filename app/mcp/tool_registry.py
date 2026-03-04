"""工具注册表 - 管理LangChain工具

基于 langchain-mcp-adapters，MCP工具已自动转换为LangChain工具
此模块提供额外的工具管理和自定义工具注册功能
"""

from typing import List, Dict, Optional, Callable, Any
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel
from loguru import logger

from .client import MCPClientManager


def wrap_tool_with_fallback(tool: BaseTool) -> BaseTool:
    """包装工具：执行失败时返回错误信息字符串而非抛出，便于 agent 继续执行。"""
    _inner = tool

    class _ToolWithFallback(BaseTool):
        name: str = _inner.name
        description: str = (_inner.description or "") + " (执行失败时返回错误信息，不中断任务。)"
        args_schema: type = _inner.args_schema

        def _run(self, **kwargs: Any) -> str:
            try:
                return _inner.invoke(kwargs)
            except Exception as e:
                logger.warning("Tool {} 执行失败: {}", _inner.name, e)
                return f"[Tool execution failed] {type(e).__name__}: {e}"

        async def _arun(self, **kwargs: Any) -> str:
            try:
                return await _inner.ainvoke(kwargs)
            except Exception as e:
                logger.warning("Tool {} 执行失败: {}", _inner.name, e)
                return f"[Tool execution failed] {type(e).__name__}: {e}"

    return _ToolWithFallback()


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
