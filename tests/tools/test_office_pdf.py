"""PDF 操作模块测试。

覆盖 office_pdf 的四个核心功能：
    - read_pdf_text: 读取 PDF 文本
    - create_pdf: 创建 PDF
    - merge_pdfs: 合并 PDF
    - extract_pages: 提取页面

依赖：pytest, PyPDF2, reportlab（创建测试需要）
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.tools.office_pdf import (
    create_pdf,
    extract_pages,
    merge_pdfs,
    read_pdf_text,
)

# ======================================================================
# 辅助函数
# ======================================================================


def _run(coro: Any) -> Any:
    """在测试中运行异步协程。"""
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_sample_pdf(path: Path, pages: int = 3) -> Path:
    """使用 reportlab 创建一个简单的测试 PDF。"""
    try:
        from reportlab.pdfgen import canvas as rlcanvas
        import io

        buf = io.BytesIO()
        c = rlcanvas.Canvas(buf, pagesize=(595.28, 841.89))
        for i in range(pages):
            c.setFont("Helvetica", 12)
            c.drawString(72, 800 - i * 20, f"Test Page {i + 1}")
            c.showPage()
        c.save()
        buf.seek(0)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(buf.read())
        return path
    except ImportError:
        pytest.skip("reportlab 未安装，跳过 PDF 创建测试")


# ======================================================================
# 测试 fixture
# ======================================================================


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """创建临时工作目录。"""
    return tmp_path


@pytest.fixture
def sample_pdf(workspace: Path) -> Path:
    """在工作目录中创建一个 3 页的示例 PDF。"""
    return _make_sample_pdf(workspace / "sample.pdf", pages=3)


@pytest.fixture
def sample_pdfs(workspace: Path) -> list[Path]:
    """在工作目录中创建多个示例 PDF。"""
    paths = []
    for i in range(3):
        p = _make_sample_pdf(workspace / f"doc_{i}.pdf", pages=2)
        paths.append(p)
    return paths


# ======================================================================
# 读取 PDF 测试
# ======================================================================


class TestReadPdfText:
    """PDF 文本读取测试。"""

    def test_read_existing_pdf(self, workspace: Path, sample_pdf: Path) -> None:
        """测试读取存在的 PDF 文件。"""
        result = _run(read_pdf_text(workspace, {"path": "sample.pdf"}))
        assert "error" not in result, f"读取失败: {result.get('error')}"
        assert result["page_count"] == 3
        assert result["total_text_length"] > 0

    def test_read_nonexistent_pdf(self, workspace: Path) -> None:
        """测试读取不存在的 PDF。"""
        result = _run(read_pdf_text(workspace, {"path": "nonexistent.pdf"}))
        assert "error" in result
        assert "不存在" in result["error"]

    def test_read_with_max_pages(self, workspace: Path, sample_pdf: Path) -> None:
        """测试限制最大页数。"""
        result = _run(
            read_pdf_text(workspace, {"path": "sample.pdf", "max_pages": 1})
        )
        assert "error" not in result
        assert result["page_count"] == 1

    def test_read_path_traversal(self, workspace: Path) -> None:
        """测试路径遍历安全防护。"""
        result = _run(read_pdf_text(workspace, {"path": "../../../etc/passwd"}))
        assert "error" in result


# ======================================================================
# 创建 PDF 测试
# ======================================================================


class TestCreatePdf:
    """PDF 创建测试。"""

    def test_create_basic_pdf(self, workspace: Path) -> None:
        """测试创建基本 PDF。"""
        result = _run(
            create_pdf(
                workspace,
                {
                    "path": "output.pdf",
                    "content": "Hello World\nThis is line 2\nThis is line 3",
                },
            )
        )
        assert "error" not in result, f"创建失败: {result.get('error')}"
        assert result["status"] == "created"
        assert (workspace / "output.pdf").exists()
        assert (workspace / "output.pdf").stat().st_size > 0

    def test_create_with_page_size(self, workspace: Path) -> None:
        """测试指定页面大小。"""
        result = _run(
            create_pdf(
                workspace,
                {
                    "path": "letter.pdf",
                    "content": "Letter size page",
                    "page_size": "Letter",
                },
            )
        )
        assert "error" not in result
        assert result["page_size"] == "Letter"

    def test_create_with_font_size(self, workspace: Path) -> None:
        """测试指定字体大小。"""
        result = _run(
            create_pdf(
                workspace,
                {
                    "path": "large_font.pdf",
                    "content": "Big text",
                    "font_size": 24,
                },
            )
        )
        assert "error" not in result
        assert result["font_size"] == 24

    def test_create_empty_content(self, workspace: Path) -> None:
        """测试空内容创建失败。"""
        result = _run(
            create_pdf(workspace, {"path": "empty.pdf", "content": ""})
        )
        assert "error" in result

    def test_create_multiline_content(self, workspace: Path) -> None:
        """测试多段落长文本创建。"""
        content = "\n".join(
            [f"第 {i + 1} 段: 这是一段测试文本，用于验证 PDF 创建功能。" for i in range(50)]
        )
        result = _run(
            create_pdf(workspace, {"path": "long.pdf", "content": content})
        )
        assert "error" not in result
        assert (workspace / "long.pdf").exists()

    def test_create_chinese_content(self, workspace: Path) -> None:
        """测试中文内容创建（需要中文字体）。"""
        result = _run(
            create_pdf(
                workspace,
                {
                    "path": "chinese.pdf",
                    "content": "你好世界\n这是中文测试\n第二行中文内容",
                },
            )
        )
        # 如果 reportlab 安装且中文字体可用，应成功
        assert "error" not in result
        assert (workspace / "chinese.pdf").exists()


# ======================================================================
# 合并 PDF 测试
# ======================================================================


class TestMergePdfs:
    """PDF 合并测试。"""

    def test_merge_two_pdfs(
        self, workspace: Path, sample_pdfs: list[Path]
    ) -> None:
        """测试合并两个 PDF。"""
        result = _run(
            merge_pdfs(
                workspace,
                {
                    "paths": ["doc_0.pdf", "doc_1.pdf"],
                    "output": "merged.pdf",
                },
            )
        )
        assert "error" not in result, f"合并失败: {result.get('error')}"
        assert result["merged_count"] == 2
        assert (workspace / "merged.pdf").exists()
        assert (workspace / "merged.pdf").stat().st_size > 0

    def test_merge_three_pdfs(
        self, workspace: Path, sample_pdfs: list[Path]
    ) -> None:
        """测试合并三个 PDF。"""
        result = _run(
            merge_pdfs(
                workspace,
                {
                    "paths": ["doc_0.pdf", "doc_1.pdf", "doc_2.pdf"],
                    "output": "merged_all.pdf",
                },
            )
        )
        assert "error" not in result
        assert result["merged_count"] == 3

    def test_merge_empty_list(self, workspace: Path) -> None:
        """测试空列表合并失败。"""
        result = _run(
            merge_pdfs(workspace, {"paths": [], "output": "out.pdf"})
        )
        assert "error" in result

    def test_merge_single_file(self, workspace: Path, sample_pdf: Path) -> None:
        """测试单文件合并失败。"""
        result = _run(
            merge_pdfs(workspace, {"paths": ["sample.pdf"], "output": "out.pdf"})
        )
        assert "error" in result
        assert "至少需要 2" in result["error"]

    def test_merge_nonexistent_file(self, workspace: Path, sample_pdf: Path) -> None:
        """测试包含不存在文件的合并失败。"""
        result = _run(
            merge_pdfs(
                workspace,
                {
                    "paths": ["sample.pdf", "nonexistent.pdf"],
                    "output": "out.pdf",
                },
            )
        )
        assert "error" in result

    def test_merge_preserves_content(
        self, workspace: Path, sample_pdfs: list[Path]
    ) -> None:
        """测试合并后内容保留。"""
        # 合并两个各 2 页的 PDF
        result = _run(
            merge_pdfs(
                workspace,
                {
                    "paths": ["doc_0.pdf", "doc_1.pdf"],
                    "output": "merged_check.pdf",
                },
            )
        )
        assert "error" not in result

        # 验证合并后的页数
        from PyPDF2 import PdfReader

        reader = PdfReader(str(workspace / "merged_check.pdf"))
        assert len(reader.pages) == 4  # 2 + 2


# ======================================================================
# 页面提取测试
# ======================================================================


class TestExtractPages:
    """PDF 页面提取测试。"""

    def test_extract_single_page(self, workspace: Path, sample_pdf: Path) -> None:
        """测试提取单页。"""
        result = _run(
            extract_pages(
                workspace,
                {
                    "path": "sample.pdf",
                    "output": "page_1.pdf",
                    "start": 1,
                    "end": 1,
                },
            )
        )
        assert "error" not in result, f"提取失败: {result.get('error')}"
        assert result["extracted_pages"] == 1
        assert (workspace / "page_1.pdf").exists()

    def test_extract_page_range(self, workspace: Path, sample_pdf: Path) -> None:
        """测试提取多页范围。"""
        result = _run(
            extract_pages(
                workspace,
                {
                    "path": "sample.pdf",
                    "output": "pages_1_2.pdf",
                    "start": 1,
                    "end": 2,
                },
            )
        )
        assert "error" not in result
        assert result["extracted_pages"] == 2

    def test_extract_all_pages(self, workspace: Path, sample_pdf: Path) -> None:
        """测试提取全部页面（不指定范围）。"""
        result = _run(
            extract_pages(
                workspace,
                {
                    "path": "sample.pdf",
                    "output": "all_pages.pdf",
                },
            )
        )
        assert "error" not in result
        assert result["extracted_pages"] == 3  # sample_pdf 有 3 页

    def test_extract_invalid_start(self, workspace: Path, sample_pdf: Path) -> None:
        """测试无效起始页码。"""
        result = _run(
            extract_pages(
                workspace,
                {
                    "path": "sample.pdf",
                    "output": "invalid.pdf",
                    "start": 99,
                },
            )
        )
        assert "error" in result
        assert "超出范围" in result["error"]

    def test_extract_end_before_start(self, workspace: Path, sample_pdf: Path) -> None:
        """测试结束页码小于起始页码。"""
        result = _run(
            extract_pages(
                workspace,
                {
                    "path": "sample.pdf",
                    "output": "invalid.pdf",
                    "start": 3,
                    "end": 1,
                },
            )
        )
        assert "error" in result

    def test_extract_nonexistent_pdf(self, workspace: Path) -> None:
        """测试提取不存在的 PDF。"""
        result = _run(
            extract_pages(
                workspace,
                {
                    "path": "nonexistent.pdf",
                    "output": "out.pdf",
                    "start": 1,
                },
            )
        )
        assert "error" in result
        assert "不存在" in result["error"]

    def test_extract_preserves_content(
        self, workspace: Path, sample_pdf: Path
    ) -> None:
        """测试提取后内容完整性。"""
        _run(
            extract_pages(
                workspace,
                {
                    "path": "sample.pdf",
                    "output": "extracted.pdf",
                    "start": 2,
                    "end": 2,
                },
            )
        )

        # 验证提取后的文件页数
        from PyPDF2 import PdfReader

        reader = PdfReader(str(workspace / "extracted.pdf"))
        assert len(reader.pages) == 1


# ======================================================================
# 集成测试：创建 -> 读取 -> 提取 -> 合并
# ======================================================================


class TestPdfWorkflow:
    """PDF 完整工作流测试。"""

    def test_create_read_workflow(self, workspace: Path) -> None:
        """测试创建后读取的工作流。"""
        # 创建
        create_result = _run(
            create_pdf(
                workspace,
                {
                    "path": "workflow.pdf",
                    "content": "Workflow Test Page 1\n\nWorkflow Test Page 2",
                },
            )
        )
        assert "error" not in create_result

        # 读取验证
        read_result = _run(
            read_pdf_text(workspace, {"path": "workflow.pdf"})
        )
        assert "error" not in read_result

    def test_create_extract_merge_workflow(self, workspace: Path) -> None:
        """测试完整创建 -> 提取 -> 合并工作流。"""
        # 创建两个 PDF
        _run(
            create_pdf(
                workspace,
                {
                    "path": "wf_a.pdf",
                    "content": "Document A content",
                },
            )
        )
        _run(
            create_pdf(
                workspace,
                {
                    "path": "wf_b.pdf",
                    "content": "Document B content",
                },
            )
        )

        # 合并
        merge_result = _run(
            merge_pdfs(
                workspace,
                {
                    "paths": ["wf_a.pdf", "wf_b.pdf"],
                    "output": "wf_merged.pdf",
                },
            )
        )
        assert "error" not in merge_result
        assert merge_result["merged_count"] == 2

        # 读取合并后的文件
        read_result = _run(
            read_pdf_text(workspace, {"path": "wf_merged.pdf"})
        )
        assert "error" not in read_result
