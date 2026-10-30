"""任务模式 SQLite checkpointer。"""

import hashlib
import re
from contextlib import asynccontextmanager
from pathlib import Path

from loguru import logger

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_SAFE_THREAD_ID = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_thread_id(thread_id: str) -> str:
    """thread_id 会成为文件名的一部分：不安全字符折叠后追加原值哈希，避免不同 id 清洗后碰撞。"""
    raw = (thread_id or "").strip() or "thread"
    cleaned = _SAFE_THREAD_ID.sub("_", raw)
    return f"{cleaned[:64]}_{hashlib.sha1(raw.encode('utf-8', 'ignore')).hexdigest()[:8]}"


@asynccontextmanager
async def sqlite_task_saver(workspace_root: Path, thread_id: str):
    """落盘到 <workspace>/.checkpoints/<thread_id>.sqlite，同一 thread_id 重跑可从断点继续。"""
    tid = sanitize_thread_id(thread_id)
    ckpt_dir = Path(workspace_root) / ".checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    db_path = ckpt_dir / f"{tid}.sqlite"
    logger.info("任务 checkpoint 启用: thread_id={} db={}", tid, db_path)
    async with AsyncSqliteSaver.from_conn_string(str(db_path)) as saver:
        yield saver
