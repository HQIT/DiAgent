"""MCP客户端管理器 - 基于 langchain-mcp-adapters

使用 LangChain 官方的 MCP 适配器，直接加载标准格式配置
"""

import json
from typing import Dict, List, Any, Optional
from pathlib import Path
from loguru import logger

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.tools import BaseTool

from ..schemas.tool_types import ToolInfo


class MCPClientManager:
    """MCP客户端管理器
    
    基于 langchain-mcp-adapters 的 MultiServerMCPClient
    """
    
    def __init__(
        self,
        config_path: Optional[str] = None,
        server_configs: Optional[Dict[str, Any]] = None,
    ):
        self.config_path = config_path
        self._server_configs_inline = server_configs
        self._client: Optional[MultiServerMCPClient] = None
        self._tools: List[BaseTool] = []
        self._connected = False
        # 每个 server 的连接状态：{"name": {"status": "ok"|"failed", "tools": n, "error": str}}
        self.server_status: Dict[str, Dict[str, Any]] = {}
    
    async def connect_all(self) -> Dict[str, Dict[str, Any]]:
        """逐个连接 MCP 服务器，单个失败不影响其余。

        返回每个 server 的连接状态；全部失败也不抛异常。
        """
        if self._connected:
            return self.server_status

        server_configs = self._load_config()

        if not server_configs:
            logger.warning("没有配置任何MCP服务器")
            self._connected = True
            return self.server_status

        self._client = MultiServerMCPClient(server_configs)
        tools: List[BaseTool] = []
        status: Dict[str, Dict[str, Any]] = {}

        # 逐 server 连接：库的 get_tools() 内部是 asyncio.gather 不隔离异常，
        # 一个坏 server 会让整批失败，因此按 server_name 分别调用
        for name in server_configs:
            try:
                server_tools = await self._client.get_tools(server_name=name)
            except Exception as e:
                status[name] = {"status": "failed", "tools": 0, "error": f"{type(e).__name__}: {e}"}
                logger.error(f"mcp: server={name} status=failed error={type(e).__name__}: {e}")
            else:
                status[name] = {"status": "ok", "tools": len(server_tools)}
                logger.info(f"mcp: server={name} status=ok tools={len(server_tools)}")
                tools.extend(server_tools)

        self._tools = tools
        self._connected = True
        self.server_status = status

        ok_count = sum(1 for v in status.values() if v["status"] == "ok")
        if ok_count:
            logger.info(f"MCP客户端已连接，{ok_count}/{len(status)} 个 server 可用，共 {len(tools)} 个工具")
        else:
            logger.error(f"MCP: 全部 {len(status)} 个 server 连接失败，无 MCP 工具可用")
        return status
    
    def _load_config(self) -> Dict[str, Any]:
        """加载MCP配置：优先使用内联 server_configs，否则从 config_path 文件读取。"""
        if self._server_configs_inline is not None:
            logger.info(f"使用内联 MCP 配置，共 {len(self._server_configs_inline)} 个服务器")
            return self._server_configs_inline
        if not self.config_path:
            logger.warning("未指定MCP配置文件路径")
            return {}
        config_file = Path(self.config_path)
        if not config_file.exists():
            logger.warning(f"MCP配置文件不存在: {self.config_path}")
            return {}
        with open(config_file, "r", encoding="utf-8") as f:
            config = json.load(f)
        logger.info(f"加载了 {len(config)} 个MCP服务器配置")
        return config
    
    async def disconnect_all(self) -> None:
        """断开所有MCP服务器连接"""
        self._client = None
        self._tools = []
        self._connected = False
        self.server_status = {}
        logger.info("MCP客户端已断开")
    
    def get_tools(self) -> List[BaseTool]:
        """获取所有LangChain格式的工具"""
        return self._tools
    
    def get_tools_by_names(self, tool_names: Optional[List[str]] = None) -> List[BaseTool]:
        """根据工具名称列表获取工具"""
        if tool_names is None:
            return self._tools
        return [tool for tool in self._tools if tool.name in tool_names]
    
    def get_available_tools(self) -> List[ToolInfo]:
        """获取所有可用工具信息（供前端展示）"""
        return [
            ToolInfo(
                id=tool.name,
                name=tool.name,
                description=tool.description or "",
                server="mcp",
                parameters=tool.args_schema.model_json_schema() if tool.args_schema else {}
            )
            for tool in self._tools
        ]
    
    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected


# 全局单例
_mcp_client: Optional[MCPClientManager] = None


async def get_mcp_client() -> MCPClientManager:
    """获取MCP客户端单例"""
    global _mcp_client
    if _mcp_client is None:
        from ..config import get_settings
        settings = get_settings()
        _mcp_client = MCPClientManager(settings.mcp_config_path)
        await _mcp_client.connect_all()
    return _mcp_client
