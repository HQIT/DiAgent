"""Ollama LLM适配器"""

from typing import List, Dict, Any, AsyncGenerator, Optional
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from .base import BaseLLMAdapter


class OllamaAdapter(BaseLLMAdapter):
    """Ollama适配器
    
    base_url 从 settings.llm.ollama_base_url 获取（通过 factory）
    """

    SUPPORTED_PARAMS = ("temperature", "top_p", "max_tokens", "stop")

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
            client_kwargs = dict(self.kwargs)
            if "max_tokens" in client_kwargs:
                # ChatOllama 无 max_tokens，对应参数为 num_predict
                client_kwargs["num_predict"] = client_kwargs.pop("max_tokens")
            self._client = ChatOllama(
                model=self.model_name,
                base_url=self.base_url,
                **client_kwargs
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
