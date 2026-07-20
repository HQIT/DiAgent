"""Chat Completions API（含 SSE 流式 Thought / Tool 事件）。"""

from __future__ import annotations

from typing import AsyncGenerator, Union

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from loguru import logger

from ...core.agent import get_agent_service
from ...schemas.extended_request import ExtendedChatRequest
from ...schemas.openai_types import ChatCompletionResponse

router = APIRouter(prefix="/v1", tags=["Chat"])


@router.post("/chat/completions")
async def chat_completions(request: ExtendedChatRequest):
    """OpenAI 兼容聊天接口；stream=true 时返回 SSE。"""
    try:
        service = await get_agent_service()
        result = await service.chat(request)

        if request.stream:
            async def event_stream() -> AsyncGenerator[str, None]:
                async for chunk in result:  # type: ignore[union-attr]
                    yield chunk

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        assert isinstance(result, ChatCompletionResponse)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("chat_completions failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
