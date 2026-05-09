"""ArchiveManager 文件压缩解压工具测试。"""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from src.tools.archive_ops import (
    compress_files,
    decompress_archive,
    extract_single,
    get_archive_info,
    list_archive,
)
from src.utils.path_safety import PathSafetyError


# =====================================================================
# Fixtures
# =====================================================================


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建模拟工作空间，预置一些文件和目录。"""
    ws = tmp_path / "workspace"
    ws.mkdir()

    # 单个文本文件
    (ws / "hello.txt").write_text("hello world", encoding="utf-8")

    # 子目录 + 多个文件
    sub = ws / "data"
    sub.mkdir()
    (sub / "a.txt").write_text("aaa", encoding="utf-8")
    (sub / "b.txt").write_text("bbb", encoding="utf-8")
    (sub / "nested").mkdir()
    (sub / "nested" / "c.txt").write_text("ccc", encoding="utf-8")
    return ws


# =====================================================================
# compress_files
# =====================================================================


class TestCompressFiles:
    """压缩功能测试。"""

    def test_compress_single_file(self, workspace: Path) -> None:
        result = compress_files(workspace, ["hello.txt"], "out.zip")
        assert result["success"] is True
        assert result["file_count"] == 1
        assert (workspace / "out.zip").exists()

    def test_compress_multiple_files(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt", "data/a.txt"], "multi.zip"
        )
        assert result["success"] is True
        assert result["file_count"] == 2

    def test_compress_directory(self, workspace: Path) -> None:
        result = compress_files(workspace, ["data"], "dir.zip")
        assert result["success"] is True
        # data/a.txt + data/b.txt + data/nested/c.txt = 3
        assert result["file_count"] == 3

    def test_compress_tar_gz(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt"], "out.tar.gz", fmt="tar.gz"
        )
        assert result["success"] is True
        assert (workspace / "out.tar.gz").exists()

    def test_compress_tgz_alias(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt"], "out.tgz", fmt="tgz"
        )
        assert result["success"] is True

    def test_compress_tar_bz2(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt"], "out.tar.bz2", fmt="tar.bz2"
        )
        assert result["success"] is True

    def test_compress_tar_xz(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt"], "out.tar.xz", fmt="tar.xz"
        )
        assert result["success"] is True

    def test_compress_tar(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt"], "out.tar", fmt="tar"
        )
        assert result["success"] is True

    def test_compress_unsupported_format(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt"], "out.rar", fmt="rar"
        )
        assert result["success"] is False
        assert "不支持" in result["error"]

    def test_compress_source_not_exist(self, workspace: Path) -> None:
        result = compress_files(workspace, ["nope.txt"], "out.zip")
        assert result["success"] is False
        assert "不存在" in result["error"]


# =====================================================================
# decompress_archive
# =====================================================================


class TestDecompressArchive:
    """解压功能测试。"""

    def _make_zip(self, workspace: Path) -> str:
        compress_files(workspace, ["data"], "test.zip")
        return "test.zip"

    def test_decompress_zip(self, workspace: Path) -> None:
        self._make_zip(workspace)
        result = decompress_archive(workspace, "test.zip", "output")
        assert result["success"] is True
        assert result["file_count"] == 3
        assert (workspace / "output").is_dir()

    def test_decompress_tar_gz(self, workspace: Path) -> None:
        compress_files(workspace, ["hello.txt"], "test.tar.gz", fmt="tar.gz")
        result = decompress_archive(workspace, "test.tar.gz", "output")
        assert result["success"] is True
        assert result["file_count"] == 1

    def test_decompress_tar_bz2(self, workspace: Path) -> None:
        compress_files(
            workspace, ["hello.txt"], "test.tar.bz2", fmt="tar.bz2"
        )
        result = decompress_archive(workspace, "test.tar.bz2", "output")
        assert result["success"] is True

    def test_decompress_archive_not_exist(self, workspace: Path) -> None:
        result = decompress_archive(workspace, "missing.zip", ".")
        assert result["success"] is False
        assert "不存在" in result["error"]

    def test_decompress_default_target(self, workspace: Path) -> None:
        compress_files(workspace, ["hello.txt"], "test.zip")
        result = decompress_archive(workspace, "test.zip")
        assert result["success"] is True


# =====================================================================
# list_archive
# =====================================================================


class TestListArchive:
    """列出归档内容测试。"""

    def test_list_zip(self, workspace: Path) -> None:
        compress_files(workspace, ["data"], "test.zip")
        result = list_archive(workspace, "test.zip")
        assert result["success"] is True
        assert len(result["members"]) > 0
        names = [m["name"] for m in result["members"]]
        assert any("a.txt" in n for n in names)

    def test_list_tar_gz(self, workspace: Path) -> None:
        compress_files(workspace, ["hello.txt"], "test.tar.gz", fmt="tar.gz")
        result = list_archive(workspace, "test.tar.gz")
        assert result["success"] is True
        assert len(result["members"]) == 1

    def test_list_archive_not_exist(self, workspace: Path) -> None:
        result = list_archive(workspace, "nope.zip")
        assert result["success"] is False


# =====================================================================
# extract_single
# =====================================================================


class TestExtractSingle:
    """提取单个文件测试。"""

    def test_extract_from_zip(self, workspace: Path) -> None:
        compress_files(workspace, ["data"], "test.zip")
        result = extract_single(
            workspace, "test.zip", "data/a.txt", "single"
        )
        assert result["success"] is True
        assert (workspace / "single").is_dir()

    def test_extract_from_tar(self, workspace: Path) -> None:
        compress_files(workspace, ["hello.txt"], "test.tar", fmt="tar")
        result = extract_single(
            workspace, "test.tar", "hello.txt", "single"
        )
        assert result["success"] is True

    def test_extract_member_not_found(self, workspace: Path) -> None:
        compress_files(workspace, ["hello.txt"], "test.zip")
        result = extract_single(
            workspace, "test.zip", "nonexistent.txt", "."
        )
        assert result["success"] is False

    def test_extract_archive_not_exist(self, workspace: Path) -> None:
        result = extract_single(workspace, "nope.zip", "a.txt", ".")
        assert result["success"] is False


# =====================================================================
# get_archive_info
# =====================================================================


class TestGetArchiveInfo:
    """归档元信息测试。"""

    def test_info_zip(self, workspace: Path) -> None:
        compress_files(workspace, ["data"], "test.zip")
        result = get_archive_info(workspace, "test.zip")
        assert result["success"] is True
        assert result["format"] == "zip"
        assert result["size_bytes"] > 0
        assert result["file_count"] == 3

    def test_info_tar_gz(self, workspace: Path) -> None:
        compress_files(workspace, ["hello.txt"], "test.tar.gz", fmt="tar.gz")
        result = get_archive_info(workspace, "test.tar.gz")
        assert result["success"] is True
        assert result["format"] == "tar.gz"

    def test_info_tar_bz2(self, workspace: Path) -> None:
        compress_files(
            workspace, ["hello.txt"], "test.tar.bz2", fmt="tar.bz2"
        )
        result = get_archive_info(workspace, "test.tar.bz2")
        assert result["success"] is True
        assert result["format"] == "tar.bz2"

    def test_info_not_exist(self, workspace: Path) -> None:
        result = get_archive_info(workspace, "missing.zip")
        assert result["success"] is False


# =====================================================================
# 路径安全测试
# =====================================================================


class TestPathSafety:
    """路径遍历攻击防护测试。"""

    def test_compress_traversal_source(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["../../etc/passwd"], "out.zip"
        )
        assert result["success"] is False

    def test_compress_traversal_archive(self, workspace: Path) -> None:
        result = compress_files(
            workspace, ["hello.txt"], "../../tmp/evil.zip"
        )
        assert result["success"] is False

    def test_decompress_traversal_archive(self, workspace: Path) -> None:
        result = decompress_archive(
            workspace, "../../etc/passwd", "."
        )
        assert result["success"] is False

    def test_decompress_traversal_target(self, workspace: Path) -> None:
        compress_files(workspace, ["hello.txt"], "test.zip")
        result = decompress_archive(
            workspace, "test.zip", "../../tmp/evil"
        )
        assert result["success"] is False

    def test_list_traversal(self, workspace: Path) -> None:
        result = list_archive(workspace, "../../etc/passwd")
        assert result["success"] is False

    def test_extract_traversal(self, workspace: Path) -> None:
        result = extract_single(
            workspace, "../../etc/passwd", "a.txt", "."
        )
        assert result["success"] is False

    def test_info_traversal(self, workspace: Path) -> None:
        result = get_archive_info(workspace, "../../etc/passwd")
        assert result["success"] is False


# =====================================================================
# 边界 / 错误场景
# =====================================================================


class TestEdgeCases:
    """边界与错误场景。"""

    def test_compress_empty_sources(self, workspace: Path) -> None:
        result = compress_files(workspace, [], "empty.zip")
        assert result["success"] is True
        assert result["file_count"] == 0

    def test_decompress_not_a_file(self, workspace: Path) -> None:
        # 目标是一个目录而非文件
        result = decompress_archive(workspace, "data", ".")
        assert result["success"] is False

    def test_roundtrip_zip(self, workspace: Path) -> None:
        """压缩 → 解压 → 比较内容。"""
        original = (workspace / "hello.txt").read_text(encoding="utf-8")
        compress_files(workspace, ["hello.txt"], "rt.zip")
        decompress_archive(workspace, "rt.zip", "rt_out")
        restored = (workspace / "rt_out" / "hello.txt").read_text(
            encoding="utf-8"
        )
        assert original == restored

    def test_roundtrip_tar_gz(self, workspace: Path) -> None:
        original = (workspace / "hello.txt").read_text(encoding="utf-8")
        compress_files(workspace, ["hello.txt"], "rt.tar.gz", fmt="tar.gz")
        decompress_archive(workspace, "rt.tar.gz", "rt_out")
        restored = (workspace / "rt_out" / "hello.txt").read_text(
            encoding="utf-8"
        )
        assert original == restored
