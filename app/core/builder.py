"""Agent 构建层：服务模式与任务模式共用的 create_deep_agent 构造入口。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langchain.agents.middleware import AgentMiddleware


@dataclass
class AgentProfile:
    """与入口无关的 agent 构建参数。

    model 传 LLM 客户端实例（llm.client），不传字符串，避免 deepagents
    无法从 "ecnu-max" 这类自定义名推断 provider。
    """

    model: Any
    workspace_root: Path
    tools: List[Any] = field(default_factory=list)
    system_prompt: str = ""
    skills_paths: List[str] = field(default_factory=list)
    subagents: Optional[List[Dict[str, Any]]] = None
    middlewares: List[AgentMiddleware] = field(default_factory=list)
    checkpointer: Optional[Any] = None

    def to_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "tools": self.tools,
            "system_prompt": self.system_prompt,
            "backend": FilesystemBackend(
                root_dir=str(self.workspace_root),
                virtual_mode=False,
            ),
            "skills": self.skills_paths,
        }
        if self.middlewares:
            kwargs["middleware"] = self.middlewares
        if self.subagents is not None:
            kwargs["subagents"] = self.subagents
        if self.checkpointer is not None:
            kwargs["checkpointer"] = self.checkpointer
        return kwargs


def build_agent(profile: AgentProfile):
    return create_deep_agent(**profile.to_kwargs())
