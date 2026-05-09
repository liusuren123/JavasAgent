"""场景检测器组件。

包含 ActivityDetector（活动检测）和 SceneClassifier（场景分类器），
从 context_engine.py 拆分出来以控制文件大小。
"""

from __future__ import annotations

import re
import time
from typing import Any

from loguru import logger

from src.perception.context_models import ActivityInfo, SceneType

# ---------------------------------------------------------------------------
# 应用场景关键词映射
# ---------------------------------------------------------------------------
_APP_SCENE_RULES: list[tuple[list[str], SceneType]] = [
    # IDE / 编辑器 → 编码
    (
        [
            "code", "vscode", "devenv", "idea", "pycharm", "webstorm",
            "clion", "rider", "goland", "atom", "sublime", "vim", "nvim",
            "nvim-qt", "emacs", "cursor", "windsurf", "fleet",
        ],
        SceneType.CODING,
    ),
    # 浏览器 → 浏览
    (
        [
            "chrome", "firefox", "msedge", "edge", "safari", "opera",
            "brave", "vivaldi", "arc", "zen", "tor", "iexplore",
        ],
        SceneType.BROWSING,
    ),
    # 会议 / 通讯 → 会议
    (
        [
            "zoom", "teams", "lark", "feishu", "dingtalk", "ding",
            "wechat", "weixin", "skype", "webex", "slack", "discord",
            "tencent_meeting", "voovmeeting", "googlemeet", "meeting",
            "腾讯会议", "飞书", "钉钉",
        ],
        SceneType.MEETING,
    ),
    # 写作 / 笔记 → 写作
    (
        [
            "notion", "obsidian", "typora", "marktext", "word", "onenote",
            "evernote", "wps", "bear", "ulysses", "ia writer",
            "scrivener", "logseq", "siyuan", "思源",
        ],
        SceneType.WRITING,
    ),
    # 游戏 → 游戏
    (
        [
            "steam", "epic", "origin", "ubisoft", "riot", "minecraft",
            "leagueclient", "overwatch", "csgo", "dota2", "genshin",
            "原神", "game",
        ],
        SceneType.GAMING,
    ),
    # 媒体播放 → 媒体
    (
        [
            "vlc", "potplayer", "potplayermini", "mpc-hc", "mpc-be",
            "spotify", "netease_cloudmusic", "qqmusic", "kugou", "foobar2000",
            "aimp", "itunes", "bilibili", "youtube",
            "plex", "jellyfin", "kodi", "mpv",
        ],
        SceneType.MEDIA,
    ),
]

# 窗口标题中的场景提示词
_TITLE_SCENE_HINTS: list[tuple[list[str], SceneType]] = [
    (["会议", "meeting", "通话", "call", "视频", "直播"], SceneType.MEETING),
    (["游戏", "game", "play"], SceneType.GAMING),
    (["电影", "movie", "视频播放", "episode", "anime"], SceneType.MEDIA),
]


