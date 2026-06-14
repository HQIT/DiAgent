"""文件上传工具：将 workspace 中的文件上传到 SeaweedFS S3 并发送到群聊。

依赖基础设施层通过 contextvar 隐式传递群聊上下文（group_id / bot_uid），
Agent/LLM 不接触这些信息。
"""

from __future__ import annotations

import contextvars
import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib import request, error

from langchain_core.tools import tool

_BRIDGE_URL = os.getenv("IM_BRIDGE_UPLOAD_URL", "http://im-bridge:8100/upload")

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# 请求级群聊上下文，由 agent.py 在每次请求时设置
current_group_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "upload_group_id", default=""
)
current_bot_uid: contextvars.ContextVar[str] = contextvars.ContextVar(
    "upload_bot_uid", default=""
)


def _format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


@tool("upload_file", parse_docstring=True)
def upload_file_tool(path: str) -> str:
    """Upload a file from the workspace and send it to the group chat as a file card.

    Call this after generating files (PPTX, PDF, images, etc.).
    The file will appear in the group chat as a clickable card — no need to
    return a download URL in your reply.

    Args:
        path: Absolute path to the file, e.g. /workspace/什么是Agent.pptx.
    """
    try:
        file_path = Path(path)
        if not file_path.exists():
            return f"[upload_file failed] file not found: {path}"
        if not file_path.is_file():
            return f"[upload_file failed] not a regular file: {path}"

        data = file_path.read_bytes()
        if len(data) > MAX_FILE_SIZE:
            return f"[upload_file failed] file too large: {_format_size(len(data))} (max {_format_size(MAX_FILE_SIZE)})"

        content_type, _ = mimetypes.guess_type(file_path.name)
        if not content_type:
            content_type = "application/octet-stream"

        payload = {
            "file_content": base64.b64encode(data).decode("utf-8"),
            "file_name": file_path.name,
            "content_type": content_type,
            "sender_user_id": current_bot_uid.get(),
            "group_id": current_group_id.get(),
        }
        req = request.Request(
            _BRIDGE_URL,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        status = result.get("status", "ok")
        if status == "sent":
            return f"已发送: {file_path.name} ({_format_size(len(data))})"
        if result.get("url"):
            return result["url"]
        return f"[upload_file failed] unexpected response: {json.dumps(result)}"

    except error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        return f"[upload_file failed] HTTP {e.code}: {detail}"
    except Exception as e:
        return f"[upload_file failed] {type(e).__name__}: {e}"
