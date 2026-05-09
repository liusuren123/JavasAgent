"""PDF 文档操作子模块。

提供 PDF 文件的读取、创建、合并、页面提取能力。

依赖：
    - PyPDF2: PDF 读取、合并、页面提取（必须）
    - pypdfium2: PDF 文本提取（优先）
    - pdfminer.six: PDF 文本提取（回退）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path


# ======================================================================
# 页面大小预设
# ======================================================================

_PAGE_SIZES: dict[str, tuple[float, float]] = {
    "A4": (595.28, 841.89),
    "A3": (841.89, 1190.55),
    "A5": (419.53, 595.28),
    "Letter": (612, 792),
    "Legal": (612, 1008),
}


# ======================================================================
# 读取 PDF 文本
# ======================================================================


async def read_pdf_text(workspace: Path, params: dict) -> dict:
    """提取 PDF 文件中的文本内容。

    Params:
        path: 文件路径
        max_pages: 最大页数（默认 100）
    """
    try:
        path = safe_resolve_path(workspace, params["path"])
    except PathSafetyError as e:
        return {"error": str(e)}

    if not path.exists():
        return {"error": f"文件不存在: {path}"}

    max_pages = params.get("max_pages", 100)

    # 优先使用 pypdfium2（轻量、快速）
    try:
        import pypdfium2

        pdf = pypdfium2.PdfDocument(str(path))
        pages: list[dict[str, Any]] = []
        for i in range(min(len(pdf), max_pages)):
            page = pdf[i]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            textpage.close()
            page.close()
            pages.append({"page": i + 1, "text": text, "length": len(text)})
        pdf.close()

        total_text = "\n".join(p["text"] for p in pages)
        logger.info(f"读取 PDF (pypdfium2): {path} ({len(pages)} 页)")
        return {
            "path": str(path),
            "pages": pages,
            "page_count": len(pages),
            "total_text_length": len(total_text),
        }
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"pypdfium2 读取失败，尝试回退: {e}")

    # 回退方案：使用 pdfminer
    try:
        from pdfminer.high_level import extract_text

        text = extract_text(str(path), maxpages=max_pages)
        logger.info(f"读取 PDF (pdfminer): {path}")
        return {
            "path": str(path),
            "text": text,
            "total_text_length": len(text),
        }
    except ImportError:
        return {
            "error": "PDF 处理库未安装，请安装: pip install pypdfium2 或 pip install pdfminer.six"
        }
    except Exception as e:
        logger.error(f"读取 PDF 失败: {e}")
        return {"error": f"读取失败: {e}"}


# ======================================================================
# 创建 PDF
# ======================================================================


async def create_pdf(workspace: Path, params: dict) -> dict:
    """从文本内容创建 PDF 文件。

    Params:
        path: 输出文件路径
        content: 文本内容（支持换行符分隔段落）
        page_size: 页面大小（默认 A4），支持 A3/A4/A5/Letter/Legal
        font_size: 字体大小（默认 12）
        margin: 页边距（默认 72 磅 = 1 英寸）
    """
    try:
        path = safe_resolve_path(workspace, params["path"])
    except PathSafetyError as e:
        return {"error": str(e)}

    content: str = params.get("content", "")
    if not content:
        return {"error": "文本内容不能为空"}

    page_size_name = params.get("page_size", "A4")
    page_w, page_h = _PAGE_SIZES.get(page_size_name, _PAGE_SIZES["A4"])
    font_size = int(params.get("font_size", 12))
    margin = int(params.get("margin", 72))

    try:
        from reportlab.pdfgen import canvas as rlcanvas  # noqa: F401

        # reportlab 可用，使用它创建
        return await _create_pdf_reportlab(
            workspace, path, content, page_size_name, page_w, page_h,
            font_size, margin,
        )
    except ImportError:
        pass

    # 回退方案：提示安装 reportlab
    return {
        "error": "创建 PDF 需要 reportlab 库，请安装: pip install reportlab",
        "hint": "reportlab 支持文本创建、中文字体、自动换行等功能",
    }


async def _create_pdf_reportlab(
    workspace: Path,
    path: Path,
    content: str,
    page_size_name: str,
    page_w: float,
    page_h: float,
    font_size: int,
    margin: int,
) -> dict:
    """使用 reportlab 创建 PDF（支持中文需注册字体）。"""
    from reportlab.pdfgen import canvas as rlcanvas
    import io

    buf = io.BytesIO()
    c = rlcanvas.Canvas(buf, pagesize=(page_w, page_h))

    # 尝试注册中文字体
    font_name = "Helvetica"
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os

        # 尝试查找系统中的中文字体
        _cn_fonts = [
            ("C:/Windows/Fonts/msyh.ttc", "MSYH"),
            ("C:/Windows/Fonts/simsun.ttc", "SimSun"),
            ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
        ]
        for fpath, fname in _cn_fonts:
            if os.path.exists(fpath):
                pdfmetrics.registerFont(TTFont(fname, fpath))
                font_name = fname
                break
    except Exception:
        logger.debug("未找到中文字体，使用默认字体")

    # 文本分行处理
    paragraphs = content.split("\n")
    line_height = font_size * 1.5
    usable_width = page_w - 2 * margin
    y = page_h - margin

    # 简单的自动换行
    def _wrap_text(text: str, max_width: float) -> list[str]:
        """按字符宽度换行。"""
        if not text:
            return [""]
        from reportlab.pdfbase.pdfmetrics import stringWidth
        lines = []
        current = ""
        for ch in text:
            test = current + ch
            if stringWidth(test, font_name, font_size) > max_width:
                if current:
                    lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)
        return lines

    for para in paragraphs:
        wrapped = _wrap_text(para, usable_width)
        for line in wrapped:
            if y < margin:
                c.showPage()
                y = page_h - margin
            c.setFont(font_name, font_size)
            c.drawString(margin, y, line)
            y -= line_height
        # 段落间额外间距
        y -= line_height * 0.3

    c.save()
    buf.seek(0)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.read())
    logger.info(f"创建 PDF (reportlab): {path}")
    return {
        "path": str(path),
        "page_size": page_size_name,
        "font_size": font_size,
        "status": "created",
    }



# ======================================================================
# 合并 PDF
# ======================================================================


async def merge_pdfs(workspace: Path, params: dict) -> dict:
    """合并多个 PDF 文件为一个。

    Params:
        paths: 要合并的 PDF 文件路径列表
        output: 输出文件路径
    """
    paths_input = params.get("paths", [])
    if not paths_input:
        return {"error": "未提供要合并的文件路径列表"}

    if len(paths_input) < 2:
        return {"error": "至少需要 2 个文件才能合并"}

    try:
        output = safe_resolve_path(workspace, params["output"])
    except PathSafetyError as e:
        return {"error": str(e)}

    # 验证所有输入文件
    resolved_paths: list[Path] = []
    for p in paths_input:
        try:
            rp = safe_resolve_path(workspace, p)
        except PathSafetyError as e:
            return {"error": f"输入文件路径不安全: {e}"}
        if not rp.exists():
            return {"error": f"文件不存在: {rp}"}
        resolved_paths.append(rp)

    try:
        from PyPDF2 import PdfMerger

        merger = PdfMerger()
        for rp in resolved_paths:
            merger.append(str(rp))

        output.parent.mkdir(parents=True, exist_ok=True)
        merger.write(str(output))
        merger.close()

        logger.info(f"合并 PDF: {len(resolved_paths)} 个文件 -> {output}")
        return {
            "output": str(output),
            "merged_count": len(resolved_paths),
            "source_files": [str(p) for p in resolved_paths],
            "status": "merged",
        }
    except ImportError:
        return {"error": "合并 PDF 需要 PyPDF2 库，请安装: pip install PyPDF2"}
    except Exception as e:
        logger.error(f"合并 PDF 失败: {e}")
        return {"error": f"合并失败: {e}"}


# ======================================================================
# 提取 PDF 页面
# ======================================================================


async def extract_pages(workspace: Path, params: dict) -> dict:
    """从 PDF 中提取指定页码范围的页面，输出为新的 PDF。

    Params:
        path: 源 PDF 文件路径
        output: 输出文件路径
        start: 起始页码（从 1 开始，默认 1）
        end: 结束页码（包含，默认到最后一页）
    """
    try:
        path = safe_resolve_path(workspace, params["path"])
    except PathSafetyError as e:
        return {"error": str(e)}

    if not path.exists():
        return {"error": f"文件不存在: {path}"}

    try:
        output = safe_resolve_path(workspace, params["output"])
    except PathSafetyError as e:
        return {"error": str(e)}

    try:
        from PyPDF2 import PdfReader, PdfWriter

        reader = PdfReader(str(path))
        total_pages = len(reader.pages)

        start = int(params.get("start", 1))
        end = int(params.get("end", total_pages))

        # 校验页码范围
        if start < 1 or start > total_pages:
            return {"error": f"起始页码 {start} 超出范围 (1-{total_pages})"}
        if end < start:
            return {"error": f"结束页码 ({end}) 不能小于起始页码 ({start})"}
        if end > total_pages:
            end = total_pages

        writer = PdfWriter()
        for i in range(start - 1, end):
            writer.add_page(reader.pages[i])

        output.parent.mkdir(parents=True, exist_ok=True)
        with open(str(output), "wb") as f:
            writer.write(f)

        extracted = end - start + 1
        logger.info(f"提取 PDF 页面: {path} 第 {start}-{end} 页 -> {output}")
        return {
            "output": str(output),
            "source": str(path),
            "page_range": f"{start}-{end}",
            "extracted_pages": extracted,
            "total_source_pages": total_pages,
            "status": "extracted",
        }
    except ImportError:
        return {"error": "提取页面需要 PyPDF2 库，请安装: pip install PyPDF2"}
    except Exception as e:
        logger.error(f"提取 PDF 页面失败: {e}")
        return {"error": f"提取失败: {e}"}
