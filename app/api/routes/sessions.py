"""会话管理端点"""

from fastapi import APIRouter, HTTPException

from ...session.store import get_session_store

router = APIRouter(prefix="/v1", tags=["Sessions"])


@router.get("/sessions")
async def list_sessions():
    """列出所有活跃会话"""
    store = get_session_store()
    sessions = await store.list_sessions()
    return {"sessions": sessions}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取指定会话的消息历史"""
    store = get_session_store()
    messages = await store.get_messages(session_id)
    if not messages:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "messages": [m.model_dump(exclude_none=True) for m in messages],
    }


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除指定会话"""
    store = get_session_store()
    deleted = await store.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted", "session_id": session_id}
