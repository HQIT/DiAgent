"""OpenAI 兼容的 Chat Completions 端点"""

import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from ...schemas.extended_request import ExtendedChatRequest
from ...schemas.openai_types import ChatMessage
from ...core.agent import get_agent_service
from ...session.store import get_session_store

router = APIRouter(prefix="/v1", tags=["Chat"])


@router.post("/chat/completions")
async def chat_completions(request: ExtendedChatRequest):
    """OpenAI 兼容的聊天补全 API

    支持 session_id 维护多轮对话上下文。
    """
    session_id = request.session_id
    store = get_session_store()

    messages = list(request.messages)

    if session_id:
        history = await store.get_messages(session_id)
        if history:
            system_msgs = [m for m in messages if m.role == "system"]
            user_msgs = [m for m in messages if m.role != "system"]
            messages = system_msgs + history + user_msgs

    agent_service = await get_agent_service()

    patched = request.model_copy(update={"messages": messages})

    try:
        result = await agent_service.chat(patched)
    except Exception as e:
        logger.error(f"chat 失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    if request.stream:
        async def _stream_and_save():
            collected: list[str] = []
            async for chunk in result:
                if chunk.startswith("data: ") and not chunk.startswith("data: [DONE]"):
                    import json as _json
                    try:
                        payload = _json.loads(chunk[len("data: "):])
                        delta_content = (
                            payload.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content")
                        )
                        if delta_content:
                            collected.append(delta_content)
                    except (_json.JSONDecodeError, IndexError, KeyError):
                        pass
                yield chunk

            if session_id:
                user_msg = next(
                    (m for m in reversed(request.messages) if m.role == "user"),
                    None,
                )
                save_msgs: list[ChatMessage] = []
                if user_msg:
                    save_msgs.append(user_msg)
                if collected:
                    save_msgs.append(
                        ChatMessage(role="assistant", content="".join(collected))
                    )
                if save_msgs:
                    await store.append_messages(session_id, save_msgs)

        return StreamingResponse(
            _stream_and_save(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        if session_id:
            user_msg = next(
                (m for m in reversed(request.messages) if m.role == "user"),
                None,
            )
            save_msgs: list[ChatMessage] = []
            if user_msg:
                save_msgs.append(user_msg)
            assistant_content = (
                result.choices[0].message.content if result.choices else ""
            )
            if assistant_content:
                save_msgs.append(
                    ChatMessage(role="assistant", content=assistant_content)
                )
            if save_msgs:
                await store.append_messages(session_id, save_msgs)
        return result
