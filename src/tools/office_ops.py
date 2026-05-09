"""办公自动化工具集（门面模块）。

提供 Word/Excel/PPT/PDF 文档操作的统一入口。
实际实现委托给各子模块：office_docx / office_xlsx / office_pptx / office_pdf。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from src.tools.office_docx import (
    append_docx,
    create_docx,
    edit_docx,
    read_docx,
)
from src.tools.office_pdf import read_pdf_text
from src.tools.office_pptx import (
    create_pptx,
    edit_pptx,
    read_pptx,
)
from src.tools.office_xlsx import (
    append_xlsx,
    create_xlsx,
    edit_xlsx,
    read_xlsx,
)


class OfficeOps:
    """办公自动化工具集（门面）。

    支持 Word (.docx)、Excel (.xlsx)、PowerPoint (.pptx)、PDF 的
    创建、读取、追加、编辑操作。

    Usage::

        office = OfficeOps(workspace="/path/to/workspace")
        result = await office.execute("read_docx", {"path": "report.docx"})
    """

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = Path(workspace) if workspace else Path.cwd()

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行办公自动化操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果字典
        """
        handlers = {
            # Word
            "read_docx": read_docx,
            "create_docx": create_docx,
            "append_docx": append_docx,
            "edit_docx": edit_docx,
            # Excel
            "read_xlsx": read_xlsx,
            "create_xlsx": create_xlsx,
            "append_xlsx": append_xlsx,
            "edit_xlsx": edit_xlsx,
            # PowerPoint
            "read_pptx": read_pptx,
            "create_pptx": create_pptx,
            "edit_pptx": edit_pptx,
            # PDF
            "read_pdf_text": read_pdf_text,
        }

        handler = handlers.get(action)
        if handler is None:
            logger.error(f"未知操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(handlers.keys()),
            }

        return await handler(self._workspace, params)
