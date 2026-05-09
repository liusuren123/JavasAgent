"""工具集包。

提供 TOOL_REGISTRY（名称 → 工具类）和 TOOL_METADATA（元数据），
供 ToolRegistry 自动注册使用。
"""

from src.tools.aftereffects_control import AfterEffectsControl
from src.tools.archive_ops import (
    compress_files,
    decompress_archive,
    extract_single,
    get_archive_info,
    list_archive,
)
from src.tools.browser_control import BrowserControl
from src.tools.calendar_ops import CalendarOps
from src.tools.clipboard_ops import ClipboardOps
from src.tools.code_dev import CodeDev
from src.tools.creative_tools import CreativeTools
from src.tools.email_ops import EmailOps
from src.tools.image_ops import ImageOps
from src.tools.office_ops import OfficeOps
from src.tools.photoshop_control import PhotoshopControl
from src.tools.premiere_control import PremiereControl
from src.tools.process_manager import ProcessManager
from src.tools.system_control import SystemControl
from src.tools.network_ops import NetworkOps
from src.tools.smart_scheduler import SmartScheduler
from src.tools.voice_ops import VoiceOps


class _ToolMeta:
    """工具元数据。"""

    __slots__ = ("description", "aliases", "requires_llm")

    def __init__(
        self,
        description: str = "",
        aliases: list[str] | None = None,
        requires_llm: bool = False,
    ) -> None:
        self.description = description
        self.aliases = aliases or []
        self.requires_llm = requires_llm


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
    "calendar_ops": CalendarOps,
    "photoshop_control": PhotoshopControl,
    "premiere_control": PremiereControl,
    "aftereffects_control": AfterEffectsControl,
    "voice_ops": VoiceOps,
    "clipboard": ClipboardOps,
    "network_ops": NetworkOps,
    "smart_scheduler": SmartScheduler,
}

# 工具元数据：名称 → _ToolMeta
# aliases 表示同一工具实例会以多个名称注册
# requires_llm 表示初始化时需要传入 llm_client
TOOL_METADATA: dict[str, _ToolMeta] = {
    "system_control": _ToolMeta(
        description="系统控制：文件操作、进程管理、窗口控制、Shell 命令执行",
        aliases=["shell"],
    ),
    "process_manager": _ToolMeta(
        description="进程管理：启动、监控、终止系统进程",
    ),
    "code_dev": _ToolMeta(
        description="代码开发：代码生成、调试、测试、Git 操作、依赖管理",
        requires_llm=True,
    ),
    "office_ops": _ToolMeta(
        description="办公自动化：Word/Excel/PPT/PDF 文档操作",
    ),
    "browser_control": _ToolMeta(
        description="浏览器控制：网页自动化、截图、填表",
    ),
    "email_ops": _ToolMeta(
        description="邮件管理：邮件收发、搜索、文件夹管理",
    ),
    "calendar_ops": _ToolMeta(
        description="日历管理：日程查询、创建、提醒",
    ),
    "creative_tools": _ToolMeta(
        description="创意工具：灵感生成、头脑风暴",
    ),
    "image_ops": _ToolMeta(
        description="图片处理：裁剪、缩放、格式转换、水印、滤镜",
    ),
    "voice_ops": _ToolMeta(
        description="语音处理：语音识别（STT）、语音合成（TTS）",
    ),
    "clipboard": _ToolMeta(
        description="剪贴板操作：复制、粘贴、读取剪贴板内容",
    ),
    "photoshop_control": _ToolMeta(
        description="Photoshop 控制：自动化图片编辑与批处理",
    ),
    "premiere_control": _ToolMeta(
        description="Premiere Pro 控制：视频编辑自动化",
    ),
    "aftereffects_control": _ToolMeta(
        description="After Effects 控制：特效与合成自动化",
    ),
    "network_ops": _ToolMeta(
        description="网络操作：HTTP 请求、文件下载、网络检测、API 调用",
    ),
    "smart_scheduler": _ToolMeta(
        description="智能调度：时间安排、日程优化、冲突检测、每日计划生成",
    ),
}
