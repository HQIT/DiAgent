"""LLM适配器基类"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncGenerator, Optional
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage


class BaseLLMAdapter(ABC):
    """LLM适配器基类
    
    统一不同LLM提供商的接口
    """
    
    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.kwargs = kwargs
        self._client: Optional[BaseChatModel] = None
    
    @property
    @abstractmethod
    def client(self) -> BaseChatModel:
        """获取LangChain ChatModel客户端"""
        pass
    
    @abstractmethod
    async def invoke(
        self, 
        messages: List[Dict[str, Any]], 
        **kwargs
    ) -> str:
        """非流式调用
        
        Args:
            messages: OpenAI格式的消息列表
            **kwargs: 其他参数
            
        Returns:
            模型响应文本
        """
        pass
    
    @abstractmethod
    async def stream(
        self, 
        messages: List[Dict[str, Any]], 
        **kwargs
    ) -> AsyncGenerator[str, None]:
        """流式调用
        
        Args:
            messages: OpenAI格式的消息列表
            **kwargs: 其他参数
            
        Yields:
            响应文本片段
        """
        pass
    
    def bind_tools(self, tools: List[Any]) -> "BaseLLMAdapter":
        """绑定工具
        
        Args:
            tools: 工具列表
            
        Returns:
            绑定工具后的适配器
        """
        if self._client and hasattr(self._client, 'bind_tools'):
            self._client = self._client.bind_tools(tools)
        return self
    
    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[BaseMessage]:
        """将OpenAI格式消息转换为LangChain消息"""
        from langchain_core.messages import (
            HumanMessage, 
            AIMessage, 
            SystemMessage,
            ToolMessage
        )
        
        result = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            
            if role == "system":
                result.append(SystemMessage(content=content))
            elif role == "user":
                result.append(HumanMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(
                    content=content,
                    tool_calls=msg.get("tool_calls") or []
                ))
            elif role == "tool":
                result.append(ToolMessage(
                    content=content,
                    tool_call_id=msg.get("tool_call_id", "")
                ))
        
        return result
