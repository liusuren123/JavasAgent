"""MacroRecorder 数据模型。

定义宏录制与回放模块使用的所有数据结构，包括事件类型、
宏事件、宏步骤、完整宏定义，以及录制状态和回放速度枚举。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class MacroStatus(str, Enum):
    """宏录制/回放状态。"""

    RECORDING = "recording"
    """正在录制中。"""

    STOPPED = "stopped"
    """已停止（空闲状态）。"""

    PLAYING = "playing"
    """正在回放中。"""


class PlaybackSpeed(str, Enum):
    """回放速度倍率。"""

    HALF = "0.5x"
    """0.5 倍速（慢放）。"""

    NORMAL = "1x"
    """1 倍速（正常）。"""

    DOUBLE = "2x"
    """2 倍速。"""

    QUAD = "4x"
    """4 倍速。"""

    @property
    def multiplier(self) -> float:
        """返回速度倍率的浮点数值。"""
        mapping: dict[str, float] = {
            "0.5x": 0.5,
            "1x": 1.0,
            "2x": 2.0,
            "4x": 4.0,
        }
        return mapping[self.value]


class MacroEventType(str, Enum):
    """宏事件类型。"""

    MOUSE_MOVE = "mouse_move"
    """鼠标移动。"""

    MOUSE_CLICK = "mouse_click"
    """鼠标点击（按下/释放）。"""

    MOUSE_SCROLL = "mouse_scroll"
    """鼠标滚轮。"""

    KEY_PRESS = "key_press"
    """键盘按键按下。"""

    KEY_RELEASE = "key_release"
    """键盘按键释放。"""


class MouseButton(str, Enum):
    """鼠标按钮。"""

    LEFT = "left"
    MIDDLE = "middle"
    RIGHT = "right"


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------


class MacroEvent(BaseModel):
    """单个宏事件。

    记录鼠标或键盘的一个离散操作，包含事件类型、坐标、按键信息
    以及相对于前一个事件的延迟（毫秒）。

    Attributes:
        event_type: 事件类型
        x: 鼠标 X 坐标（鼠标事件有效）
        y: 鼠标 Y 坐标（鼠标事件有效）
        button: 鼠标按钮（鼠标点击事件有效）
        pressed: 按下/释放（鼠标点击事件: True=按下, False=释放）
        key: 键盘按键（键盘事件有效，pynput key 的字符串表示）
        scroll_dx: 水平滚动量
        scroll_dy: 垂直滚动量
        delay_ms: 与前一个事件的间隔（毫秒），首个事件为 0
        timestamp: 事件发生时的绝对时间戳（录制时记录）
    """

    event_type: MacroEventType
    x: int | None = None
    y: int | None = None
    button: MouseButton | None = None
    pressed: bool | None = None
    key: str | None = None
    scroll_dx: int = 0
    scroll_dy: int = 0
    delay_ms: float = 0.0
    timestamp: float = 0.0


class MacroStep(BaseModel):
    """一个完整的宏步骤。

    一个步骤通常由一组相关事件组成（例如"鼠标按下 + 释放"算一个完整点击），
    可附带参数描述。

    Attributes:
        description: 步骤描述（可选）
        events: 该步骤包含的事件列表
        params: 附加参数键值对
    """

    description: str = ""
    events: list[MacroEvent] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)


class MacroDefinition(BaseModel):
    """完整宏定义。

    一个宏由名称、描述、步骤列表以及元信息组成，可序列化为 JSON
    并通过 ``MacroRecorder`` 保存/加载。

    Attributes:
        name: 宏名称
        description: 宏描述
        steps: 步骤列表（每个步骤包含多个事件）
        events: 扁平化事件列表（录制时直接使用）
        created_at: 创建时间
        updated_at: 最后更新时间
        hotkey: 绑定的热键（可选，如 ``<ctrl>+<alt>+m``）
        version: 宏格式版本号
    """

    name: str = "Untitled Macro"
    description: str = ""
    steps: list[MacroStep] = Field(default_factory=list)
    events: list[MacroEvent] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    hotkey: str | None = None
    version: str = "1.0"
