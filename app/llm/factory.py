"""LLM工厂 - 根据配置创建对应的LLM适配器"""

from typing import Optional, Dict, Any
from functools import lru_cache

from .base import BaseLLMAdapter
from .ollama_adapter import OllamaAdapter
from .vllm_adapter import VLLMAdapter
from .openai_adapter import OpenAIAdapter
from ..config import get_settings, get_model_config


class LLMFactory:
    """LLM工厂类"""
    
    # 支持的提供商
    PROVIDERS = {
        "ollama": OllamaAdapter,
        "vllm": VLLMAdapter,
        "openai": OpenAIAdapter,
    }
    
    @classmethod
    def create(
        cls,
        model_id: str,
        **kwargs
    ) -> BaseLLMAdapter:
        """根据模型ID创建LLM适配器
        
        Args:
            model_id: 模型标识，如 "qwen2.5-14b", "gpt-4o"
                     对应 models.yaml 中的 key
            **kwargs: 传递给适配器的额外参数（会覆盖配置文件中的值）
            
        Returns:
            对应的LLM适配器实例
            
        Raises:
            ValueError: 模型未配置或缺少必要配置
        """
        settings = get_settings()
        
        # 获取模型配置（从 models.yaml）
        model_config = get_model_config(model_id)
        
        if not model_config:
            raise ValueError(
                f"模型未配置: {model_id}. "
                f"请在 models.yaml 中添加该模型配置"
            )
        
        # 获取 provider（必须）
        provider = model_config.get("provider")
        if not provider:
            raise ValueError(
                f"模型 {model_id} 缺少 provider 配置"
            )
        provider = provider.lower()
        
        # 检查提供商是否支持
        if provider not in cls.PROVIDERS:
            raise ValueError(
                f"不支持的LLM提供商: {provider}. "
                f"支持的提供商: {list(cls.PROVIDERS.keys())}"
            )
        
        # 获取实际模型名（必须）
        model_name = model_config.get("model")
        if not model_name:
            raise ValueError(
                f"模型 {model_id} 缺少 model 配置"
            )
        
        # 获取 base_url（必须）
        if "base_url" not in kwargs:
            base_url = model_config.get("base_url")
            if not base_url:
                raise ValueError(
                    f"模型 {model_id} 缺少 base_url 配置"
                )
            kwargs["base_url"] = base_url
        
        # 获取 api_key（如果有）
        if "api_key" not in kwargs:
            api_key = model_config.get("api_key") or settings.llm_openai_api_key
            if api_key:
                kwargs["api_key"] = api_key

        # 透传部分供应商特定参数，例如 OpenAI 兼容接口的 extra_body。
        if "extra_body" not in kwargs:
            extra_body = model_config.get("extra_body")
            if extra_body is not None:
                kwargs["extra_body"] = extra_body

        if "reasoning_effort" not in kwargs:
            reasoning_effort = model_config.get("reasoning_effort")
            if reasoning_effort is not None:
                kwargs["reasoning_effort"] = reasoning_effort
        
        # 创建适配器
        adapter_class = cls.PROVIDERS[provider]
        return adapter_class(model_name=model_name, **kwargs)
    
    @classmethod
    def register_provider(
        cls, 
        name: str, 
        adapter_class: type
    ):
        """注册新的LLM提供商
        
        Args:
            name: 提供商名称
            adapter_class: 适配器类
        """
        cls.PROVIDERS[name.lower()] = adapter_class


def get_llm(model_string: str, **kwargs) -> BaseLLMAdapter:
    """便捷函数 - 获取LLM适配器
    
    Args:
        model_string: 模型字符串，格式 "provider:model_name"
        **kwargs: 额外参数
        
    Returns:
        LLM适配器实例
    """
    return LLMFactory.create(model_string, **kwargs)
