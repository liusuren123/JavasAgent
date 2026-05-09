"""工具集包。"""

from src.tools.browser_control import BrowserControl
from src.tools.code_dev import CodeDev
from src.tools.creative_tools import CreativeTools
from src.tools.email_ops import EmailOps
from src.tools.image_ops import ImageOps
from src.tools.office_ops import OfficeOps
from src.tools.photoshop_control import PhotoshopControl
from src.tools.premiere_control import PremiereControl
from src.tools.process_manager import ProcessManager
from src.tools.system_control import SystemControl

# 工具注册表：名称 → 类
TOOL_REGISTRY: dict[str, type] = {
    "system_control": SystemControl,
    "process_manager": ProcessManager,
    "browser_control": BrowserControl,
    "code_dev": CodeDev,
    "creative_tools": CreativeTools,
    "image_ops": ImageOps,
    "office_ops": OfficeOps,
    "email_ops": EmailOps,
    "photoshop_control": PhotoshopControl,
    "premiere_control": PremiereControl,
}
