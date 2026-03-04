"""Ollama LLM适配器"""

from typing import List, Dict, Any, AsyncGenerator, Optional
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from .base import BaseLLMAdapter


class OllamaAdapter(BaseLLMAdapter):
    """Ollama适配器
    
    base_url 从 settings.llm.ollama_base_url 获取（通过 factory）
    """
    
    def __init__(
        self, 
        model_name: str, 
        base_url: str = None,  # 由 factory 从配置注入
        **kwargs
    ):
        super().__init__(model_name, **kwargs)
        self.base_url = base_url or "http://localhost:11434"
        self._client = None
    
    @property
    def client(self) -> BaseChatModel:
        if self._client is None:
            self._client = ChatOllama(
                model=self.model_name,
                base_url=self.base_url,
                **self.kwargs
            )
            object.__setattr__(self._client, "model_provider", "ollama")
        return self._client
    
    async def invoke(
        self, 
        messages: List[Dict[str, Any]], 
        **kwargs
    ) -> str:
        lc_messages = self._convert_messages(messages)
        response = await self.client.ainvoke(lc_messages, **kwargs)
        return response.content
    
    async def stream(
        self, 
        messages: List[Dict[str, Any]], 
        **kwargs
    ) -> AsyncGenerator[str, None]:
        lc_messages = self._convert_messages(messages)
        async for chunk in self.client.astream(lc_messages, **kwargs):
            if chunk.content:
                yield chunk.content
