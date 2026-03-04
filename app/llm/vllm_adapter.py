"""vLLM LLM适配器
使用OpenAI兼容接口连接vLLM
"""

from typing import List, Dict, Any, AsyncGenerator, Optional
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from .base import BaseLLMAdapter


class VLLMAdapter(BaseLLMAdapter):
    """vLLM适配器 - 使用OpenAI兼容API
    
    base_url 从 settings.llm.vllm_base_url 获取（通过 factory）
    """
    
    def __init__(
        self, 
        model_name: str, 
        base_url: str = None,  # 由 factory 从配置注入
        api_key: str = "EMPTY",  # vLLM不需要真实API key
        **kwargs
    ):
        super().__init__(model_name, **kwargs)
        self.base_url = base_url or "http://localhost:8000/v1"
        self.api_key = api_key
        self._client = None
    
    @property
    def client(self) -> BaseChatModel:
        if self._client is None:
            self._client = ChatOpenAI(
                model=self.model_name,
                openai_api_base=self.base_url,
                openai_api_key=self.api_key,
                **self.kwargs
            )
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
