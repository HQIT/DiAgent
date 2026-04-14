"""配置管理"""

from typing import Optional, Dict, Any, List
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
import yaml
from pathlib import Path


class Settings(BaseSettings):
    """应用配置
    
    所有配置从 .env 文件读取，使用扁平化结构确保正确加载
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
    
    # 应用配置
    app_name: str = "DiAgent"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    
    # 会话配置
    session_ttl: int = Field(default=3600 * 24, alias="SESSION_TTL")
    max_history_messages: int = Field(default=50, alias="MAX_HISTORY_MESSAGES")
    
    # LLM 配置
    llm_default_model: str = Field(default="qwen2.5-14b", alias="LLM_DEFAULT_MODEL")
    llm_models_config_path: str = Field(default="configs/models.yaml", alias="LLM_MODELS_CONFIG_PATH")
    llm_openai_api_key: Optional[str] = Field(default=None, alias="LLM_OPENAI_API_KEY")
    
    # Redis 配置
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_db: int = Field(default=0, alias="REDIS_DB")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")
    
    # MCP 配置
    mcp_config_path: str = Field(default="configs/mcp_servers.json", alias="MCP_CONFIG_PATH")
    
    # Agent 配置（LangGraph 递归上限）
    agent_recursion_limit: int = Field(default=100, alias="AGENT_RECURSION_LIMIT")
    
    # Agent 系统提示词（可通过环境变量注入，覆盖默认提示词）
    agent_system_prompt: Optional[str] = Field(default=None, alias="AGENT_SYSTEM_PROMPT")
    
    # Agent 工作区根目录（backend 根、skills 所在目录；相对路径相对项目根解析，也可填绝对路径）
    agent_workspace: str = Field(default="workspace", alias="AGENT_WORKSPACE")
    
    # Skills 配置（为 agent_workspace 下的子目录名，即 skills 放在 workspace/skills 下）
    skills_dir: str = Field(default="skills", alias="SKILLS_DIR")
    skills_max_file_size: int = Field(default=1024 * 1024, alias="SKILLS_MAX_FILE_SIZE")  # 1MB

    @computed_field
    @property
    def redis_url(self) -> str:
        """Redis 连接 URL"""
        if self.redis_password:
            return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


# 模型配置缓存
_models_config: Optional[Dict[str, Any]] = None


def get_models_config() -> Dict[str, Any]:
    """获取模型配置
    
    Returns:
        模型配置字典，格式: {"model_string": {"base_url": ..., "display_name": ..., ...}}
    """
    global _models_config
    
    if _models_config is not None:
        return _models_config
    
    settings = get_settings()
    config_path = Path(settings.llm_models_config_path)
    
    if not config_path.exists():
        return {}
    
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    _models_config = data.get("models", {})
    return _models_config


def get_model_config(model_string: str) -> Dict[str, Any]:
    """获取指定模型的配置
    
    Args:
        model_string: 模型字符串，如 "ollama:qwen2.5:14b"
        
    Returns:
        模型配置，如果未配置返回空字典
    """
    models = get_models_config()
    return models.get(model_string, {})


def reload_models_config():
    """重新加载模型配置（用于配置热更新）"""
    global _models_config
    _models_config = None
    get_models_config()
