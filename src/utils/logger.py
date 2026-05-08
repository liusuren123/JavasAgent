"""日志模块。

基于 loguru 的结构化日志，支持文件轮转和控制台输出。
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logger(log_level: str = "INFO", log_path: str | None = None) -> None:
    """初始化日志系统。

    Args:
        log_level: 日志级别（DEBUG/INFO/WARNING/ERROR）
        log_path: 日志文件目录，为 None 则只输出到控制台
    """
    logger.remove()

    # 控制台输出 - 带颜色的简洁格式
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<7}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )

    # 文件输出 - 详细格式 + 轮转
    if log_path:
        log_dir = Path(log_path)
        log_dir.mkdir(parents=True, exist_ok=True)

        logger.add(
            str(log_dir / "javas_{time:YYYY-MM-DD}.log"),
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<7} | {name}:{function}:{line} - {message}",
            rotation="00:00",  # 每天轮转
            retention="30 days",
            compression="gz",
            encoding="utf-8",
        )


def get_logger(name: str = "javas"):
    """获取命名的 logger实例。"""
    return logger.bind(name=name)
