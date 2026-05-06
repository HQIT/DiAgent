"""通用事件发布工具：让 Agent 通过 DiOS 触发内部事件。"""

from __future__ import annotations

import json
import os
from fnmatch import fnmatch
from typing import Any
from urllib import error, request

from langchain_core.tools import tool


def _dios_base_url() -> str:
    # service 容器通常是 http://backend:8000；本地调试可退化到 localhost
    return (os.getenv("DIOS_API") or "http://backend:8000").rstrip("/")


def _http_json(method: str, path: str, payload: dict | None = None, timeout: int = 20) -> dict:
    base = _dios_base_url()
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{base}{path}",
        method=method,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _validate_event_type(event_type: str) -> tuple[bool, str]:
    catalog = _http_json("GET", "/api/os/events/catalog")
    allowed = {x.get("type", "") for x in (catalog.get("event_types") or [])}
    if event_type in allowed:
        return True, ""
    return False, f"event_type '{event_type}' is not in /events/catalog"


def _validate_source_and_event(source: str, event_type: str) -> tuple[bool, str]:
    patterns = _http_json("GET", "/api/os/connectors/source-patterns")
    matched = [p for p in patterns if fnmatch(source, p.get("source_pattern", ""))]
    if not matched:
        return False, f"source '{source}' not allowed by /connectors/source-patterns"
    allowed_types = {t for p in matched for t in (p.get("event_types") or [])}
    if event_type not in allowed_types:
        return False, f"event_type '{event_type}' not allowed for source '{source}'"
    return True, ""


@tool("publish_event", parse_docstring=True)
def publish_event_tool(
    event_type: str,
    source: str,
    subject: str = "",
    data: dict | None = None,
) -> str:
    """Publish an event to DiOS event gateway.

    This is a generic event emission mechanism for multi-agent collaboration.
    It validates event_type and source before publishing.

    Args:
        event_type: Event type, e.g. git.issue.opened / ai4r.topic.proposed.
        source: Event source string, must match allowed source patterns.
        subject: Optional subject.
        data: Optional event payload object.
    """
    try:
        ok, reason = _validate_event_type(event_type)
        if not ok:
            return f"[publish_event rejected] {reason}"
        ok, reason = _validate_source_and_event(source, event_type)
        if not ok:
            return f"[publish_event rejected] {reason}"

        payload = {
            "event_type": event_type,
            "source": source,
            "subject": subject or "",
            "data": data or {},
        }
        result = _http_json("POST", "/api/os/events/manual", payload=payload, timeout=30)
        return json.dumps(
            {
                "ok": True,
                "event_id": result.get("event_id"),
                "status": result.get("status"),
                "matched_agents": result.get("matched_agents"),
                "type": result.get("type"),
                "source": result.get("source"),
            },
            ensure_ascii=False,
        )
    except error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8")
        except Exception:
            detail = str(e)
        return f"[publish_event failed] HTTP {e.code}: {detail}"
    except Exception as e:
        return f"[publish_event failed] {type(e).__name__}: {e}"
