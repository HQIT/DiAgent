"""响应格式化器 - 转换为OpenAI标准格式

支持流式输出工具调用状态
"""

from typing import AsyncGenerator, Optional, Dict, Any, Literal
from dataclasses import dataclass
import json
import time
import uuid


def _json_safe(obj: Any) -> Any:
    """递归过滤，只保留可 JSON 序列化的值；ToolRuntime 等不可序列化字段直接丢弃，不输出"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            try:
                cleaned = _json_safe(v)
                out[k] = cleaned
            except (TypeError, ValueError):
                continue
        return out
    if isinstance(obj, (list, tuple)):
        out = []
        for x in obj:
            try:
                out.append(_json_safe(x))
            except (TypeError, ValueError):
                continue
        return out
    raise TypeError(f"不可序列化类型: {type(obj).__name__}")


from ..schemas.openai_types import (
    ChatCompletionResponse,
    ChatCompletionChunk,
    ChatMessage,
    Choice,
    ChunkChoice,
    DeltaMessage,
    Usage
)


@dataclass
class ToolCallEvent:
    """工具调用事件"""
    event_type: Literal["tool_call_start", "tool_call_end", "tool_call_error"]
    tool_call_id: str
    tool_name: str
    arguments: Optional[Dict[str, Any]] = None
    result: Optional[str] = None
    error: Optional[str] = None


class ResponseFormatter:
    """响应格式化器
    
    将Agent输出转换为OpenAI标准格式
    支持流式输出工具调用状态
    """
    
    def __init__(self, model: str):
        self.model = model
        self._chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        self._created = int(time.time())
        self._tool_call_index = 0
    
    # ============================================================
    # 内部辅助方法 - 用于流式输出
    # ============================================================
    
    def _format_role_chunk(self) -> str:
        """格式化角色信息块"""
        chunk = ChatCompletionChunk(
            id=self._chunk_id,
            created=self._created,
            model=self.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(role="assistant"),
                    finish_reason=None
                )
            ]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    
    def _format_content_chunk(self, content: str) -> str:
        """格式化内容块"""
        chunk = ChatCompletionChunk(
            id=self._chunk_id,
            created=self._created,
            model=self.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(content=content),
                    finish_reason=None
                )
            ]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    
    def _format_reasoning_content_chunk(self, reasoning_content: str) -> str:
        """格式化推理内容块（工具调用前的思考）"""
        chunk = ChatCompletionChunk(
            id=self._chunk_id,
            created=self._created,
            model=self.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(reasoning_content=reasoning_content),
                    finish_reason=None
                )
            ]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    
    def _format_finish_chunk(self) -> str:
        """格式化结束块"""
        chunk = ChatCompletionChunk(
            id=self._chunk_id,
            created=self._created,
            model=self.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(),
                    finish_reason="stop"
                )
            ]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    
    def format_response(
        self,
        content: str,
        usage: Optional[Dict[str, int]] = None
    ) -> ChatCompletionResponse:
        """格式化非流式响应
        
        Args:
            content: 响应内容
            usage: Token使用统计
            
        Returns:
            OpenAI格式响应
        """
        return ChatCompletionResponse(
            model=self.model,
            choices=[
                Choice(
                    index=0,
                    message=ChatMessage(
                        role="assistant",
                        content=content
                    ),
                    finish_reason="stop"
                )
            ],
            usage=Usage(**(usage or {})) if usage else None
        )
    
    async def format_stream(
        self,
        content_generator: AsyncGenerator[str, None]
    ) -> AsyncGenerator[str, None]:
        """格式化流式响应为SSE
        
        Args:
            content_generator: 内容生成器
            
        Yields:
            SSE格式的响应块
        """
        created = int(time.time())
        
        # 发送角色信息
        first_chunk = ChatCompletionChunk(
            id=self._chunk_id,
            created=created,
            model=self.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(role="assistant"),
                    finish_reason=None
                )
            ]
        )
        yield f"data: {first_chunk.model_dump_json()}\n\n"
        
        # 发送内容块
        async for content in content_generator:
            if content:
                chunk = ChatCompletionChunk(
                    id=self._chunk_id,
                    created=created,
                    model=self.model,
                    choices=[
                        ChunkChoice(
                            index=0,
                            delta=DeltaMessage(content=content),
                            finish_reason=None
                        )
                    ]
                )
                yield f"data: {chunk.model_dump_json()}\n\n"
        
        # 发送结束标记
        final_chunk = ChatCompletionChunk(
            id=self._chunk_id,
            created=created,
            model=self.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(),
                    finish_reason="stop"
                )
            ]
        )
        yield f"data: {final_chunk.model_dump_json()}\n\n"
        yield "data: [DONE]\n\n"
    
    def format_tool_call_chunk(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: str
    ) -> str:
        """格式化工具调用块
        
        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            arguments: 工具参数JSON字符串
            
        Returns:
            SSE格式字符串
        """
        chunk = ChatCompletionChunk(
            id=self._chunk_id,
            created=int(time.time()),
            model=self.model,
            choices=[
                ChunkChoice(
                    index=0,
                    delta=DeltaMessage(
                        tool_calls=[{
                            "index": 0,
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": arguments
                            }
                        }]
                    ),
                    finish_reason=None
                )
            ]
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    
    def format_error(self, error: str, code: str = "internal_error") -> Dict[str, Any]:
        """格式化错误响应
        
        Args:
            error: 错误信息
            code: 错误代码
            
        Returns:
            错误响应字典
        """
        return {
            "error": {
                "message": error,
                "type": "error",
                "code": code
            }
        }
    
    # ============================================================
    # 工具调用流式事件
    # ============================================================
    
    def format_tool_call_start(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> str:
        """格式化工具调用开始事件
        
        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            SSE格式字符串
        """
        event_data = {
            "type": "tool_call_start",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": _json_safe(arguments) if arguments is not None else {},
            "timestamp": time.time()
        }
        return f"event: tool_call\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    
    def format_tool_call_end(
        self,
        tool_call_id: str,
        tool_name: str,
        result: str,
        duration_ms: float = None
    ) -> str:
        """格式化工具调用结束事件
        
        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            result: 工具返回结果
            duration_ms: 工具调用耗时（毫秒）
            
        Returns:
            SSE格式字符串
        """
        event_data = {
            "type": "tool_call_end",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "result": result,
            "timestamp": time.time()
        }
        if duration_ms is not None:
            event_data["duration_ms"] = round(duration_ms, 2)
        return f"event: tool_call\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    
    def format_tool_call_error(
        self,
        tool_call_id: str,
        tool_name: str,
        error: str
    ) -> str:
        """格式化工具调用错误事件
        
        Args:
            tool_call_id: 工具调用ID
            tool_name: 工具名称
            error: 错误信息
            
        Returns:
            SSE格式字符串
        """
        event_data = {
            "type": "tool_call_error",
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "error": error,
            "timestamp": time.time()
        }
        return f"event: tool_call\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    
    def format_thinking_status(self, status: str) -> str:
        """格式化思考状态（可选）
        
        Args:
            status: 状态描述
            
        Returns:
            SSE格式字符串
        """
        event_data = {
            "type": "status",
            "message": status,
            "timestamp": time.time()
        }
        return f"event: status\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    
    def format_reasoning_chunk(self, content: str) -> str:
        """格式化推理过程块
        
        当模型正在进行工具调用时，输出的内容作为reasoning
        
        Args:
            content: 推理内容
            
        Returns:
            SSE格式字符串
        """
        event_data = {
            "type": "reasoning",
            "content": content,
            "timestamp": time.time()
        }
        return f"event: reasoning\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    
    def format_reasoning_start(self) -> str:
        """格式化推理开始事件"""
        event_data = {
            "type": "reasoning_start",
            "timestamp": time.time()
        }
        return f"event: reasoning\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
    
    def format_reasoning_end(self) -> str:
        """格式化推理结束事件"""
        event_data = {
            "type": "reasoning_end",
            "timestamp": time.time()
        }
        return f"event: reasoning\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
