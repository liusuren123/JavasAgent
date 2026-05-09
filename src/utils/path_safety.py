"""路径安全工具。

防止路径遍历攻击，确保文件操作限定在工作目录范围内。
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger


class PathSafetyError(ValueError):
    """路径安全违规异常。"""

    pass


def safe_resolve_path(
    workspace: Path,
    user_path: str,
    *,
    allow_create_parents: bool = False,
) -> Path:
    """安全解析用户提供的路径，防止路径遍历。

    将用户路径与 workspace 拼接后解析，验证结果仍在 workspace 内。
    支持 ``..`` 检测和符号链接跟随。

    Args:
        workspace: 工作目录的根路径（安全边界）
        user_path: 用户提供的相对路径
        allow_create_parents: 是否允许创建不存在的父目录

    Returns:
        解析后的安全绝对路径

    Raises:
        PathSafetyError: 路径超出工作目录范围或包含非法字符
    """
    if not user_path:
        raise PathSafetyError("路径不能为空")

    # 检查明显的路径遍历模式
    normalized = user_path.replace("\\", "/")
    if ".." in normalized.split("/"):
        raise PathSafetyError(f"路径包含遍历序列 '..': {user_path}")

    # 解析工作区根
    workspace = workspace.resolve()

    # 拼接并解析
    target = (workspace / user_path).resolve()

    # 验证是否在工作区内
    try:
        target.relative_to(workspace)
    except ValueError:
        raise PathSafetyError(
            f"路径 '{user_path}' 超出工作目录范围 '{workspace}'"
        ) from None

    # 对于已存在的路径，再次验证（防御符号链接逃逸）
    if target.exists():
        real_target = target.resolve()
        try:
            real_target.relative_to(workspace)
        except ValueError:
            raise PathSafetyError(
                f"路径 '{user_path}' 解析后超出工作目录范围（可能是符号链接）"
            ) from None

    # 按需创建父目录
    if allow_create_parents and not target.parent.exists():
        target.parent.mkdir(parents=True, exist_ok=True)

    return target


def is_safe_path(workspace: Path, user_path: str) -> bool:
    """检查路径是否安全（不抛异常的版本）。

    Args:
        workspace: 工作目录根路径
        user_path: 用户提供的路径

    Returns:
        路径是否在工作目录范围内
    """
    try:
        safe_resolve_path(workspace, user_path)
        return True
    except PathSafetyError:
        return False
