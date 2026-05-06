"""DiAgent 内置 shell 工具：在容器内执行 bash 命令。

威胁模型：依赖 DiAgent 容器本身作为 sandbox。不做命令白名单、不做注入检查。
仅保留工程性防御：超时 + 输出截尾。
"""

from __future__ import annotations

import subprocess

from langchain_core.tools import tool


@tool("shell", parse_docstring=True)
def shell_tool(command: str, cwd: str | None = None, timeout: int = 300) -> str:
    """Execute a bash command inside the agent container.

    Returns exit_code plus truncated stdout/stderr. Environment variables
    (including DIOS-injected credentials like GIT_PLATFORM_TOKEN) are
    inherited automatically. Use for git / curl / shell scripts.

    Args:
        command: Bash command. Supports '&&', ';', '|', multiline.
        cwd: Working directory. Defaults to /workspace.
        timeout: Per-command timeout in seconds. Default 300, max 1800.
    """
    try:
        r = subprocess.run(
            ["bash", "-lc", command],
            cwd=cwd or "/workspace",
            capture_output=True,
            text=True,
            timeout=min(max(timeout, 1), 1800),
            check=False,
        )
        return (
            f"exit_code: {r.returncode}\n"
            f"stdout:\n{r.stdout[:32000]}\n"
            f"stderr:\n{r.stderr[:8000]}"
        )
    except subprocess.TimeoutExpired:
        return f"exit_code: -1\nstdout:\n\nstderr:\ncommand timed out after {timeout}s"
    except Exception as e:
        return f"exit_code: -1\nstdout:\n\nstderr:\n{type(e).__name__}: {e}"
