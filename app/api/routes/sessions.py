"""会话占位 API（POC 暂不持久化）。"""

from fastapi import APIRouter

router = APIRouter(prefix="/v1", tags=["Sessions"])


@router.get("/sessions")
async def list_sessions():
    return {"sessions": [], "note": "POC 未启用会话持久化"}
