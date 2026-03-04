"""OpenAI LLM适配器"""

from typing import List, Dict, Any, AsyncGenerator, Optional
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .base import BaseLLMAdapter


class OpenAIAdapter(BaseLLMAdapter):
    """OpenAI适配器"""
    
    def __init__(
        self, 
        model_name: str, 
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        super().__init__(model_name, **kwargs)
        self.api_key = api_key
        self.base_url = base_url
        self._client = None
    
    @property
    def client(self) -> BaseChatModel:
        if self._client is None:
            init_kwargs = {"model": self.model_name, **self.kwargs}
            if self.api_key:
                init_kwargs["openai_api_key"] = self.api_key
            if self.base_url:
                init_kwargs["openai_api_base"] = self.base_url
            self._client = ChatOpenAI(**init_kwargs)
            # 供 LangChain/deepagents 推断 provider 使用（Pydantic 禁止任意 setattr，用 object.__setattr__）
            object.__setattr__(self._client, "model_provider", "openai")
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
