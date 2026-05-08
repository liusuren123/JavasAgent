"""平台适配层包。"""

from __future__ import annotations

import platform
import sys

from loguru import logger

from src.platforms.base import PlatformAdapter


def create_platform_adapter(config: "AppConfig | None" = None) -> PlatformAdapter | None:
    """根据当前平台自动选择并创建适配器。

    Args:
        config: 应用配置，用于获取平台相关参数。

    Returns:
        对应平台的适配器实例，无法识别时返回 None。
    """
    system = platform.system()

    if system == "Windows":
        from src.platforms.windows import WindowsAdapter

        action_delay = config.platform.action_delay if config else 0.5
        adapter = WindowsAdapter(action_delay=action_delay)
        logger.info(f"已创建 Windows 平台适配器 (delay={action_delay})")
        return adapter
    else:
        logger.warning(f"不支持的平台: {system}，屏幕操作将不可用")
        return None
