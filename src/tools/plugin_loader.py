"""插件动态加载与实例化。

提供模块的动态加载、卸载、以及安装源处理（Git 克隆、本地复制）。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from src.tools.plugin_models import PluginInfo


# ------------------------------------------------------------------
# 模块加载 / 卸载
# ------------------------------------------------------------------


def load_module(info: PluginInfo) -> Any:
    """使用 importlib 动态加载插件模块。

    支持两种 entry_point 格式：
    1. 文件名: "main.py" → 加载 main.py
    2. 模块路径: "mymodule.plugin" → 加载 mymodule/plugin.py

    Args:
        info: 插件运行时信息

    Returns:
        加载后的模块对象

    Raises:
        FileNotFoundError: 入口文件不存在
        ImportError: 无法创建模块规格
    """
    plugin_dir = Path(info.install_path)
    entry_point = info.manifest.entry_point

    if entry_point.endswith(".py"):
        module_file = plugin_dir / entry_point
    else:
        module_file = plugin_dir / entry_point.replace(".", "/") / "__init__.py"
        if not module_file.exists():
            module_file = plugin_dir / (entry_point.replace(".", "/") + ".py")

    if not module_file.exists():
        raise FileNotFoundError(f"入口文件不存在: {module_file}")

    module_name = f"plugins.{info.plugin_id}.{entry_point.rstrip('.py')}"

    # 如果模块已加载，先从 sys.modules 移除以实现重载
    if module_name in sys.modules:
        del sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, str(module_file))
    if spec is None or spec.loader is None:
        raise ImportError(f"无法创建模块规格: {module_file}")

    # 将插件目录加入 sys.path，确保插件内部 import 正常
    plugin_dir_str = str(plugin_dir)
    if plugin_dir_str not in sys.path:
        sys.path.insert(0, plugin_dir_str)

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    logger.debug(f"加载插件模块: {module_name}")
    return module


def unload_module(info: PluginInfo) -> None:
    """卸载插件模块。

    Args:
        info: 插件运行时信息
    """
    entry_point = info.manifest.entry_point
    module_name = f"plugins.{info.plugin_id}.{entry_point.rstrip('.py')}"
    sys.modules.pop(module_name, None)
    info.loaded_module = None
    logger.debug(f"卸载插件模块: {module_name}")


# ------------------------------------------------------------------
# 安装源处理
# ------------------------------------------------------------------


async def clone_from_git(
    git_url: str,
    plugins_dir: Path,
    plugin_id: str | None = None,
) -> Path | None:
    """从 Git URL 克隆插件。

    Args:
        git_url: Git 仓库 URL
        plugins_dir: 插件安装根目录
        plugin_id: 可选的插件 ID（用于目标目录名）

    Returns:
        克隆后的插件目录路径，失败返回 None
    """
    plugins_dir.mkdir(parents=True, exist_ok=True)
    target = plugins_dir / (plugin_id or Path(git_url).stem.replace(".git", ""))

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", git_url, str(target)],
            capture_output=True, text=True, timeout=120, check=True,
        )
        # 移除 .git 目录以节省空间
        git_dir = target / ".git"
        if git_dir.exists():
            shutil.rmtree(git_dir, ignore_errors=True)
        logger.info(f"从 Git 克隆插件到: {target}")
        return target
    except Exception as e:
        logger.error(f"Git 克隆失败: {e}")
        return None


async def copy_from_local(
    source: str,
    plugins_dir: Path,
) -> Path | None:
    """从本地路径复制插件。

    Args:
        source: 源目录路径
        plugins_dir: 插件安装根目录

    Returns:
        复制后的插件目录路径，失败返回 None
    """
    src = Path(source).resolve()
    if not src.is_dir():
        logger.error(f"源路径不是目录: {src}")
        return None

    plugins_dir.mkdir(parents=True, exist_ok=True)
    target = plugins_dir / src.name

    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    try:
        shutil.copytree(src, target)
        logger.info(f"从本地复制插件到: {target}")
        return target
    except Exception as e:
        logger.error(f"复制插件失败: {e}")
        return None
