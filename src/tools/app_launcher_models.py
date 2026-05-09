"""应用启动器数据模型。

包含 AppLauncher 使用的应用信息数据类。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AppInfo:
    """应用信息。"""

    name: str
    path: str
    icon_path: str | None = None
    version: str | None = None
    is_running: bool = False
    pid: int | None = None


@dataclass
class LaunchResult:
    """启动结果。"""

    success: bool
    app_name: str = ""
    pid: int | None = None
    path: str = ""
    error: str = ""
    already_running: bool = False
    brought_to_front: bool = False
