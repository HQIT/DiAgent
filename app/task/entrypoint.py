"""任务模式入口：仅从统一配置文件读取配置（不依赖 .env），按触发方式执行任务。

唯一需要的环境变量（或 compose 传入）：
- TASK_CONFIG: 统一配置文件路径（YAML/JSON），必填；配置内含 app、models、task 等

触发方式以 task.trigger 为准（在 agent-task.yaml 的 task.trigger.mode / cron / interval_seconds 配置）。
可选环境变量覆盖：OUTPUT_DIR、TRIGGER_MODE、CRON、INTERVAL_SECONDS。
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from .config_schema import load_task_config_and_apply_app
from .runner import _resolve_workspace_root
from .triggers import run_once, run_scheduled, run_interval


def _get_config_path() -> Path:
    path = os.environ.get("TASK_CONFIG")
    if not path:
        logger.error("未设置 TASK_CONFIG 环境变量（任务配置文件路径）")
        sys.exit(2)
    return Path(path)


def _get_output_dir(config) -> Optional[Path]:
    """产出目录：优先环境变量 OUTPUT_DIR，否则配置中的 task.output_dir（相对 workspace），再否则 None。"""
    path = os.environ.get("OUTPUT_DIR")
    if path:
        return Path(path).resolve()
    if getattr(config, "output_dir", None) and str(config.output_dir).strip():
        raw = str(config.output_dir).strip()
        p = Path(raw)
        if p.is_absolute():
            return p.resolve()
        workspace_root = _resolve_workspace_root(config.workspace)
        return (workspace_root / raw).resolve()
    return None


def main() -> None:
    config_path = _get_config_path()
    if not config_path.exists():
        logger.error("任务配置文件不存在: {}", config_path)
        sys.exit(2)

    # 从统一配置加载并应用 app 段到进程，再得到 TaskConfig（配置全以此文件为准）
    config = load_task_config_and_apply_app(config_path)
    output_dir = _get_output_dir(config)

    # 环境变量覆盖触发方式
    mode = os.environ.get("TRIGGER_MODE", config.trigger.mode)
    if mode not in ("once", "schedule", "interval"):
        logger.error("无效的 TRIGGER_MODE: {}，应为 once | schedule | interval", mode)
        sys.exit(2)

    async def _run() -> None:
        if mode == "once":
            await run_once(config, output_dir=output_dir)
            return
        if mode == "interval":
            sec = os.environ.get("INTERVAL_SECONDS")
            interval = float(sec) if sec else config.trigger.interval_seconds
            if not interval:
                logger.error("interval 模式需要配置 trigger.interval_seconds 或环境变量 INTERVAL_SECONDS")
                sys.exit(2)
            await run_interval(config, output_dir=output_dir, interval_seconds=interval)
            return
        if mode == "schedule":
            cron = os.environ.get("CRON") or config.trigger.cron
            if not cron:
                logger.error("schedule 模式需要配置 trigger.cron 或环境变量 CRON")
                sys.exit(2)
            await run_scheduled(config, output_dir=output_dir, cron=cron)
            return

    asyncio.run(_run())


if __name__ == "__main__":
    main()
