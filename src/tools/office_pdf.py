"""PDF 文本提取子模块。

提供 PDF 文件的文本读取能力。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import PathSafetyError, safe_resolve_path


# ======================================================================
# 操作实现
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

    # 优先使用 PyMuPDF (fitz)，回退到 pdfminer
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(str(path))
        pages: list[dict[str, Any]] = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            text = page.get_text()
            pages.append({"page": i + 1, "text": text, "length": len(text)})
        doc.close()

        total_text = "\n".join(p["text"] for p in pages)
        logger.info(f"读取 PDF (PyMuPDF): {path} ({len(pages)} 页)")
        return {
            "path": str(path),
            "pages": pages,
            "page_count": len(pages),
            "total_text_length": len(total_text),
        }
    except ImportError:
        pass

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
            "error": "PDF 处理库未安装，请安装: pip install PyMuPDF 或 pip install pdfminer.six"
        }
    except Exception as e:
        logger.error(f"读取 PDF 失败: {e}")
        return {"error": f"读取失败: {e}"}
