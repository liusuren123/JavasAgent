"""文件压缩解压工具。

提供 zip / tar / tar.gz / tar.bz2 / tar.xz 格式的压缩、解压、
归档内容浏览与单文件提取能力。所有路径均通过 safe_resolve_path
做安全检查，防止路径遍历攻击。
"""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path

# 支持的格式 → (模块, 写模式 / 读模式后缀)
_SUPPORTED_FMT = {
    "zip": "zip",
    "tar": "tar",
    "tar.gz": "tar.gz",
    "tgz": "tar.gz",
    "tar.bz2": "tar.bz2",
    "tar.xz": "tar.xz",
}

_TAR_MODES = {
    "tar": "",
    "tar.gz": "gz",
    "tar.bz2": "bz2",
    "tar.xz": "xz",
}


# =====================================================================
# 公开 API
# =====================================================================


def compress_files(
    workspace: Path,
    sources: list[str],
    archive_path: str,
    fmt: str = "zip",
) -> dict[str, Any]:
    """将文件/目录压缩为一个归档。

    Args:
        workspace: 工作空间根目录
        sources: 要压缩的文件/目录路径列表（相对 workspace）
        archive_path: 归档文件路径（相对 workspace）
        fmt: 格式，支持 zip/tar/tar.gz/tgz/tar.bz2/tar.xz

    Returns:
        ``{"success": True, "archive_path": str, "file_count": int, "size_bytes": int}``
        或 ``{"success": False, "error": str}``
    """
    canonical = _SUPPORTED_FMT.get(fmt)
    if canonical is None:
        msg = f"不支持的压缩格式 '{fmt}'，支持: {', '.join(_SUPPORTED_FMT)}"
        logger.error(msg)
        return {"success": False, "error": msg}

    try:
        safe_archive = safe_resolve_path(
            workspace, archive_path, allow_create_parents=True
        )
    except PathSafetyError as exc:
        logger.error(f"归档路径不安全: {exc}")
        return {"success": False, "error": str(exc)}

    # 解析所有源路径
    safe_sources: list[Path] = []
    for src in sources:
        try:
            safe_sources.append(safe_resolve_path(workspace, src))
        except PathSafetyError as exc:
            logger.error(f"源路径不安全 '{src}': {exc}")
            return {"success": False, "error": str(exc)}

    # 检查源路径是否存在
    for s in safe_sources:
        if not s.exists():
            msg = f"源路径不存在: {s.relative_to(workspace)}"
            logger.error(msg)
            return {"success": False, "error": msg}

    try:
        file_count = (
            _compress_zip(workspace, safe_sources, safe_archive)
            if canonical == "zip"
            else _compress_tar(workspace, safe_sources, safe_archive, canonical)
        )
    except Exception as exc:
        logger.error(f"压缩失败: {exc}")
        return {"success": False, "error": str(exc)}

    size = safe_archive.stat().st_size
    rel = str(safe_archive.relative_to(workspace))
    logger.info(f"压缩完成: {rel} ({file_count} 个文件, {size} 字节)")
    return {
        "success": True,
        "archive_path": rel,
        "file_count": file_count,
        "size_bytes": size,
    }


def decompress_archive(
    workspace: Path,
    archive_path: str,
    target_dir: str = ".",
) -> dict[str, Any]:
    """解压归档到指定目录。

    Args:
        workspace: 工作空间根目录
        archive_path: 归档文件路径（相对 workspace）
        target_dir: 目标目录（相对 workspace）

    Returns:
        ``{"success": True, "target_dir": str, "file_count": int, "files": list[str]}``
    """
    try:
        safe_archive = safe_resolve_path(workspace, archive_path)
        safe_target = safe_resolve_path(
            workspace, target_dir, allow_create_parents=True
        )
    except PathSafetyError as exc:
        return {"success": False, "error": str(exc)}

    if not safe_archive.exists():
        return {"success": False, "error": f"归档文件不存在: {archive_path}"}

    if not safe_archive.is_file():
        return {"success": False, "error": f"路径不是文件: {archive_path}"}

    try:
        files = _decompress_zip(safe_archive, safe_target)
        if files is None:
            files = _decompress_tar(safe_archive, safe_target)
        if files is None:
            return {
                "success": False,
                "error": f"无法识别的归档格式: {archive_path}",
            }
    except Exception as exc:
        logger.error(f"解压失败: {exc}")
        return {"success": False, "error": str(exc)}

    # 返回相对 workspace 的路径
    rel_files = [str(Path(f).relative_to(workspace)) for f in files]
    rel_target = str(safe_target.relative_to(workspace))
    logger.info(f"解压完成: {len(rel_files)} 个文件到 {rel_target}")
    return {
        "success": True,
        "target_dir": rel_target,
        "file_count": len(rel_files),
        "files": rel_files,
    }