# ---------------------------------------------------------------------------
# ActivityDetector
# ---------------------------------------------------------------------------
class ActivityDetector:
    """检测用户当前活跃的应用程序和窗口标题。

    在 Windows 平台上使用 ctypes Win32 API 获取前台窗口信息；
    在其他平台或 API 不可用时返回空信息（IDLE 状态）。
    """

    def __init__(self) -> None:
        self._available = False
        self._user32: Any = None
        self._kernel32: Any = None
        self._psapi: Any = None
        self._init_platform()

    def _init_platform(self) -> None:
        """初始化平台相关的窗口检测能力。"""
        try:
            import ctypes
            import ctypes.wintypes  # type: ignore[attr-defined]

            self._user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            self._kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            self._psapi = ctypes.windll.psapi  # type: ignore[attr-defined]
            self._available = True
            logger.debug("ActivityDetector: Win32 API 初始化成功")
        except (ImportError, AttributeError, OSError):
            self._available = False
            logger.debug("ActivityDetector: Win32 API 不可用，将返回 IDLE 状态")

    async def detect(self) -> ActivityInfo:
        """检测当前前台窗口的活动信息。

        Returns:
            ActivityInfo 包含应用名、窗口标题等信息
        """
        if not self._available:
            return ActivityInfo(
                app_name="",
                window_title="",
                pid=0,
                timestamp=time.time(),
            )

        try:
            import ctypes
            import ctypes.wintypes  # type: ignore[attr-defined]

            hwnd = self._user32.GetForegroundWindow()
            if not hwnd:
                return ActivityInfo(
                    app_name="",
                    window_title="",
                    pid=0,
                    timestamp=time.time(),
                )

            # 获取窗口标题
            length = self._user32.GetWindowTextLengthW(hwnd)
            buf_size = max(length + 1, 1)
            buf = ctypes.create_unicode_buffer(buf_size)
            self._user32.GetWindowTextW(hwnd, buf, buf_size)
            title = buf.value

            # 获取进程 ID
            pid = ctypes.wintypes.DWORD()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid_val = pid.value

            # 获取进程名
            app_name = self._get_process_name(pid_val)

            return ActivityInfo(
                app_name=app_name,
                window_title=title,
                pid=pid_val,
                timestamp=time.time(),
            )
        except Exception as e:
            logger.error(f"ActivityDetector 检测失败: {e}")
            return ActivityInfo(
                app_name="",
                window_title="",
                pid=0,
                timestamp=time.time(),
            )

    def _get_process_name(self, pid: int) -> str:
        """获取进程名称。"""
        if pid == 0:
            return ""
        try:
            import ctypes

            PROCESS_QUERY_INFORMATION = 0x0400
            PROCESS_VM_READ = 0x0010
            handle = self._kernel32.OpenProcess(
                PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
            )
            if not handle:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(260)
                if self._psapi.GetModuleBaseNameW(handle, None, buf, 260):
                    name = buf.value.lower()
                    if name.endswith(".exe"):
                        name = name[:-4]
                    return name
                return ""
            finally:
                self._kernel32.CloseHandle(handle)
        except Exception:
            return ""


# ---------------------------------------------------------------------------
# SceneClassifier
# ---------------------------------------------------------------------------
class SceneClassifier:
    """基于窗口/应用名称分类当前场景。

    使用关键词匹配策略，结合应用名和窗口标题进行场景判断。
    支持自定义规则扩展。
    """

    def __init__(
        self,
        app_rules: list[tuple[list[str], SceneType]] | None = None,
        title_hints: list[tuple[list[str], SceneType]] | None = None,
    ) -> None:
        self._app_rules = app_rules or _APP_SCENE_RULES
        self._title_hints = title_hints or _TITLE_SCENE_HINTS

    def classify(self, activity: ActivityInfo) -> tuple[SceneType, float]:
        """分类当前场景。

        Args:
            activity: 当前活动信息

        Returns:
            (scene_type, confidence) 元组，置信度 0-1
        """
        app_name = activity.app_name.lower()
        window_title = activity.window_title.lower()

        # 无活跃窗口 → IDLE
        if not app_name and not window_title:
            return SceneType.IDLE, 0.95

        # 第一轮：应用名精确匹配
        for keywords, scene in self._app_rules:
            for kw in keywords:
                if kw in app_name:
                    return scene, 0.85

        # 第二轮：窗口标题提示
        for keywords, scene in self._title_hints:
            for kw in keywords:
                if kw in window_title:
                    return scene, 0.75

        # 默认：UNKNOWN，低置信度
        return SceneType.UNKNOWN, 0.3

    def classify_with_title_keywords(
        self, activity: ActivityInfo, keywords: list[str]
    ) -> tuple[SceneType, float]:
        """使用自定义关键词进行场景分类。

        Args:
            activity: 当前活动信息
            keywords: 关键词列表

        Returns:
            (scene_type, confidence) 元组
        """
        window_title = activity.window_title.lower()
        app_name = activity.app_name.lower()
        combined = f"{app_name} {window_title}"

        match_count = sum(1 for kw in keywords if kw.lower() in combined)
        if match_count == 0:
            return self.classify(activity)

        confidence = min(0.5 + 0.2 * match_count, 0.95)
        for rule_keywords, scene in self._app_rules:
            for kw in rule_keywords:
                if kw in combined:
                    return scene, confidence

        return SceneType.UNKNOWN, confidence
