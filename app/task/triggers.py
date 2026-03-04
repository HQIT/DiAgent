"""任务触发方式：立即一次、定时(cron)、周期(interval)。"""

import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger

from .config_schema import TaskConfig, load_task_config
from .runner import run_task


async def run_once(
    config: TaskConfig,
    output_dir: Optional[Path] = None,
) -> str:
    """立即执行一次任务并返回最终答案。"""
    logger.info("触发方式: once，执行一次后退出")
    return await run_task(config, output_dir=output_dir)


async def run_interval(
    config: TaskConfig,
    output_dir: Optional[Path] = None,
    interval_seconds: Optional[float] = None,
) -> None:
    """按固定间隔周期执行任务（永不退出，除非异常）。"""
    sec = interval_seconds if interval_seconds is not None else (config.trigger.interval_seconds or 60.0)
    logger.info("触发方式: interval，每 {} 秒执行一次", sec)
    while True:
        try:
            await run_task(config, output_dir=output_dir)
        except Exception as e:
            logger.exception("本次周期任务执行失败: {}", e)
        await asyncio.sleep(sec)


async def run_scheduled(
    config: TaskConfig,
    output_dir: Optional[Path] = None,
    cron: Optional[str] = None,
) -> None:
    """按 cron 表达式定时执行任务（永不退出，除非异常）。"""
    cron_expr = cron or config.trigger.cron
    if not cron_expr:
        raise ValueError("schedule 模式需要配置 trigger.cron 或传入 cron 参数")
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        raise ImportError("schedule 模式需要安装 apscheduler: pip install apscheduler")

    logger.info("触发方式: schedule，cron={}", cron_expr)
    out_dir = output_dir
    scheduler = AsyncIOScheduler()

    async def job() -> None:
        try:
            await run_task(config, output_dir=out_dir)
        except Exception as e:
            logger.exception("定时任务执行失败: {}", e)

    scheduler.add_job(job, CronTrigger.from_crontab(cron_expr), id="task")
    scheduler.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        scheduler.shutdown(wait=False)
