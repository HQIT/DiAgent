"""扩展请求模型 - 包含个性化字段"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from .openai_types import ChatMessage


class ToolSelection(BaseModel):
    """工具选择配置"""
    tool_ids: List[str] = Field(default_factory=list, description="选择的工具ID列表")
    tool_config: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None, 
        description="工具特定配置，key为tool_id"
    )


class MiddlewareConfig(BaseModel):
    """中间件配置"""
    enabled_middlewares: Optional[List[str]] = None
    middleware_options: Optional[Dict[str, Dict[str, Any]]] = None


class ExtendedChatRequest(BaseModel):
    """扩展的OpenAI Chat请求格式
    
    继承标准OpenAI字段，并添加个性化扩展字段
    """
    # === 标准OpenAI字段 ===
    model: str = Field(..., description="模型名称，如 ollama:qwen2.5:14b")
    messages: List[ChatMessage] = Field(..., description="消息列表")
    temperature: Optional[float] = Field(0.7, ge=0, le=2)
    top_p: Optional[float] = Field(1.0, ge=0, le=1)
    max_tokens: Optional[int] = Field(None, ge=1)
    stream: Optional[bool] = Field(False, description="是否流式输出")
    stop: Optional[List[str]] = None
    
    # === 扩展字段 ===
    session_id: Optional[str] = Field(
        None, 
        description="会话ID"
    )
    
    user_id: Optional[str] = Field(
        None,
        description="用户ID，用于标识用户"
    )
    
    tool_selection: Optional[ToolSelection] = Field(
        None,
        description="前端选择的工具配置"
    )
    
    middleware_config: Optional[MiddlewareConfig] = Field(
        None,
        description="中间件配置"
    )
    
    # 用户上下文
    user_context: Optional[Dict[str, Any]] = Field(
        None,
        description="用户上下文信息，如用户ID、权限等"
    )
    
    # 自定义扩展字段
    custom_fields: Optional[Dict[str, Any]] = Field(
        None,
        description="其他自定义扩展字段"
    )
    
    def to_standard_request(self) -> Dict[str, Any]:
        """转换为标准OpenAI请求格式"""
        return {
            "model": self.model,
            "messages": [msg.model_dump(exclude_none=True) for msg in self.messages],
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stream": self.stream,
            "stop": self.stop,
        }
    
    def get_selected_tool_ids(self) -> List[str]:
        """获取选择的工具ID列表"""
        if self.tool_selection:
            return self.tool_selection.tool_ids
        return []
