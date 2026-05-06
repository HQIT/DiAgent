"""会话存储 — 维护多轮对话上下文

默认内存存储，可选 Redis 持久化。
"""

import asyncio
import time
from typing import Optional
from collections import OrderedDict

from loguru import logger

from ..schemas.openai_types import ChatMessage


class SessionStore:
    """内存会话存储，带 TTL 和 LRU 淘汰"""

    def __init__(self, ttl: int = 86400, max_sessions: int = 200, max_messages: int = 50):
        self._ttl = ttl
        self._max_sessions = max_sessions
        self._max_messages = max_messages
        self._sessions: OrderedDict[str, dict] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get_messages(self, session_id: str) -> list[ChatMessage]:
        async with self._lock:
            entry = self._sessions.get(session_id)
            if entry is None:
                return []
            if time.time() - entry["last_access"] > self._ttl:
                self._sessions.pop(session_id, None)
                return []
            entry["last_access"] = time.time()
            self._sessions.move_to_end(session_id)
            return list(entry["messages"])

    async def append_messages(self, session_id: str, messages: list[ChatMessage]) -> None:
        async with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = {
                    "messages": [],
                    "created": time.time(),
                    "last_access": time.time(),
                }
            entry = self._sessions[session_id]
            entry["messages"].extend(messages)
            if len(entry["messages"]) > self._max_messages:
                entry["messages"] = entry["messages"][-self._max_messages:]
            entry["last_access"] = time.time()
            self._sessions.move_to_end(session_id)
            self._evict()

    async def delete_session(self, session_id: str) -> bool:
        async with self._lock:
            return self._sessions.pop(session_id, None) is not None

    async def list_sessions(self) -> list[dict]:
        async with self._lock:
            now = time.time()
            result = []
            for sid, entry in self._sessions.items():
                if now - entry["last_access"] <= self._ttl:
                    result.append({
                        "session_id": sid,
                        "message_count": len(entry["messages"]),
                        "created": entry["created"],
                        "last_access": entry["last_access"],
                    })
            return result

    def _evict(self) -> None:
        now = time.time()
        while self._sessions:
            sid, entry = next(iter(self._sessions.items()))
            if now - entry["last_access"] > self._ttl:
                self._sessions.pop(sid)
            else:
                break
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)


_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        from ..config import get_settings
        settings = get_settings()
        _store = SessionStore(
            ttl=settings.session_ttl,
            max_messages=settings.max_history_messages,
        )
    return _store
