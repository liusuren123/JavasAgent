"""MacroRecorder 宏录制与回放核心实现。

提供鼠标/键盘事件的录制、保存、加载和回放功能。
录制使用 ``pynput`` 监听输入事件，回放使用 ``pyautogui`` 执行操作。

使用示例::

    recorder = MacroRecorder()
    await recorder.start_recording()
    # ... 用户操作 ...
    macro = await recorder.stop_recording()
    await recorder.save_macro(macro, "macros/my_macro.json")

    macro = await recorder.load_macro("macros/my_macro.json")
    await recorder.playback(macro, speed=PlaybackSpeed.NORMAL, loop_count=1)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.tools.macro_models import (
    MacroDefinition,
    MacroEvent,
    MacroEventType,
    MacroStatus,
    MouseButton,
    PlaybackSpeed,
)

# ---------------------------------------------------------------------------
# pynput / pyautogui 延迟导入（方便测试时 mock）
# ---------------------------------------------------------------------------

try:
    from pynput import keyboard, mouse  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    keyboard = None  # type: ignore[assignment]
    mouse = None  # type: ignore[assignment]
    logger.warning("pynput 未安装，录制功能不可用")

try:
    import pyautogui  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover
    pyautogui = None  # type: ignore[assignment]
    logger.warning("pyautogui 未安装，回放功能不可用")


class MacroRecorder:
    """宏录制与回放器。

    通过 ``pynput`` 监听鼠标和键盘事件来录制宏，通过 ``pyautogui``
    执行回放。支持保存/加载 JSON 格式的宏文件、速度调节和循环回放。

    Attributes:
        status: 当前状态（录制中 / 已停止 / 回放中）
        _events: 录制期间收集的原始事件
        _start_time: 录制开始时间
        _last_event_time: 上一次事件的时间戳
        _mouse_listener: 鼠标监听器
        _keyboard_listener: 键盘监听器
    """

    def __init__(self) -> None:
        """初始化 MacroRecorder。"""
        self.status: MacroStatus = MacroStatus.STOPPED
        self._events: list[MacroEvent] = []
        self._start_time: float = 0.0
        self._last_event_time: float = 0.0
        self._mouse_listener: Any | None = None
        self._keyboard_listener: Any | None = None

    # ------------------------------------------------------------------
    # 录制
    # ------------------------------------------------------------------

    async def start_recording(self) -> None:
        """开始录制鼠标和键盘事件。

        启动 pynput 的鼠标和键盘 Listener。录制期间所有事件会被
        捕获并保存到内部列表。调用 ``stop_recording()`` 停止。

        Raises:
            RuntimeError: 如果已经在录制中或回放中
            ImportError: 如果 pynput 未安装
        """
        if self.status == MacroStatus.RECORDING:
            raise RuntimeError("已经在录制中")
        if self.status == MacroStatus.PLAYING:
            raise RuntimeError("回放中，无法开始录制")

        if mouse is None or keyboard is None:
            raise ImportError("pynput 未安装，请执行 pip install pynput")

        self._events.clear()
        self._start_time = time.monotonic()
        self._last_event_time = self._start_time
        self.status = MacroStatus.RECORDING
        logger.info("宏录制已开始")

        # 鼠标监听
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
            on_scroll=self._on_mouse_scroll,
        )
        self._mouse_listener.start()

        # 键盘监听
        self._keyboard_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._keyboard_listener.start()

    async def stop_recording(self) -> MacroDefinition:
        """停止录制并返回宏定义。

        停止 pynput 的监听器，将录制期间收集的事件封装为
        ``MacroDefinition`` 返回。

        Returns:
            MacroDefinition: 包含所有录制事件的宏定义

        Raises:
            RuntimeError: 如果当前未在录制
        """
        if self.status != MacroStatus.RECORDING:
            raise RuntimeError("当前未在录制")

        # 停止监听器
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None
        if self._keyboard_listener is not None:
            self._keyboard_listener.stop()
            self._keyboard_listener = None

        self.status = MacroStatus.STOPPED
        logger.info(f"宏录制已停止，共录制 {len(self._events)} 个事件")

        macro = MacroDefinition(
            name="Recorded Macro",
            description=f"自动录制宏，包含 {len(self._events)} 个事件",
            events=list(self._events),
        )
        return macro

    # ------------------------------------------------------------------
    # pynput 回调
    # ------------------------------------------------------------------

    def _calc_delay(self) -> float:
        """计算与上一个事件的延迟（毫秒）。"""
        now = time.monotonic()
        delay = (now - self._last_event_time) * 1000.0
        self._last_event_time = now
        return delay

    def _on_mouse_move(self, x: int, y: int) -> None:
        """鼠标移动回调。"""
        if self.status != MacroStatus.RECORDING:
            return
        self._events.append(
            MacroEvent(
                event_type=MacroEventType.MOUSE_MOVE,
                x=x,
                y=y,
                delay_ms=self._calc_delay(),
                timestamp=time.time(),
            )
        )

    def _on_mouse_click(
        self, x: int, y: int, button: Any, pressed: bool
    ) -> None:
        """鼠标点击回调。"""
        if self.status != MacroStatus.RECORDING:
            return
        btn_str = str(button).replace("Button.", "")
        btn = MouseButton.LEFT  # 默认
        for mb in MouseButton:
            if mb.value == btn_str:
                btn = mb
                break
        self._events.append(
            MacroEvent(
                event_type=MacroEventType.MOUSE_CLICK,
                x=x,
                y=y,
                button=btn,
                pressed=pressed,
                delay_ms=self._calc_delay(),
                timestamp=time.time(),
            )
        )

    def _on_mouse_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        """鼠标滚轮回调。"""
        if self.status != MacroStatus.RECORDING:
            return
        self._events.append(
            MacroEvent(
                event_type=MacroEventType.MOUSE_SCROLL,
                x=x,
                y=y,
                scroll_dx=dx,
                scroll_dy=dy,
                delay_ms=self._calc_delay(),
                timestamp=time.time(),
            )
        )

    def _on_key_press(self, key: Any) -> None:
        """键盘按下回调。"""
        if self.status != MacroStatus.RECORDING:
            return
        key_str = self._key_to_str(key)
        self._events.append(
            MacroEvent(
                event_type=MacroEventType.KEY_PRESS,
                key=key_str,
                delay_ms=self._calc_delay(),
                timestamp=time.time(),
            )
        )

    def _on_key_release(self, key: Any) -> None:
        """键盘释放回调。"""
        if self.status != MacroStatus.RECORDING:
            return
        key_str = self._key_to_str(key)
        self._events.append(
            MacroEvent(
                event_type=MacroEventType.KEY_RELEASE,
                key=key_str,
                delay_ms=self._calc_delay(),
                timestamp=time.time(),
            )
        )

    @staticmethod
    def _key_to_str(key: Any) -> str:
        """将 pynput 的 key 对象转为字符串。"""
        try:
            if hasattr(key, "char") and key.char is not None:
                return key.char
            if hasattr(key, "name"):
                return str(key.name)
            return str(key)
        except Exception:
            return str(key)

    # ------------------------------------------------------------------
    # 回放
    # ------------------------------------------------------------------

    async def playback(
        self,
        macro: MacroDefinition,
        speed: PlaybackSpeed = PlaybackSpeed.NORMAL,
        loop_count: int = 1,
    ) -> None:
        """回放宏。

        按照录制的事件顺序，使用 pyautogui 执行鼠标和键盘操作。
        支持速度调节和循环回放。

        Args:
            macro: 要回放的宏定义
            speed: 回放速度倍率，默认 1x
            loop_count: 循环回放次数，默认 1

        Raises:
            RuntimeError: 如果正在录制
            ImportError: 如果 pyautogui 未安装
            ValueError: 如果宏没有事件可回放
        """
        if self.status == MacroStatus.RECORDING:
            raise RuntimeError("录制中，无法回放")
        if pyautogui is None:
            raise ImportError("pyautogui 未安装，请执行 pip install pyautogui")
        if not macro.events:
            raise ValueError("宏中没有事件可回放")

        self.status = MacroStatus.PLAYING
        speed_mult = speed.multiplier
        logger.info(
            f"开始回放宏 '{macro.name}'，"
            f"共 {len(macro.events)} 个事件，"
            f"速度 {speed.value}，循环 {loop_count} 次"
        )

        try:
            for loop_idx in range(loop_count):
                if loop_idx > 0:
                    logger.debug(f"回放循环 {loop_idx + 1}/{loop_count}")
                for evt in macro.events:
                    if self.status != MacroStatus.PLAYING:
                        logger.info("回放被中断")
                        return

                    # 等待延迟
                    if evt.delay_ms > 0:
                        await asyncio.sleep(evt.delay_ms / 1000.0 / speed_mult)

                    await self._replay_event(evt)
        finally:
            self.status = MacroStatus.STOPPED
            logger.info(f"宏 '{macro.name}' 回放完成")

    async def _replay_event(self, event: MacroEvent) -> None:
        """回放单个事件。

        Args:
            event: 要回放的宏事件
        """
        if pyautogui is None:
            return

        try:
            if event.event_type == MacroEventType.MOUSE_MOVE:
                if event.x is not None and event.y is not None:
                    pyautogui.moveTo(event.x, event.y)

            elif event.event_type == MacroEventType.MOUSE_CLICK:
                if event.x is not None and event.y is not None:
                    button = event.button.value if event.button else "left"
                    if event.pressed:
                        pyautogui.mouseDown(event.x, event.y, button=button)
                    else:
                        pyautogui.mouseUp(event.x, event.y, button=button)

            elif event.event_type == MacroEventType.MOUSE_SCROLL:
                if event.x is not None and event.y is not None:
                    pyautogui.moveTo(event.x, event.y)
                pyautogui.scroll(event.scroll_dy)

            elif event.event_type == MacroEventType.KEY_PRESS:
                if event.key:
                    key_name = self._normalize_key(event.key)
                    if key_name:
                        pyautogui.keyDown(key_name)

            elif event.event_type == MacroEventType.KEY_RELEASE:
                if event.key:
                    key_name = self._normalize_key(event.key)
                    if key_name:
                        pyautogui.keyUp(key_name)

        except Exception as exc:
            logger.warning(f"回放事件失败: {event.event_type} - {exc}")

    @staticmethod
    def _normalize_key(key_str: str) -> str:
        """将录制的按键名称转换为 pyautogui 可接受的名称。

        pynput 和 pyautogui 的按键命名略有不同，此方法做映射。
        """
        key_mapping: dict[str, str] = {
            "space": "space",
            "enter": "enter",
            "return": "enter",
            "tab": "tab",
            "backspace": "backspace",
            "delete": "delete",
            "esc": "escape",
            "escape": "escape",
            "shift": "shift",
            "shift_l": "shiftleft",
            "shift_r": "shiftright",
            "ctrl": "ctrl",
            "ctrl_l": "ctrlleft",
            "ctrl_r": "ctrlright",
            "alt": "alt",
            "alt_l": "altleft",
            "alt_r": "altright",
            "cmd": "win",
            "cmd_l": "winleft",
            "cmd_r": "winright",
            "up": "up",
            "down": "down",
            "left": "left",
            "right": "right",
            "home": "home",
            "end": "end",
            "page_up": "pageup",
            "page_down": "pagedown",
            "caps_lock": "capslock",
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4",
            "f5": "f5", "f6": "f6", "f7": "f7", "f8": "f8",
            "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
        }
        lower_key = key_str.lower().strip("'")
        return key_mapping.get(lower_key, key_str)

    # ------------------------------------------------------------------
    # 文件操作
    # ------------------------------------------------------------------

    async def save_macro(self, macro: MacroDefinition, filepath: str) -> str:
        """保存宏到 JSON 文件。

        Args:
            macro: 要保存的宏定义
            filepath: 目标文件路径（.json）

        Returns:
            str: 实际保存的绝对路径

        Raises:
            ValueError: 文件路径为空
        """
        if not filepath:
            raise ValueError("文件路径不能为空")

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = macro.model_dump(mode="json")
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        abs_path = str(path.resolve())
        logger.info(f"宏已保存到: {abs_path}")
        return abs_path

    async def load_macro(self, filepath: str) -> MacroDefinition:
        """从文件加载宏。

        Args:
            filepath: JSON 宏文件路径

        Returns:
            MacroDefinition: 加载的宏定义

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 文件内容无法解析
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"宏文件不存在: {filepath}")

        content = path.read_text(encoding="utf-8")
        data = json.loads(content)
        macro = MacroDefinition.model_validate(data)
        logger.info(f"已加载宏: {macro.name} ({len(macro.events)} 个事件)")
        return macro

    async def list_macros(self, directory: str = "macros") -> list[dict[str, Any]]:
        """列出目录下所有宏文件。

        扫描指定目录下的 ``.json`` 文件，尝试解析为宏定义并返回
        摘要信息（名称、事件数、创建时间、文件路径）。

        Args:
            directory: 要扫描的目录路径

        Returns:
            list[dict]: 宏文件摘要列表，每项包含 name / event_count / created_at / filepath
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            logger.warning(f"宏目录不存在: {directory}")
            return []

        macros: list[dict[str, Any]] = []
        for file_path in sorted(dir_path.glob("*.json")):
            try:
                content = file_path.read_text(encoding="utf-8")
                data = json.loads(content)
                macro = MacroDefinition.model_validate(data)
                macros.append({
                    "name": macro.name,
                    "event_count": len(macro.events),
                    "created_at": macro.created_at,
                    "filepath": str(file_path.resolve()),
                })
            except Exception as exc:
                logger.warning(f"跳过无效宏文件 {file_path}: {exc}")

        logger.info(f"在 {directory} 中找到 {len(macros)} 个宏文件")
        return macros

    async def delete_macro(self, filepath: str) -> bool:
        """删除宏文件。

        Args:
            filepath: 要删除的宏文件路径

        Returns:
            bool: 是否删除成功

        Raises:
            FileNotFoundError: 文件不存在
        """
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"宏文件不存在: {filepath}")

        path.unlink()
        logger.info(f"已删除宏文件: {filepath}")
        return True
