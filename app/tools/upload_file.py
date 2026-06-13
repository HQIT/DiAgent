"""文件上传工具：将 workspace 中的文件上传到 SeaweedFS S3，返回可下载 URL。"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib import request, error

from langchain_core.tools import tool

_BRIDGE_URL = os.getenv("IM_BRIDGE_UPLOAD_URL", "http://im-bridge:8100/upload")


@tool("upload_file", parse_docstring=True)
def upload_file_tool(path: str) -> str:
    """Upload a file from the agent workspace to But-You storage and return a download URL.

    Use this after generating files (PPTX, PDF, images, etc.) so users in group
    chat can download them.

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
        content_type, _ = mimetypes.guess_type(file_path.name)
        if not content_type:
            content_type = "application/octet-stream"

        payload = {
            "file_content": base64.b64encode(data).decode("utf-8"),
            "file_name": file_path.name,
            "content_type": content_type,
        }
        req = request.Request(
            _BRIDGE_URL,
            method="POST",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        url = result.get("url", "")
        if not url:
            return f"[upload_file failed] no url returned: {json.dumps(result)}"
        return url

    except error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        return f"[upload_file failed] HTTP {e.code}: {detail}"
    except Exception as e:
        return f"[upload_file failed] {type(e).__name__}: {e}"
