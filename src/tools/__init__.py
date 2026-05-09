"""工具集包。"""

from src.tools.process_manager import ProcessManager
from src.tools.system_control import SystemControl

# 工具注册表：名称 → 类
TOOL_REGISTRY: dict[str, type] = {
    "system_control": SystemControl,
    "process_manager": ProcessManager,
}
