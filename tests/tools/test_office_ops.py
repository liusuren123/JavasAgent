"""OfficeOps 工具测试。

覆盖 office_ops 门面类以及 office_docx / office_xlsx / office_pptx / office_pdf 子模块。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.tools.office_ops import OfficeOps


@pytest.fixture
def office(tmp_path: Path) -> OfficeOps:
    """创建使用临时目录作为 workspace 的 OfficeOps 实例。"""
    return OfficeOps(workspace=str(tmp_path))


# ======================================================================
# 通用 / 错误处理
# ======================================================================


class TestOfficeOpsCommon:
    """通用功能和错误处理测试。"""

    @pytest.mark.asyncio
    async def test_unknown_action(self, office: OfficeOps) -> None:
        result = await office.execute("nonexistent", {})
        assert "error" in result
        assert "available_actions" in result
        assert isinstance(result["available_actions"], list)

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, office: OfficeOps) -> None:
        result = await office.execute("read_docx", {"path": "../../etc/passwd"})
        assert "error" in result
        assert "路径" in result["error"] or "遍历" in result["error"]

    @pytest.mark.asyncio
    async def test_file_not_found(self, office: OfficeOps) -> None:
        result = await office.execute("read_docx", {"path": "not_exist.docx"})
        assert "error" in result
        assert "不存在" in result["error"]


# ======================================================================
# Word (.docx) 操作 — office_docx
# ======================================================================


class TestWordOps:
    """Word 文档操作测试。"""

    @pytest.mark.asyncio
    async def test_create_and_read_docx(self, office: OfficeOps) -> None:
        paragraphs = ["第一段内容", "第二段内容", "第三段内容"]
        create_result = await office.execute("create_docx", {
            "path": "test.docx",
            "title": "测试文档",
            "paragraphs": paragraphs,
        })
        assert create_result.get("created") is True

        read_result = await office.execute("read_docx", {"path": "test.docx"})
        assert "paragraphs" in read_result
        assert read_result["paragraph_count"] >= 3

        texts = [p["text"] for p in read_result["paragraphs"]]
        for para in paragraphs:
            assert para in texts

    @pytest.mark.asyncio
    async def test_create_docx_with_headings(self, office: OfficeOps) -> None:
        result = await office.execute("create_docx", {
            "path": "headings.docx",
            "title": "标题文档",
            "headings": [
                {"level": 1, "text": "第一章"},
                {"level": 2, "text": "第一节"},
            ],
            "paragraphs": ["正文内容"],
        })
        assert result.get("created") is True

    @pytest.mark.asyncio
    async def test_append_docx(self, office: OfficeOps) -> None:
        await office.execute("create_docx", {
            "path": "append_test.docx",
            "paragraphs": ["原有内容"],
        })

        result = await office.execute("append_docx", {
            "path": "append_test.docx",
            "paragraphs": ["追加的内容1", "追加的内容2"],
            "headings": [{"level": 1, "text": "新章节"}],
        })
        assert result.get("appended") == 3

        read_result = await office.execute("read_docx", {"path": "append_test.docx"})
        all_texts = [p["text"] for p in read_result["paragraphs"]]
        assert "原有内容" in all_texts
        assert "追加的内容1" in all_texts

    @pytest.mark.asyncio
    async def test_append_to_nonexistent_file(self, office: OfficeOps) -> None:
        result = await office.execute("append_docx", {
            "path": "no_such.docx",
            "paragraphs": ["内容"],
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_empty_docx(self, office: OfficeOps) -> None:
        from docx import Document

        doc = Document()
        path = Path(office._workspace) / "empty.docx"
        doc.save(str(path))

        result = await office.execute("read_docx", {"path": "empty.docx"})
        assert result["paragraph_count"] == 0

    @pytest.mark.asyncio
    async def test_edit_docx_search_replace(self, office: OfficeOps) -> None:
        """编辑 Word 文档 — 搜索替换模式。"""
        await office.execute("create_docx", {
            "path": "edit_test.docx",
            "paragraphs": ["Hello World", "Python is great"],
        })

        result = await office.execute("edit_docx", {
            "path": "edit_test.docx",
            "search_replace": [
                {"search": "Hello", "replace": "你好"},
                {"search": "great", "replace": "棒"},
            ],
        })
        assert result.get("replaced", 0) >= 1

        read_result = await office.execute("read_docx", {"path": "edit_test.docx"})
        all_texts = " ".join(p["text"] for p in read_result["paragraphs"])
        assert "你好" in all_texts

    @pytest.mark.asyncio
    async def test_edit_docx_index_replace(self, office: OfficeOps) -> None:
        """编辑 Word 文档 — 按段落索引替换。"""
        await office.execute("create_docx", {
            "path": "edit_idx.docx",
            "paragraphs": ["AAA", "BBB", "CCC"],
        })

        result = await office.execute("edit_docx", {
            "path": "edit_idx.docx",
            "replacements": [{"index": 0, "text": "替换后的AAA"}],
        })
        assert result.get("replaced", 0) >= 1

    @pytest.mark.asyncio
    async def test_edit_nonexistent_docx(self, office: OfficeOps) -> None:
        result = await office.execute("edit_docx", {
            "path": "no_file.docx",
            "search_replace": [{"search": "a", "replace": "b"}],
        })
        assert "error" in result


# ======================================================================
# Excel (.xlsx) 操作 — office_xlsx
# ======================================================================


class TestExcelOps:
    """Excel 文件操作测试。"""

    @pytest.mark.asyncio
    async def test_create_and_read_xlsx(self, office: OfficeOps) -> None:
        headers = ["姓名", "年龄", "城市"]
        rows = [
            ["张三", 25, "北京"],
            ["李四", 30, "上海"],
            ["王五", 28, "深圳"],
        ]

        create_result = await office.execute("create_xlsx", {
            "path": "data.xlsx",
            "headers": headers,
            "rows": rows,
        })
        assert create_result.get("created") is True
        assert create_result["columns"] == 3

        read_result = await office.execute("read_xlsx", {"path": "data.xlsx"})
        assert read_result["row_count"] == 4  # 1 header + 3 data rows
        assert read_result["column_count"] == 3
        assert read_result["rows"][0] == headers

    @pytest.mark.asyncio
    async def test_create_xlsx_custom_sheet(self, office: OfficeOps) -> None:
        result = await office.execute("create_xlsx", {
            "path": "custom.xlsx",
            "sheet": "数据表",
            "headers": ["A", "B"],
            "rows": [[1, 2]],
        })
        assert result["sheet"] == "数据表"

        read_result = await office.execute("read_xlsx", {"path": "custom.xlsx", "sheet": "数据表"})
        assert read_result["sheet"] == "数据表"

    @pytest.mark.asyncio
    async def test_append_xlsx(self, office: OfficeOps) -> None:
        await office.execute("create_xlsx", {
            "path": "append.xlsx",
            "headers": ["姓名", "分数"],
            "rows": [["张三", 90]],
        })

        result = await office.execute("append_xlsx", {
            "path": "append.xlsx",
            "rows": [["李四", 85], ["王五", 95]],
        })
        assert result["appended_rows"] == 2

        read_result = await office.execute("read_xlsx", {"path": "append.xlsx"})
        assert read_result["row_count"] == 4

    @pytest.mark.asyncio
    async def test_read_xlsx_nonexistent_sheet(self, office: OfficeOps) -> None:
        await office.execute("create_xlsx", {
            "path": "sheets.xlsx",
            "headers": ["A"],
            "rows": [[1]],
        })

        result = await office.execute("read_xlsx", {
            "path": "sheets.xlsx",
            "sheet": "不存在",
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_xlsx_empty(self, office: OfficeOps) -> None:
        result = await office.execute("create_xlsx", {"path": "empty.xlsx"})
        assert result.get("created") is True

    @pytest.mark.asyncio
    async def test_append_to_nonexistent_file(self, office: OfficeOps) -> None:
        result = await office.execute("append_xlsx", {
            "path": "no_file.xlsx",
            "rows": [[1, 2]],
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_create_xlsx_with_column_widths(self, office: OfficeOps) -> None:
        result = await office.execute("create_xlsx", {
            "path": "widths.xlsx",
            "headers": ["短", "很长很长的标题"],
            "rows": [["a", "b"]],
            "column_widths": [10, 30],
        })
        assert result.get("created") is True

    @pytest.mark.asyncio
    async def test_edit_xlsx_cells(self, office: OfficeOps) -> None:
        """编辑 Excel — 修改单元格值。"""
        await office.execute("create_xlsx", {
            "path": "edit_cells.xlsx",
            "headers": ["姓名", "年龄"],
            "rows": [["张三", 25]],
        })

        result = await office.execute("edit_xlsx", {
            "path": "edit_cells.xlsx",
            "cells": [{"row": 2, "col": 2, "value": 26}],
        })
        assert result.get("changes", 0) >= 1

        read_result = await office.execute("read_xlsx", {"path": "edit_cells.xlsx"})
        assert read_result["rows"][1][1] == 26

    @pytest.mark.asyncio
    async def test_edit_xlsx_add_and_delete_rows(self, office: OfficeOps) -> None:
        """编辑 Excel — 添加和删除行。"""
        await office.execute("create_xlsx", {
            "path": "edit_rows.xlsx",
            "headers": ["项目", "状态"],
            "rows": [["A", "进行中"], ["B", "已完成"]],
        })

        result = await office.execute("edit_xlsx", {
            "path": "edit_rows.xlsx",
            "delete_rows": [2],  # 删除第一行数据（row 2）
            "add_rows": [["C", "待开始"]],
        })
        assert result.get("changes", 0) >= 2

        read_result = await office.execute("read_xlsx", {"path": "edit_rows.xlsx"})
        all_values = [row[0] for row in read_result["rows"] if row[0]]
        assert "C" in all_values

    @pytest.mark.asyncio
    async def test_edit_nonexistent_xlsx(self, office: OfficeOps) -> None:
        result = await office.execute("edit_xlsx", {
            "path": "no_file.xlsx",
            "cells": [{"row": 1, "col": 1, "value": "test"}],
        })
        assert "error" in result


# ======================================================================
# PowerPoint (.pptx) 操作 — office_pptx
# ======================================================================


class TestPowerPointOps:
    """PowerPoint 演示文稿操作测试。"""

    @pytest.mark.asyncio
    async def test_create_and_read_pptx(self, office: OfficeOps) -> None:
        slides = [
            {"title": "第一页", "body": "第一页内容"},
            {"title": "第二页", "body": "第二页内容"},
            {"title": "第三页", "body": "第三页内容"},
        ]

        create_result = await office.execute("create_pptx", {
            "path": "presentation.pptx",
            "title": "测试演示",
            "slides": slides,
        })
        assert create_result.get("created") is True
        assert create_result["slide_count"] == 3

        read_result = await office.execute("read_pptx", {"path": "presentation.pptx"})
        assert read_result["slide_count"] == 3
        assert len(read_result["slides"]) == 3

    @pytest.mark.asyncio
    async def test_create_empty_pptx(self, office: OfficeOps) -> None:
        result = await office.execute("create_pptx", {"path": "empty.pptx"})
        assert result.get("created") is True
        assert result["slide_count"] == 0

    @pytest.mark.asyncio
    async def test_read_nonexistent_pptx(self, office: OfficeOps) -> None:
        result = await office.execute("read_pptx", {"path": "no.pptx"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_edit_pptx_add_slide(self, office: OfficeOps) -> None:
        """编辑 PPT — 添加幻灯片。"""
        await office.execute("create_pptx", {
            "path": "edit_add.pptx",
            "slides": [{"title": "原有页", "body": "原有内容"}],
        })

        result = await office.execute("edit_pptx", {
            "path": "edit_add.pptx",
            "operations": [
                {"action": "add_slide", "title": "新增页", "body": "新增内容"},
            ],
        })
        assert result.get("operations") == 1

        read_result = await office.execute("read_pptx", {"path": "edit_add.pptx"})
        assert read_result["slide_count"] == 2

    @pytest.mark.asyncio
    async def test_edit_pptx_delete_slide(self, office: OfficeOps) -> None:
        """编辑 PPT — 删除幻灯片。"""
        await office.execute("create_pptx", {
            "path": "edit_del.pptx",
            "slides": [
                {"title": "第一页"},
                {"title": "第二页"},
                {"title": "第三页"},
            ],
        })

        result = await office.execute("edit_pptx", {
            "path": "edit_del.pptx",
            "operations": [
                {"action": "delete_slide", "slide_index": 1},
            ],
        })
        assert result.get("operations") == 1

        read_result = await office.execute("read_pptx", {"path": "edit_del.pptx"})
        assert read_result["slide_count"] == 2

    @pytest.mark.asyncio
    async def test_edit_pptx_replace_text(self, office: OfficeOps) -> None:
        """编辑 PPT — 文本替换。"""
        await office.execute("create_pptx", {
            "path": "edit_replace.pptx",
            "slides": [{"title": "Hello", "body": "World"}],
        })

        result = await office.execute("edit_pptx", {
            "path": "edit_replace.pptx",
            "operations": [
                {"action": "replace_text", "search": "Hello", "replace": "你好"},
            ],
        })
        assert result.get("operations") == 1

        read_result = await office.execute("read_pptx", {"path": "edit_replace.pptx"})
        all_text = " ".join(
            shape["text"]
            for slide in read_result["slides"]
            for shape in slide["shapes"]
        )
        assert "你好" in all_text

    @pytest.mark.asyncio
    async def test_edit_pptx_add_textbox(self, office: OfficeOps) -> None:
        """编辑 PPT — 添加文本框。"""
        await office.execute("create_pptx", {
            "path": "edit_textbox.pptx",
            "slides": [{"title": "测试"}],
        })

        result = await office.execute("edit_pptx", {
            "path": "edit_textbox.pptx",
            "operations": [
                {"action": "add_textbox", "slide_index": 0, "text": "新文本框", "left": 1, "top": 3},
            ],
        })
        assert result.get("operations") == 1

        read_result = await office.execute("read_pptx", {"path": "edit_textbox.pptx"})
        texts = [shape["text"] for shape in read_result["slides"][0]["shapes"]]
        assert "新文本框" in texts

    @pytest.mark.asyncio
    async def test_edit_pptx_add_image(self, office: OfficeOps) -> None:
        """编辑 PPT — 添加图片。"""
        # 先准备一张小图片
        img_path = Path(office._workspace) / "test_img.png"
        try:
            from PIL import Image
            img = Image.new("RGB", (100, 100), color="red")
            img.save(str(img_path))
        except ImportError:
            # 用一个最小的有效 PNG 文件代替
            import struct
            import zlib
            raw = zlib.compress(b"\x00" * 4)  # 1x1 像素 RGBA
            png = b"\x89PNG\r\n\x1a\n"
            png += struct.pack(">I", 13) + b"IHDR" + struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0) + b"\x00\x00\x00\x00"
            png += struct.pack(">I", len(raw)) + b"IDAT" + raw + b"\x00\x00\x00\x00"
            png += struct.pack(">I", 0) + b"IEND" + b"\xaeB`\x82"
            img_path.write_bytes(png)

        await office.execute("create_pptx", {
            "path": "edit_img.pptx",
            "slides": [{"title": "有图片的页面"}],
        })

        result = await office.execute("edit_pptx", {
            "path": "edit_img.pptx",
            "operations": [
                {"action": "add_image", "slide_index": 0, "image_path": "test_img.png"},
            ],
        })
        assert result.get("operations") == 1

    @pytest.mark.asyncio
    async def test_edit_pptx_invalid_index(self, office: OfficeOps) -> None:
        """编辑 PPT — 无效幻灯片索引。"""
        await office.execute("create_pptx", {
            "path": "edit_inv.pptx",
            "slides": [{"title": "一页"}],
        })

        result = await office.execute("edit_pptx", {
            "path": "edit_inv.pptx",
            "operations": [
                {"action": "delete_slide", "slide_index": 99},
            ],
        })
        # 操作本身不报错，但 details 里应有 error
        details = result.get("details", [])
        assert any("error" in d for d in details)

    @pytest.mark.asyncio
    async def test_edit_nonexistent_pptx(self, office: OfficeOps) -> None:
        result = await office.execute("edit_pptx", {
            "path": "no_file.pptx",
            "operations": [],
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_edit_pptx_unknown_operation(self, office: OfficeOps) -> None:
        """编辑 PPT — 未知操作类型。"""
        await office.execute("create_pptx", {
            "path": "edit_unk.pptx",
            "slides": [{"title": "测试"}],
        })

        result = await office.execute("edit_pptx", {
            "path": "edit_unk.pptx",
            "operations": [
                {"action": "nonexistent_op"},
            ],
        })
        details = result.get("details", [])
        assert any("error" in d for d in details)


# ======================================================================
# PDF 文本提取 — office_pdf
# ======================================================================


class TestPDFOps:
    """PDF 文本提取测试。"""

    @pytest.mark.asyncio
    async def test_read_nonexistent_pdf(self, office: OfficeOps) -> None:
        result = await office.execute("read_pdf_text", {"path": "no.pdf"})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_read_pdf_with_no_library(self, office: OfficeOps, monkeypatch: Any) -> None:
        """测试无 PDF 库时的降级处理。"""
        pdf_path = Path(office._workspace) / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        import importlib

        original_import = importlib.import_module

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name in ("fitz", "pdfminer.high_level"):
                raise ImportError(f"No module named '{name}'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(importlib, "import_module", mock_import)

        result = await office.execute("read_pdf_text", {"path": "test.pdf"})
        assert "error" in result or "pages" in result


# ======================================================================
# 集成测试
# ======================================================================


class TestOfficeOpsIntegration:
    """集成测试：跨工具协作。"""

    @pytest.mark.asyncio
    async def test_full_docx_workflow(self, office: OfficeOps) -> None:
        """完整的 Word 文档工作流：创建→追加→编辑→读取。"""
        await office.execute("create_docx", {
            "path": "workflow.docx",
            "title": "工作流测试",
            "headings": [{"level": 1, "text": "引言"}],
            "paragraphs": ["这是引言部分。"],
        })

        await office.execute("append_docx", {
            "path": "workflow.docx",
            "headings": [{"level": 1, "text": "正文"}],
            "paragraphs": ["正文内容1", "正文内容2"],
        })

        # 编辑：替换文本
        await office.execute("edit_docx", {
            "path": "workflow.docx",
            "search_replace": [{"search": "正文内容1", "replace": "已修改的内容"}],
        })

        result = await office.execute("read_docx", {"path": "workflow.docx"})
        all_texts = [p["text"] for p in result["paragraphs"]]
        assert "这是引言部分。" in all_texts
        assert "已修改的内容" in all_texts
        assert "正文内容2" in all_texts

    @pytest.mark.asyncio
    async def test_full_xlsx_workflow(self, office: OfficeOps) -> None:
        """完整的 Excel 工作流：创建→追加→编辑→读取。"""
        await office.execute("create_xlsx", {
            "path": "workflow.xlsx",
            "headers": ["项目", "状态"],
            "rows": [["项目A", "进行中"]],
        })

        await office.execute("append_xlsx", {
            "path": "workflow.xlsx",
            "rows": [["项目B", "已完成"], ["项目C", "待开始"]],
        })

        # 编辑：修改单元格值
        await office.execute("edit_xlsx", {
            "path": "workflow.xlsx",
            "cells": [{"row": 2, "col": 2, "value": "已完成"}],
        })

        result = await office.execute("read_xlsx", {"path": "workflow.xlsx"})
        assert result["row_count"] == 4  # 1 header + 3 data

    @pytest.mark.asyncio
    async def test_full_pptx_workflow(self, office: OfficeOps) -> None:
        """完整的 PPT 工作流：创建→编辑（添加/替换）→读取。"""
        await office.execute("create_pptx", {
            "path": "workflow.pptx",
            "slides": [
                {"title": "标题页", "body": "报告内容"},
                {"title": "第二页", "body": "详细说明"},
            ],
        })

        await office.execute("edit_pptx", {
            "path": "workflow.pptx",
            "operations": [
                {"action": "add_slide", "title": "新增页", "body": "新增内容"},
                {"action": "replace_text", "search": "报告内容", "replace": "更新后的报告"},
            ],
        })

        result = await office.execute("read_pptx", {"path": "workflow.pptx"})
        assert result["slide_count"] == 3

        all_text = " ".join(
            shape["text"]
            for slide in result["slides"]
            for shape in slide["shapes"]
        )
        assert "更新后的报告" in all_text

    @pytest.mark.asyncio
    async def test_workspace_isolation(self, tmp_path: Path) -> None:
        """验证不同 workspace 的隔离性。"""
        ws1 = tmp_path / "ws1"
        ws2 = tmp_path / "ws2"
        ws1.mkdir()
        ws2.mkdir()

        office1 = OfficeOps(workspace=str(ws1))
        office2 = OfficeOps(workspace=str(ws2))

        await office1.execute("create_docx", {
            "path": "unique.docx",
            "paragraphs": ["workspace1"],
        })
        await office2.execute("create_docx", {
            "path": "unique.docx",
            "paragraphs": ["workspace2"],
        })

        r1 = await office1.execute("read_docx", {"path": "unique.docx"})
        r2 = await office2.execute("read_docx", {"path": "unique.docx"})

        texts1 = [p["text"] for p in r1["paragraphs"]]
        texts2 = [p["text"] for p in r2["paragraphs"]]
        assert "workspace1" in texts1
        assert "workspace2" in texts2
        assert "workspace1" not in texts2
