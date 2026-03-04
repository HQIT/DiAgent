"""自定义中间件

基于 LangChain v1 装饰器式中间件
参考: https://langchain-doc.cn/v1/python/langchain/releases/langchain-v1.html
"""

from typing import Callable, List, Optional, Dict, Any
import time
from loguru import logger

# 导入 LangChain v1 中间件装饰器和类型
from langchain.agents.middleware import (
    before_model,
    after_model
)
from langchain.agents.middleware import AgentState, ModelRequest, ModelResponse


# ============================================================
# 日志中间件 - 使用装饰器方式
# ============================================================

@before_model
def log_before_model(state: AgentState, runtime) -> Dict[str, Any] | None:
    """模型调用前 - 记录消息数和可用工具"""
    msg_count = len(state.get('messages', []))
    logger.info(f"🚀 [模型调用] 消息数: {msg_count}")
    
    # 打印最新消息
    if msg_count > 0:
        last_msg = state.get('messages', [])[-1]
        if hasattr(last_msg, 'content') and last_msg.content:
            content = last_msg.content
            content_preview = content[:100] + "..." if len(content) > 100 else content
            logger.info(f"   最新消息: {content_preview}")
    
    return None


@after_model()
def log_after_model(state: AgentState, runtime) -> Dict[str, Any] | None:
    """模型调用后 - 记录模型决策"""
    messages = state.get('messages', [])
    if not messages:
        return None
    
    last_msg = messages[-1]
    
    # 检查是否有工具调用
    if hasattr(last_msg, 'tool_calls') and last_msg.tool_calls:
        tool_names = [tc.get('name', tc.name if hasattr(tc, 'name') else 'unknown') 
                      for tc in last_msg.tool_calls]
        logger.info(f"🔧 [模型决策] 调用工具: {tool_names}")
    elif hasattr(last_msg, 'content') and last_msg.content:
        content = last_msg.content
        content_preview = (content[:80] + "...") if len(content) > 80 else content
        logger.info(f"💬 [模型响应] {content_preview}")
    
    return None


# ============================================================
# 组合中间件列表 - 供外部使用
# ============================================================

# 日志中间件列表
logging_middlewares = [
    log_before_model,
    log_after_model
]


def get_logging_middlewares() -> List:
    """获取日志中间件列表"""
    return logging_middlewares.copy()