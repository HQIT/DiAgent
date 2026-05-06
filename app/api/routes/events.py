"""接收 DiOS 投递的 CloudEvents 事件"""

import uuid
from typing import Any, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException
from loguru import logger

from ...core.agent import get_agent_service, get_system_prompt
from ...schemas.extended_request import ExtendedChatRequest
from ...schemas.openai_types import ChatMessage
from ...config import get_settings

router = APIRouter(prefix="/v1", tags=["Events"])


class CloudEvent(BaseModel):
    specversion: str = "1.0"
    id: str
    source: str
    type: str
    subject: Optional[str] = None
    time: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)


def _event_to_user_message(event: CloudEvent) -> str:
    """将 CloudEvent 转为供 Agent 理解的 user message"""
    import json
    lines = [
        f"[事件通知] 类型: {event.type}",
        f"来源: {event.source}",
    ]
    if event.subject:
        lines.append(f"主题: {event.subject}")
    if event.time:
        lines.append(f"时间: {event.time}")
    lines.append(f"数据:\n```json\n{json.dumps(event.data, ensure_ascii=False, indent=2)}\n```")
    return "\n".join(lines)


@router.post("/events")
async def receive_event(event: CloudEvent):
    """接收 DiOS 投递的事件，交给 Agent 处理"""
    logger.info(f"收到事件: type={event.type}, source={event.source}, id={event.id}")

    settings = get_settings()
    agent_service = await get_agent_service()

    user_content = _event_to_user_message(event)

    request = ExtendedChatRequest(
        model=settings.llm_default_model,
        messages=[
            ChatMessage(role="user", content=user_content),
        ],
        stream=False,
    )

    try:
        result = await agent_service.chat(request)
        content = result.choices[0].message.content if result.choices else ""
        logger.info(f"事件处理完成: event_id={event.id}, response_len={len(content)}")
        return {
            "status": "processed",
            "event_id": event.id,
            "response": content,
        }
    except Exception as e:
        logger.error(f"事件处理失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
