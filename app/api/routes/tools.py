"""工具列表 API。"""

from fastapi import APIRouter

from ...mcp.client import get_mcp_client

router = APIRouter(prefix="/v1", tags=["Tools"])


@router.get("/tools")
async def list_tools():
    client = await get_mcp_client()
    tools = client.get_available_tools()
    return {
        "tools": [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "server": t.server,
            }
            for t in tools
        ]
    }