def list_archive(workspace: Path, archive_path: str) -> dict[str, Any]:
    """列出归档内文件清单。

    Returns:
        ``{"success": True, "members": list[dict]}`` 每个 dict 含 name, size, is_dir
    """
    try:
        safe_archive = safe_resolve_path(workspace, archive_path)
    except PathSafetyError as exc:
        return {"success": False, "error": str(exc)}

    if not safe_archive.exists():
        return {"success": False, "error": f"归档文件不存在: {archive_path}"}

    try:
        members = _list_zip(safe_archive)
        if members is None:
            members = _list_tar(safe_archive)
        if members is None:
            return {
                "success": False,
                "error": f"无法识别的归档格式: {archive_path}",
            }
    except Exception as exc:
        logger.error(f"列出归档内容失败: {exc}")
        return {"success": False, "error": str(exc)}

    return {"success": True, "members": members}


def extract_single(
    workspace: Path,
    archive_path: str,
    member_path: str,
    target_dir: str = ".",
) -> dict[str, Any]:
    """从归档中提取单个文件。

    Args:
        member_path: 归档内成员路径
        target_dir: 解压目标目录（相对 workspace）

    Returns:
        ``{"success": True, "extracted_path": str}``
    """
    try:
        safe_archive = safe_resolve_path(workspace, archive_path)
        safe_target = safe_resolve_path(
            workspace, target_dir, allow_create_parents=True
        )
    except PathSafetyError as exc:
        return {"success": False, "error": str(exc)}

    if not safe_archive.exists():
        return {"success": False, "error": f"归档文件不存在: {archive_path}"}

    try:
        result = _extract_single_zip(safe_archive, member_path, safe_target)
        if result is None:
            result = _extract_single_tar(safe_archive, member_path, safe_target)
        if result is None:
            return {
                "success": False,
                "error": f"无法识别的归档格式或成员不存在: {member_path}",
            }
        rel = str(Path(result).relative_to(workspace))
        logger.info(f"提取单个文件: {member_path} → {rel}")
        return {"success": True, "extracted_path": rel}
    except Exception as exc:
        logger.error(f"提取失败: {exc}")
        return {"success": False, "error": str(exc)}


def get_archive_info(workspace: Path, archive_path: str) -> dict[str, Any]:
    """获取归档元信息。

    Returns:
        ``{"success": True, "format": str, "size_bytes": int,
            "file_count": int, "dir_count": int, "compressed_size": int}``
    """
    try:
        safe_archive = safe_resolve_path(workspace, archive_path)
    except PathSafetyError as exc:
        return {"success": False, "error": str(exc)}

    if not safe_archive.exists():
        return {"success": False, "error": f"归档文件不存在: {archive_path}"}

    size = safe_archive.stat().st_size
    name = safe_archive.name.lower()

    try:
        if zipfile.is_zipfile(safe_archive):
            info = _info_zip(safe_archive, size)
        elif tarfile.is_tarfile(safe_archive):
            info = _info_tar(safe_archive, size, name)
        else:
            return {
                "success": False,
                "error": f"无法识别的归档格式: {archive_path}",
            }
    except Exception as exc:
        logger.error(f"获取归档信息失败: {exc}")
        return {"success": False, "error": str(exc)}

    info["success"] = True
    return info


# =====================================================================
# ZIP 辅助
# =====================================================================


def _compress_zip(
    workspace: Path, sources: list[Path], archive: Path
) -> int:
    """写入 zip 归档，返回文件数量。"""
    count = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for src in sources:
            arcname = str(src.relative_to(workspace))
            if src.is_file():
                zf.write(src, arcname)
                count += 1
            elif src.is_dir():
                for root, _dirs, files in os.walk(src):
                    root_path = Path(root)
                    for fname in files:
                        full = root_path / fname
                        arc = str(full.relative_to(workspace))
                        zf.write(full, arc)
                        count += 1
    return count


def _decompress_zip(archive: Path, target: Path) -> list[str] | None:
    """解压 zip，返回绝对路径列表；不是 zip 则返回 None。"""
    if not zipfile.is_zipfile(archive):
        return None
    files: list[str] = []
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            # 跳过目录条目
            if info.is_dir():
                continue
            # 防止 zip slip（路径遍历）
            dest = (target / info.filename).resolve()
            try:
                dest.relative_to(target.resolve())
            except ValueError:
                logger.warning(f"跳过不安全成员: {info.filename}")
                continue
            zf.extract(info, target)
            files.append(str(dest))
    return files


