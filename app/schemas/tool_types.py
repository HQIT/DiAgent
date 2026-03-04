"""工具相关模型"""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    """工具参数定义"""
    type: str
    description: Optional[str] = None
    enum: Optional[List[str]] = None
    default: Optional[Any] = None


class ToolInfo(BaseModel):
    """工具信息 - 用于前端展示"""
    id: str = Field(..., description="工具唯一ID")
    name: str = Field(..., description="工具名称")
    description: str = Field(..., description="工具描述")
    server: str = Field(..., description="所属MCP服务器")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="工具参数JSON Schema"
    )
    category: Optional[str] = Field(None, description="工具分类")
    enabled: bool = Field(True, description="是否可用")


class ToolCallResult(BaseModel):
    """工具调用结果"""
    tool_id: str
    tool_name: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: Optional[float] = None


class ToolListResponse(BaseModel):
    """工具列表响应"""
    tools: List[ToolInfo]
    total: int
    categories: List[str] = Field(default_factory=list)
