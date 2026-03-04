"""请求预处理器"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from loguru import logger

from ..schemas.extended_request import ExtendedChatRequest
from ..schemas.openai_types import ChatMessage


@dataclass
class ProcessedRequest:
    """预处理后的请求"""
    model: str
    messages: List[ChatMessage]
    temperature: float
    max_tokens: Optional[int]
    stream: bool
    
    # 从扩展字段提取
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    selected_tool_ids: List[str] = field(default_factory=list)
    user_context: Dict[str, Any] = field(default_factory=dict)
    custom_fields: Dict[str, Any] = field(default_factory=dict)
    middleware_config: Dict[str, Any] = field(default_factory=dict)


class RequestPreprocessor:
    """请求预处理器
    
    将扩展请求转换为标准化的内部格式
    """
    
    def process(self, request: ExtendedChatRequest) -> ProcessedRequest:
        """预处理请求
        
        Args:
            request: 扩展请求
            
        Returns:
            预处理后的请求
        """
        # 验证消息
        self._validate_messages(request.messages)
        
        # 提取扩展字段
        selected_tool_ids = request.get_selected_tool_ids()
        
        middleware_config = {}
        if request.middleware_config:
            middleware_config = {
                "enabled": request.middleware_config.enabled_middlewares or [],
                "options": request.middleware_config.middleware_options or {}
            }
        
        # 从 user_context 提取 user_id（如果存在）
        user_id = request.user_id
        if not user_id and request.user_context:
            user_id = request.user_context.get("user_id")
        
        processed = ProcessedRequest(
            model=request.model,
            messages=request.messages,
            temperature=request.temperature or 0.7,
            max_tokens=request.max_tokens,
            stream=request.stream or False,
            session_id=request.session_id,
            user_id=user_id,
            selected_tool_ids=selected_tool_ids,
            user_context=request.user_context or {},
            custom_fields=request.custom_fields or {},
            middleware_config=middleware_config
        )
        
        logger.debug(f"预处理完成: model={processed.model}, "
                    f"tools={len(selected_tool_ids)}, "
                    f"session={processed.session_id}")
        
        return processed
    
    def _validate_messages(self, messages: List[ChatMessage]) -> None:
        """验证消息格式
        
        Args:
            messages: 消息列表
        """
        if not messages:
            raise ValueError("消息列表不能为空")
        
        valid_roles = {"system", "user", "assistant", "tool"}
        for msg in messages:
            if msg.role not in valid_roles:
                raise ValueError(f"无效的消息角色: {msg.role}")
