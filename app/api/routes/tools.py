"""工具查询端点"""

from fastapi import APIRouter

from ...mcp.client import get_mcp_client

router = APIRouter(prefix="/v1", tags=["Tools"])


@router.get("/tools")
async def list_tools():
    """列出所有可用的 MCP 工具"""
    mcp = await get_mcp_client()
    tools_info = mcp.get_available_tools()
    return {
        "tools": [t.model_dump() for t in tools_info],
        "total": len(tools_info),
    }
