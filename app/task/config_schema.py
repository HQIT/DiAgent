"""任务配置 Schema：输入、输出、触发、skills、MCP、subagents。"""

import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

import yaml
from pydantic import BaseModel, Field, field_validator


class TaskOutputConfig(BaseModel):
    """任务输出配置：log 与 result 文件路径。"""

    log_file: str = Field(
        default="task.log",
        description="执行过程 log 文件路径（含 tool 调用、模型 I/O），相对工作目录或绝对路径",
    )
    result_file: str = Field(
        default="task_result.txt",
        description="最终答案输出文件路径",
    )


class TaskTriggerConfig(BaseModel):
    """触发方式配置。"""

    mode: Literal["once", "schedule", "interval"] = Field(
        default="once",
        description="once=立即执行一次并退出; schedule=cron 定时; interval=周期执行",
    )
    cron: Optional[str] = Field(
        default=None,
        description="mode=schedule 时使用，cron 表达式，如 '0 9 * * *' 表示每天 9 点",
    )
    interval_seconds: Optional[float] = Field(
        default=None,
        description="mode=interval 时使用，每隔多少秒执行一次",
    )


class SubagentSpec(BaseModel):
    """Subagent 配置项（与主 task 对齐：任务说明、system_prompt、tools、MCP、skills 等）。"""

    name: str = Field(description="Subagent 名称")
    description: str = Field(description="供主 agent 选择是否调用的描述")
    prompt: str = Field(description="Subagent 系统提示词（即 system_prompt）")
    tools: List[str] = Field(
        default_factory=list,
        description="该 subagent 可用的工具名列表，空/null 表示与主 agent 一致或使用其 MCP 全部工具",
    )

    @field_validator("tools", mode="before")
    @classmethod
    def _tools_none_to_list(cls, v: Any) -> List[str]:
        if v is None:
            return []
        return list(v) if not isinstance(v, list) else v
    model: Optional[str] = Field(default=None, description="该 subagent 使用的模型，空表示与主 agent 一致")
    task: Optional[str] = Field(default=None, description="可选：子任务说明模板，主 agent 调用时可传入具体任务")
    # 单独 MCP：不填则使用主 task 的 MCP 与 tools 过滤；填则使用该配置文件中的工具（相对 workspace）
    mcp_config_path: Optional[str] = Field(default=None, description="该 subagent 的 MCP 配置文件路径，空表示与主 task 一致")
    # 单独 skills：不填则与主 task 一致；填则只使用该 subagent 的 skills 目录/列表
    skills_dir: Optional[str] = Field(default=None, description="该 subagent 的 skills 子目录名，空表示与主 task 一致")
    skill_names: Optional[List[str]] = Field(default=None, description="该 subagent 只启用这些 skill，空表示与主 task 一致或全部")


class TaskConfig(BaseModel):
    """单次任务的完整配置（可由 YAML/JSON 文件加载）。"""

    # --- 输入 ---
    task: str = Field(description="用户要执行的任务描述（作为唯一一条 user 消息传给 agent）")
    model: Optional[str] = Field(
        default=None,
        description="使用的模型，如 'ollama:qwen2.5:14b'，空则用 app 默认",
    )
    temperature: float = Field(default=0.7, ge=0, le=2)

    # Agent 系统提示词（不设则用默认 get_system_prompt()）
    system_prompt: Optional[str] = Field(
        default=None,
        description="Agent 的 system prompt，不填则使用默认助理提示词",
    )

    # 工作区与 skills：workspace 由 compose 挂载传入（如 /workspace），其下放 skills、mcp 等
    workspace: str = Field(default="workspace", description="工作区根目录（容器内如 /workspace），其下含 skills_dir、mcp 配置等")
    skills_dir: str = Field(default="skills", description="skills 在 workspace 下的子目录名，即 workspace/skills/")
    skill_names: Optional[List[str]] = Field(
        default=None,
        description="可选：只启用这些 skill 子目录，空表示启用 workspace/skills 下全部",
    )

    # MCP：配置文件路径（相对 workspace 或绝对路径），如 workspace 下的 mcp_servers.json
    mcp_config_path: Optional[str] = Field(
        default=None,
        description="MCP 配置文件路径（JSON），相对 workspace 根或绝对路径；空则用 app.MCP_CONFIG_PATH",
    )

    # 工具：仅启用列出的工具名（MCP 工具名等），空/不填表示使用全部可用工具
    tools: Optional[List[str]] = Field(
        default=None,
        description="可选：只启用这些工具名（如 MCP 工具），空表示启用全部",
    )

    # Subagents
    subagents: Optional[List[SubagentSpec]] = Field(
        default=None,
        description="可选的 subagent 列表，供主 agent 按需调用",
    )

    # --- 输出 ---
    output: TaskOutputConfig = Field(default_factory=TaskOutputConfig)
    output_dir: Optional[str] = Field(
        default=None,
        description="产出物根目录（log、result 等均在此下）。相对 workspace 解析，或绝对路径；不填则用环境变量 OUTPUT_DIR，再否则当前工作目录",
    )

    # --- 触发（任务模式入口根据此决定执行方式）---
    trigger: TaskTriggerConfig = Field(default_factory=TaskTriggerConfig)

    # 其他
    recursion_limit: int = Field(default=100, ge=1, description="Agent 递归/步数上限")
    task_user_id: Optional[str] = Field(
        default="task",
        description="任务模式下的虚拟 user_id，用于工作目录映射",
    )


