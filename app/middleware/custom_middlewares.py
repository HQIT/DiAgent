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
    after_model,
    wrap_model_call,
)
from langchain.agents.middleware import AgentState, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage


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
# 系统消息合并中间件
# ------------------------------------------------------------
# deepagents 的 middleware 栈（TodoList / Skills / Filesystem / SubAgent
# / Summarization / AnthropicPromptCaching ...）会在 messages 前面追加
# 多条 SystemMessage，并且把 content 写成 list[dict]（Anthropic 格式）。
#
# OpenAI 官方 API 能吃下这两种情况，但很多国产 / 自建的 OpenAI 兼容网关
# （ECNU、部分 vLLM 部署等）只认单条 system + str content，遇到多条或
# list content 会直接返回 500。
#
# 本 middleware 在发给 LLM 之前把 messages 里所有 SystemMessage 合并成
# 一条、content 拍平成 str。官方 issue #974 maintainer 推荐的做法。
# ============================================================


def _content_to_str(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text" and "text" in block:
                    parts.append(str(block["text"]))
                elif "text" in block:
                    parts.append(str(block["text"]))
            else:
                parts.append(str(block))
        return "\n\n".join(p for p in parts if p)
    return str(content)


def _do_merge(messages, system_message=None):
    system_texts: List[str] = []
    rest = []
    for m in messages:
        if isinstance(m, SystemMessage):
            t = _content_to_str(m.content)
            if t:
                system_texts.append(t)
        else:
            rest.append(m)

    if system_message is not None:
        t = _content_to_str(getattr(system_message, "content", ""))
        if t:
            system_texts.append(t)

    merged_system = SystemMessage(content="\n\n".join(system_texts)) if system_texts else None
    return rest, merged_system


@wrap_model_call
async def merge_system_messages(request: ModelRequest, handler) -> ModelResponse:
    """把 request.messages + request.system_message 中的 system 合并成一条。"""
    rest_messages, merged_system = _do_merge(request.messages, request.system_message)
    new_req = request.override(messages=rest_messages, system_message=merged_system)
    return await handler(new_req)


# ============================================================
# 组合中间件列表 - 供外部使用
# ============================================================

logging_middlewares = [
    log_before_model,
    log_after_model,
]


def get_logging_middlewares() -> List:
    """获取日志中间件 + system message 合并兼容中间件。"""
    return [*logging_middlewares, merge_system_messages]