def _list_zip(archive: Path) -> list[dict[str, Any]] | None:
    if not zipfile.is_zipfile(archive):
        return None
    members: list[dict[str, Any]] = []
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            members.append(
                {
                    "name": info.filename,
                    "size": info.file_size,
                    "compressed_size": info.compress_size,
                    "is_dir": info.is_dir(),
                }
            )
    return members


def _extract_single_zip(
    archive: Path, member: str, target: Path
) -> str | None:
    if not zipfile.is_zipfile(archive):
        return None
    with zipfile.ZipFile(archive, "r") as zf:
        # 精确匹配或路径结尾匹配
        names = zf.namelist()
        match = None
        if member in names:
            match = member
        else:
            for n in names:
                if n.rstrip("/") == member.rstrip("/"):
                    match = n
                    break
        if match is None:
            return None
        info = zf.getinfo(match)
        if info.is_dir():
            return None
        dest = (target / Path(match).name).resolve()
        zf.extract(info, target)
        return str(dest)


def _info_zip(archive: Path, size: int) -> dict[str, Any]:
    compressed = 0
    file_count = 0
    dir_count = 0
    with zipfile.ZipFile(archive, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                dir_count += 1
            else:
                file_count += 1
            compressed += info.compress_size
    return {
        "format": "zip",
        "size_bytes": size,
        "compressed_size": compressed,
        "file_count": file_count,
        "dir_count": dir_count,
    }


# =====================================================================
# TAR 辅助
# =====================================================================


def _compress_tar(
    workspace: Path, sources: list[Path], archive: Path, canonical: str
) -> int:
    ext = _TAR_MODES[canonical]
    mode = f"w:{ext}" if ext else "w"
    count = 0
    with tarfile.open(archive, mode) as tf:
        for src in sources:
            arcname = str(src.relative_to(workspace))
            if src.is_file():
                tf.add(src, arcname=arcname)
                count += 1
            elif src.is_dir():
                for root, _dirs, files in os.walk(src):
                    root_path = Path(root)
                    for fname in files:
                        full = root_path / fname
                        arc = str(full.relative_to(workspace))
                        tf.add(full, arcname=arc)
                        count += 1
    return count


def _decompress_tar(archive: Path, target: Path) -> list[str] | None:
    if not tarfile.is_tarfile(archive):
        return None
    files: list[str] = []
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            if not member.isfile():
                continue
            # 防止 tar 路径遍历
            dest = (target / member.name).resolve()
            try:
                dest.relative_to(target.resolve())
            except ValueError:
                logger.warning(f"跳过不安全成员: {member.name}")
                continue
            tf.extract(member, target, filter="data")
            files.append(str(dest))
    return files


def _list_tar(archive: Path) -> list[dict[str, Any]] | None:
    if not tarfile.is_tarfile(archive):
        return None
    members: list[dict[str, Any]] = []
    with tarfile.open(archive, "r:*") as tf:
        for m in tf.getmembers():
            members.append(
                {
                    "name": m.name,
                    "size": m.size,
                    "is_dir": m.isdir(),
                    "mode": oct(m.mode) if m.mode else None,
                    "mtime": m.mtime,
                }
            )
    return members


def _extract_single_tar(
    archive: Path, member: str, target: Path
) -> str | None:
    if not tarfile.is_tarfile(archive):
        return None
    with tarfile.open(archive, "r:*") as tf:
        # 精确匹配
        match = None
        for m in tf.getmembers():
            if m.name == member or m.name.rstrip("/") == member.rstrip("/"):
                match = m
                break
        if match is None or not match.isfile():
            return None
        tf.extract(match, target, filter="data")
        return str((target / match.name).resolve())


def _info_tar(
    archive: Path, size: int, name: str
) -> dict[str, Any]:
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        fmt = "tar.gz"
    elif name.endswith(".tar.bz2"):
        fmt = "tar.bz2"
    elif name.endswith(".tar.xz"):
        fmt = "tar.xz"
    else:
        fmt = "tar"
    file_count = 0
    dir_count = 0
    with tarfile.open(archive, "r:*") as tf:
        for m in tf.getmembers():
            if m.isfile():
                file_count += 1
            elif m.isdir():
                dir_count += 1
    return {
        "format": fmt,
        "size_bytes": size,
        "file_count": file_count,
        "dir_count": dir_count,
    }
