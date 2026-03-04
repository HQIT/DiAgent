"""任务模式：以配置文件驱动的一次性/定时/周期任务执行。

- 输入：任务描述、可用的 skills、MCP 配置、可选的 subagents
- 输出：执行 log 文件（含 tool 调用过程）、结果文件（最终答案）
- 触发：立即一次 / 定时(cron) / 周期(interval)
"""

from .config_schema import (
    TaskConfig,
    TaskOutputConfig,
    TaskTriggerConfig,
    load_task_config,
    load_unified_config,
)
from .runner import TaskRunner, run_task
from .triggers import run_once, run_scheduled, run_interval

__all__ = [
    "TaskConfig",
    "TaskOutputConfig",
    "TaskTriggerConfig",
    "load_task_config",
    "load_unified_config",
    "TaskRunner",
    "run_task",
    "run_once",
    "run_scheduled",
    "run_interval",
]
