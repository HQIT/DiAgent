"""通用对话上下文压缩（framework-level）。

策略：当消息数或字符数超过阈值时，将较早的非 system 消息折叠为一条摘要，
保留最近若干条原文。不做业务语义推断；应用层可在 custom_fields 覆盖开关。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from ..schemas.openai_types import ChatMessage


def _content_len(msg: ChatMessage) -> int:
    return len(msg.content or "")


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _estimate_chars(messages: List[ChatMessage]) -> int:
    return sum(_content_len(m) for m in messages)


def _build_extractive_summary(
    older: List[ChatMessage],
    *,
    max_summary_chars: int,
    line_clip: int = 240,
) -> str:
    lines: List[str] = [
        "【历史对话压缩】以下为较早轮次的摘录，细节以近期消息为准：",
    ]
    for msg in older:
        role = msg.role
        body = _clip(msg.content or "", line_clip)
        if not body:
            continue
        lines.append(f"- [{role}] {body}")
    summary = "\n".join(lines)
    if len(summary) > max_summary_chars:
        summary = summary[: max_summary_chars - 1] + "…"
    return summary


def compact_messages(
    messages: List[ChatMessage],
    *,
    enabled: bool = True,
    max_messages: int = 20,
    keep_recent: int = 8,
    max_chars: int = 24000,
    max_summary_chars: int = 4000,
) -> Tuple[List[ChatMessage], Optional[Dict[str, Any]]]:
    """按阈值压缩消息列表。

    Returns:
        (messages, meta)；未触发压缩时 meta 为 None。
    """
    if not enabled or not messages:
        return messages, None

    keep_recent = max(2, int(keep_recent))
    max_messages = max(keep_recent + 1, int(max_messages))
    max_chars = max(1000, int(max_chars))
    max_summary_chars = max(200, int(max_summary_chars))

    total_chars = _estimate_chars(messages)
    over_count = len(messages) > max_messages
    over_chars = total_chars > max_chars
    if not over_count and not over_chars:
        return messages, None

    systems = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]
    if len(non_system) <= keep_recent:
        return messages, None

    older = non_system[:-keep_recent]
    recent = non_system[-keep_recent:]
    summary_text = _build_extractive_summary(
        older, max_summary_chars=max_summary_chars
    )
    summary_msg = ChatMessage(role="user", content=summary_text)
    out = systems + [summary_msg] + recent

    meta = {
        "compacted": True,
        "strategy": "extractive",
        "before_messages": len(messages),
        "after_messages": len(out),
        "older_folded": len(older),
        "before_chars": total_chars,
        "after_chars": _estimate_chars(out),
        "trigger": "messages" if over_count else "chars",
    }
    logger.info(
        "context compact: {before}→{after} msgs, folded={folded}, trigger={trigger}",
        before=meta["before_messages"],
        after=meta["after_messages"],
        folded=meta["older_folded"],
        trigger=meta["trigger"],
    )
    return out, meta


def resolve_compact_options(
    settings: Any,
    custom_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """合并全局配置与请求 custom_fields.context_compact。"""
    opts: Dict[str, Any] = {
        "enabled": bool(getattr(settings, "context_compact_enabled", True)),
        "max_messages": int(getattr(settings, "context_compact_max_messages", 20)),
        "keep_recent": int(getattr(settings, "context_compact_keep_recent", 8)),
        "max_chars": int(getattr(settings, "context_compact_max_chars", 24000)),
        "max_summary_chars": int(
            getattr(settings, "context_compact_max_summary_chars", 4000)
        ),
    }
    cf = custom_fields or {}
    override = cf.get("context_compact")
    if isinstance(override, dict):
        for key in opts:
            if key in override and override[key] is not None:
                opts[key] = override[key]
    return opts