def _load_raw_config(path: Union[str, Path]) -> Dict[str, Any]:
    """从 YAML 或 JSON 文件加载原始字典。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    raw = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        return yaml.safe_load(raw) or {}
    import json
    return json.loads(raw)


def load_task_config(path: Union[str, Path]) -> TaskConfig:
    """从 YAML 或 JSON 文件加载任务配置（仅 task 部分或整文件即 task）。"""
    p = Path(path)
    data = _load_raw_config(p)
    return load_task_config_from_dict(data, p)


def load_task_config_from_dict(data: Dict[str, Any], config_path: Optional[Path] = None) -> TaskConfig:
    """
    从字典加载 TaskConfig，支持统一配置文件格式：
    - 若存在顶层的 "task" 键，则以其为任务配置。
    - 若不存在 "task"，则整份 data 当作 TaskConfig。
    config_path: 用于解析相对路径（如 mcp_config_path），可选。
    """
    if "task" in data:
        task_data = dict(data["task"])
        # 若 task.model 未指定，尝试从 app.LLM_DEFAULT_MODEL 或 models.default_model 获取
        if task_data.get("model") is None:
            if "app" in data and data["app"].get("LLM_DEFAULT_MODEL"):
                task_data["model"] = data["app"]["LLM_DEFAULT_MODEL"]
            elif "models" in data and data["models"].get("default_model"):
                task_data["model"] = data["models"]["default_model"]
        return TaskConfig.model_validate(task_data)
    return TaskConfig.model_validate(data)


def load_unified_config(path: Union[str, Path]) -> TaskConfig:
    """
    加载统一配置文件：单文件内包含 app、task 等。
    等价于 load_task_config，但明确语义为「统一配置」。
    """
    return load_task_config(path)


def _apply_models_config(data: Dict[str, Any]) -> None:
    """若配置中有 models 段，写入临时文件并设置 LLM_MODELS_CONFIG_PATH、LLM_DEFAULT_MODEL。"""
    models_block = data.get("models")
    if not models_block or not isinstance(models_block, dict):
        return
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="agent_models_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(models_block, f, allow_unicode=True, default_flow_style=False)
        os.environ["LLM_MODELS_CONFIG_PATH"] = path
        if models_block.get("default_model"):
            os.environ["LLM_DEFAULT_MODEL"] = str(models_block["default_model"])
    except Exception:
        os.close(fd)
        raise


def apply_app_config(data: Dict[str, Any]) -> None:
    """
    将配置中的 app、models 注入进程：
    - app 段写入 os.environ，供 get_settings() 读取；API key 在 config 的 app.LLM_OPENAI_API_KEY 中配置。
    - 若有 models 段，写入临时 YAML 并设置 LLM_MODELS_CONFIG_PATH（及 default_model）。
    - 将 LLM_OPENAI_API_KEY 同步到 OPENAI_API_KEY，供依赖该变量的库使用；未配置时注入占位避免报错。
    """
    app = data.get("app")
    if app and isinstance(app, dict):
        for k, v in app.items():
            if v is None:
                continue
            os.environ[k] = str(v)
    _apply_models_config(data)
    if os.environ.get("LLM_OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = os.environ["LLM_OPENAI_API_KEY"]
    elif not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "not-needed"


def load_task_config_and_apply_app(path: Union[str, Path]) -> TaskConfig:
    """
    加载统一配置文件：先应用 app 段到进程环境，再解析并返回 TaskConfig。
    任务模式入口用此函数，配置全部以该 config 文件为准。
    """
    p = Path(path)
    data = _load_raw_config(p)
    apply_app_config(data)
    return load_task_config_from_dict(data, p)
