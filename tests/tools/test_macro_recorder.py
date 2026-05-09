"""MacroRecorder 单元测试。

测试宏数据模型的序列化/反序列化、宏文件的保存/加载/列表/删除，
以及 PlaybackSpeed 和 MacroStatus 枚举值。
Mock pynput 和 pyautogui，不依赖真实硬件。
"""

from __future__ import annotations

import json
import os
import sys
import types
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.tools.macro_models import (
    MacroDefinition,
    MacroEvent,
    MacroEventType,
    MacroStatus,
    MacroStep,
    MouseButton,
    PlaybackSpeed,
)
from src.tools.macro_recorder import MacroRecorder


# ---------------------------------------------------------------------------
# 枚举测试
# ---------------------------------------------------------------------------


class TestMacroStatus:
    """MacroStatus 枚举测试。"""

    def test_values(self) -> None:
        assert MacroStatus.RECORDING == "recording"
        assert MacroStatus.STOPPED == "stopped"
        assert MacroStatus.PLAYING == "playing"

    def test_all_members(self) -> None:
        assert len(MacroStatus) == 3

    def test_string_comparison(self) -> None:
        assert MacroStatus.RECORDING.value == "recording"
        assert MacroStatus.STOPPED.value == "stopped"
        assert MacroStatus.PLAYING.value == "playing"


class TestPlaybackSpeed:
    """PlaybackSpeed 枚举测试。"""

    def test_values(self) -> None:
        assert PlaybackSpeed.HALF.value == "0.5x"
        assert PlaybackSpeed.NORMAL.value == "1x"
        assert PlaybackSpeed.DOUBLE.value == "2x"
        assert PlaybackSpeed.QUAD.value == "4x"

    def test_multiplier(self) -> None:
        assert PlaybackSpeed.HALF.multiplier == 0.5
        assert PlaybackSpeed.NORMAL.multiplier == 1.0
        assert PlaybackSpeed.DOUBLE.multiplier == 2.0
        assert PlaybackSpeed.QUAD.multiplier == 4.0

    def test_all_members(self) -> None:
        assert len(PlaybackSpeed) == 4


class TestMacroEventType:
    """MacroEventType 枚举测试。"""

    def test_values(self) -> None:
        assert MacroEventType.MOUSE_MOVE == "mouse_move"
        assert MacroEventType.MOUSE_CLICK == "mouse_click"
        assert MacroEventType.MOUSE_SCROLL == "mouse_scroll"
        assert MacroEventType.KEY_PRESS == "key_press"
        assert MacroEventType.KEY_RELEASE == "key_release"


class TestMouseButton:
    """MouseButton 枚举测试。"""

    def test_values(self) -> None:
        assert MouseButton.LEFT.value == "left"
        assert MouseButton.MIDDLE.value == "middle"
        assert MouseButton.RIGHT.value == "right"


# ---------------------------------------------------------------------------
# 数据模型序列化/反序列化测试
# ---------------------------------------------------------------------------


class TestMacroEvent:
    """MacroEvent 测试。"""

    def test_create_mouse_move(self) -> None:
        evt = MacroEvent(
            event_type=MacroEventType.MOUSE_MOVE,
            x=100, y=200,
            delay_ms=50.0,
            timestamp=1700000000.0,
        )
        assert evt.event_type == MacroEventType.MOUSE_MOVE
        assert evt.x == 100
        assert evt.y == 200
        assert evt.delay_ms == 50.0

    def test_create_mouse_click(self) -> None:
        evt = MacroEvent(
            event_type=MacroEventType.MOUSE_CLICK,
            x=300, y=400,
            button=MouseButton.LEFT,
            pressed=True,
            delay_ms=10.0,
        )
        assert evt.button == MouseButton.LEFT
        assert evt.pressed is True

    def test_create_key_event(self) -> None:
        evt = MacroEvent(
            event_type=MacroEventType.KEY_PRESS,
            key="a",
            delay_ms=20.0,
        )
        assert evt.key == "a"
        assert evt.x is None

    def test_create_scroll(self) -> None:
        evt = MacroEvent(
            event_type=MacroEventType.MOUSE_SCROLL,
            x=500, y=600,
            scroll_dx=0,
            scroll_dy=-3,
            delay_ms=5.0,
        )
        assert evt.scroll_dy == -3

    def test_default_values(self) -> None:
        evt = MacroEvent(event_type=MacroEventType.MOUSE_MOVE)
        assert evt.x is None
        assert evt.y is None
        assert evt.button is None
        assert evt.key is None
        assert evt.scroll_dx == 0
        assert evt.scroll_dy == 0
        assert evt.delay_ms == 0.0
        assert evt.timestamp == 0.0

    def test_serialization_roundtrip(self) -> None:
        evt = MacroEvent(
            event_type=MacroEventType.MOUSE_CLICK,
            x=100, y=200,
            button=MouseButton.RIGHT,
            pressed=False,
            delay_ms=123.45,
            timestamp=1700000000.0,
        )
        data = evt.model_dump(mode="json")
        evt2 = MacroEvent.model_validate(data)
        assert evt2.event_type == evt.event_type
        assert evt2.x == evt.x
        assert evt2.y == evt.y
        assert evt2.button == evt.button
        assert evt2.pressed == evt.pressed
        assert evt2.delay_ms == evt.delay_ms
        assert evt2.timestamp == evt.timestamp


class TestMacroStep:
    """MacroStep 测试。"""

    def test_create_step(self) -> None:
        step = MacroStep(
            description="Click button",
            events=[
                MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=10, y=20),
            ],
            params={"clicks": 1},
        )
        assert step.description == "Click button"
        assert len(step.events) == 1
        assert step.params["clicks"] == 1

    def test_default_values(self) -> None:
        step = MacroStep()
        assert step.description == ""
        assert step.events == []
        assert step.params == {}

    def test_serialization_roundtrip(self) -> None:
        step = MacroStep(
            description="test step",
            events=[
                MacroEvent(event_type=MacroEventType.KEY_PRESS, key="a"),
                MacroEvent(event_type=MacroEventType.KEY_RELEASE, key="a"),
            ],
            params={"repeat": 3},
        )
        data = step.model_dump(mode="json")
        step2 = MacroStep.model_validate(data)
        assert step2.description == step.description
        assert len(step2.events) == 2
        assert step2.params["repeat"] == 3


class TestMacroDefinition:
    """MacroDefinition 测试。"""

    def test_create_minimal(self) -> None:
        macro = MacroDefinition()
        assert macro.name == "Untitled Macro"
        assert macro.description == ""
        assert macro.events == []
        assert macro.steps == []
        assert macro.version == "1.0"
        assert macro.hotkey is None

    def test_create_with_events(self) -> None:
        events = [
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=10, y=20, button=MouseButton.LEFT, pressed=True),
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=10, y=20, button=MouseButton.LEFT, pressed=False),
        ]
        macro = MacroDefinition(
            name="Test Macro",
            description="A test macro",
            events=events,
            hotkey="<ctrl>+<alt>+t",
        )
        assert macro.name == "Test Macro"
        assert len(macro.events) == 2
        assert macro.hotkey == "<ctrl>+<alt>+t"

    def test_serialization_roundtrip(self) -> None:
        macro = MacroDefinition(
            name="Serialize Test",
            description="Testing serialization",
            events=[
                MacroEvent(event_type=MacroEventType.KEY_PRESS, key="h", delay_ms=10.0),
                MacroEvent(event_type=MacroEventType.KEY_RELEASE, key="h", delay_ms=5.0),
            ],
            steps=[
                MacroStep(description="Type h", events=[
                    MacroEvent(event_type=MacroEventType.KEY_PRESS, key="h"),
                ]),
            ],
            hotkey="<ctrl>+h",
        )
        data = macro.model_dump(mode="json")
        json_str = json.dumps(data)
        loaded = json.loads(json_str)
        macro2 = MacroDefinition.model_validate(loaded)

        assert macro2.name == macro.name
        assert macro2.description == macro.description
        assert len(macro2.events) == len(macro.events)
        assert len(macro2.steps) == len(macro.steps)
        assert macro2.hotkey == macro.hotkey
        assert macro2.version == macro.version

    def test_json_roundtrip_with_all_event_types(self) -> None:
        """测试包含所有事件类型的完整序列化循环。"""
        events = [
            MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=100, y=200, delay_ms=10.0),
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=100, y=200, button=MouseButton.LEFT, pressed=True, delay_ms=5.0),
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=100, y=200, button=MouseButton.LEFT, pressed=False, delay_ms=5.0),
            MacroEvent(event_type=MacroEventType.MOUSE_SCROLL, x=100, y=200, scroll_dy=-3, delay_ms=10.0),
            MacroEvent(event_type=MacroEventType.KEY_PRESS, key="a", delay_ms=20.0),
            MacroEvent(event_type=MacroEventType.KEY_RELEASE, key="a", delay_ms=10.0),
        ]
        macro = MacroDefinition(name="All Types", events=events)
        json_str = macro.model_dump_json()
        macro2 = MacroDefinition.model_validate_json(json_str)
        assert len(macro2.events) == 6
        for orig, loaded in zip(events, macro2.events):
            assert orig.event_type == loaded.event_type
            assert orig.delay_ms == loaded.delay_ms


# ---------------------------------------------------------------------------
# MacroRecorder 文件操作测试
# ---------------------------------------------------------------------------


@pytest.fixture
def recorder() -> MacroRecorder:
    """创建 MacroRecorder 实例。"""
    return MacroRecorder()


@pytest.fixture
def sample_macro() -> MacroDefinition:
    """创建示例宏定义。"""
    return MacroDefinition(
        name="Test Macro",
        description="Sample for testing",
        events=[
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=100, y=200, button=MouseButton.LEFT, pressed=True, delay_ms=50.0),
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=100, y=200, button=MouseButton.LEFT, pressed=False, delay_ms=10.0),
            MacroEvent(event_type=MacroEventType.KEY_PRESS, key="enter", delay_ms=20.0),
            MacroEvent(event_type=MacroEventType.KEY_RELEASE, key="enter", delay_ms=5.0),
        ],
        hotkey="<ctrl>+m",
    )


@pytest.fixture
def macro_dir(tmp_path: Path) -> Path:
    """创建临时宏目录。"""
    d = tmp_path / "macros"
    d.mkdir()
    return d


class TestSaveMacro:
    """save_macro 测试。"""

    @pytest.mark.asyncio
    async def test_save_macro_creates_file(
        self, recorder: MacroRecorder, sample_macro: MacroDefinition, macro_dir: Path
    ) -> None:
        filepath = str(macro_dir / "test.json")
        result = await recorder.save_macro(sample_macro, filepath)

        assert Path(filepath).exists()
        assert result == str(Path(filepath).resolve())

    @pytest.mark.asyncio
    async def test_save_macro_json_content(
        self, recorder: MacroRecorder, sample_macro: MacroDefinition, macro_dir: Path
    ) -> None:
        filepath = str(macro_dir / "content_test.json")
        await recorder.save_macro(sample_macro, filepath)

        content = Path(filepath).read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["name"] == "Test Macro"
        assert len(data["events"]) == 4
        assert data["hotkey"] == "<ctrl>+m"

    @pytest.mark.asyncio
    async def test_save_macro_creates_directories(
        self, recorder: MacroRecorder, sample_macro: MacroDefinition, tmp_path: Path
    ) -> None:
        filepath = str(tmp_path / "deep" / "nested" / "dir" / "macro.json")
        await recorder.save_macro(sample_macro, filepath)
        assert Path(filepath).exists()

    @pytest.mark.asyncio
    async def test_save_macro_empty_path_raises(
        self, recorder: MacroRecorder, sample_macro: MacroDefinition
    ) -> None:
        with pytest.raises(ValueError, match="文件路径不能为空"):
            await recorder.save_macro(sample_macro, "")


class TestLoadMacro:
    """load_macro 测试。"""

    @pytest.mark.asyncio
    async def test_load_macro(
        self, recorder: MacroRecorder, sample_macro: MacroDefinition, macro_dir: Path
    ) -> None:
        filepath = str(macro_dir / "load_test.json")
        await recorder.save_macro(sample_macro, filepath)
        loaded = await recorder.load_macro(filepath)

        assert loaded.name == sample_macro.name
        assert len(loaded.events) == len(sample_macro.events)
        assert loaded.hotkey == sample_macro.hotkey

    @pytest.mark.asyncio
    async def test_load_macro_nonexistent(self, recorder: MacroRecorder) -> None:
        with pytest.raises(FileNotFoundError):
            await recorder.load_macro("/nonexistent/macro.json")

    @pytest.mark.asyncio
    async def test_load_macro_invalid_json(
        self, recorder: MacroRecorder, macro_dir: Path
    ) -> None:
        filepath = macro_dir / "bad.json"
        filepath.write_text("not valid json{{{", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            await recorder.load_macro(str(filepath))

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(
        self, recorder: MacroRecorder, sample_macro: MacroDefinition, macro_dir: Path
    ) -> None:
        filepath = str(macro_dir / "roundtrip.json")
        await recorder.save_macro(sample_macro, filepath)
        loaded = await recorder.load_macro(filepath)

        assert loaded.name == sample_macro.name
        assert loaded.description == sample_macro.description
        assert len(loaded.events) == len(sample_macro.events)
        for orig, loaded_evt in zip(sample_macro.events, loaded.events):
            assert orig.event_type == loaded_evt.event_type
            assert orig.x == loaded_evt.x
            assert orig.y == loaded_evt.y
            assert orig.delay_ms == loaded_evt.delay_ms
        assert loaded.hotkey == sample_macro.hotkey
        assert loaded.version == sample_macro.version


class TestListMacros:
    """list_macros 测试。"""

    @pytest.mark.asyncio
    async def test_list_macros_empty_dir(
        self, recorder: MacroRecorder, macro_dir: Path
    ) -> None:
        result = await recorder.list_macros(str(macro_dir))
        assert result == []

    @pytest.mark.asyncio
    async def test_list_macros_with_files(
        self, recorder: MacroRecorder, macro_dir: Path
    ) -> None:
        # 创建几个宏文件
        for i in range(3):
            macro = MacroDefinition(name=f"Macro {i}", events=[
                MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=i * 10, y=i * 20),
            ])
            await recorder.save_macro(macro, str(macro_dir / f"macro_{i}.json"))

        result = await recorder.list_macros(str(macro_dir))
        assert len(result) == 3
        names = {r["name"] for r in result}
        assert names == {"Macro 0", "Macro 1", "Macro 2"}

    @pytest.mark.asyncio
    async def test_list_macros_skips_invalid(
        self, recorder: MacroRecorder, macro_dir: Path
    ) -> None:
        # 一个有效
        macro = MacroDefinition(name="Valid")
        await recorder.save_macro(macro, str(macro_dir / "valid.json"))
        # 一个无效
        (macro_dir / "invalid.json").write_text("bad json{{", encoding="utf-8")

        result = await recorder.list_macros(str(macro_dir))
        assert len(result) == 1
        assert result[0]["name"] == "Valid"

    @pytest.mark.asyncio
    async def test_list_macros_nonexistent_dir(self, recorder: MacroRecorder) -> None:
        result = await recorder.list_macros("/nonexistent/dir")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_macros_returns_event_count(
        self, recorder: MacroRecorder, macro_dir: Path
    ) -> None:
        macro = MacroDefinition(name="WithEvents", events=[
            MacroEvent(event_type=MacroEventType.KEY_PRESS, key="a"),
            MacroEvent(event_type=MacroEventType.KEY_RELEASE, key="a"),
        ])
        await recorder.save_macro(macro, str(macro_dir / "events.json"))

        result = await recorder.list_macros(str(macro_dir))
        assert result[0]["event_count"] == 2

    @pytest.mark.asyncio
    async def test_list_macros_includes_filepath(
        self, recorder: MacroRecorder, macro_dir: Path
    ) -> None:
        macro = MacroDefinition(name="PathTest")
        filepath = str(macro_dir / "path_test.json")
        await recorder.save_macro(macro, filepath)

        result = await recorder.list_macros(str(macro_dir))
        assert result[0]["filepath"] == str(Path(filepath).resolve())


class TestDeleteMacro:
    """delete_macro 测试。"""

    @pytest.mark.asyncio
    async def test_delete_macro(
        self, recorder: MacroRecorder, sample_macro: MacroDefinition, macro_dir: Path
    ) -> None:
        filepath = str(macro_dir / "to_delete.json")
        await recorder.save_macro(sample_macro, filepath)
        assert Path(filepath).exists()

        result = await recorder.delete_macro(filepath)
        assert result is True
        assert not Path(filepath).exists()

    @pytest.mark.asyncio
    async def test_delete_macro_nonexistent(self, recorder: MacroRecorder) -> None:
        with pytest.raises(FileNotFoundError):
            await recorder.delete_macro("/nonexistent/macro.json")


# ---------------------------------------------------------------------------
# 录制状态测试（不依赖真实 pynput）
# ---------------------------------------------------------------------------


class TestRecordingState:
    """录制状态管理测试。"""

    @pytest.mark.asyncio
    async def test_start_recording_no_pynput_raises(self, recorder: MacroRecorder) -> None:
        """pynput 未安装时应抛出 ImportError。"""
        with patch("src.tools.macro_recorder.mouse", None), \
             patch("src.tools.macro_recorder.keyboard", None):
            with pytest.raises(ImportError, match="pynput"):
                await recorder.start_recording()

    @pytest.mark.asyncio
    async def test_stop_recording_not_recording_raises(self, recorder: MacroRecorder) -> None:
        """不在录制状态时 stop_recording 应抛出异常。"""
        with pytest.raises(RuntimeError, match="当前未在录制"):
            await recorder.stop_recording()


# ---------------------------------------------------------------------------
# 回放测试（mock pyautogui）
# ---------------------------------------------------------------------------


class TestPlayback:
    """回放测试（mock pyautogui）。"""

    @pytest.mark.asyncio
    async def test_playback_empty_macro_raises(self, recorder: MacroRecorder) -> None:
        macro = MacroDefinition(name="Empty")
        with pytest.raises(ValueError, match="没有事件"):
            await recorder.playback(macro)

    @pytest.mark.asyncio
    async def test_playback_recording_state_raises(self, recorder: MacroRecorder) -> None:
        recorder.status = MacroStatus.RECORDING
        macro = MacroDefinition(name="Test", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=0, y=0),
        ])
        with pytest.raises(RuntimeError, match="录制中"):
            await recorder.playback(macro)

    @pytest.mark.asyncio
    async def test_playback_sets_status(self, recorder: MacroRecorder) -> None:
        """回放期间状态应为 PLAYING，结束后恢复 STOPPED。"""
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Quick", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=10, y=20, delay_ms=0),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro)
        assert recorder.status == MacroStatus.STOPPED

    @pytest.mark.asyncio
    async def test_playback_mouse_move(self, recorder: MacroRecorder) -> None:
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Move", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=100, y=200, delay_ms=0),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro)
        mock_agui.moveTo.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_playback_mouse_click(self, recorder: MacroRecorder) -> None:
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Click", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=50, y=60, button=MouseButton.LEFT, pressed=True, delay_ms=0),
            MacroEvent(event_type=MacroEventType.MOUSE_CLICK, x=50, y=60, button=MouseButton.LEFT, pressed=False, delay_ms=0),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro)
        mock_agui.mouseDown.assert_called_once_with(50, 60, button="left")
        mock_agui.mouseUp.assert_called_once_with(50, 60, button="left")

    @pytest.mark.asyncio
    async def test_playback_scroll(self, recorder: MacroRecorder) -> None:
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Scroll", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_SCROLL, x=100, y=100, scroll_dy=-3, delay_ms=0),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro)
        mock_agui.moveTo.assert_called_with(100, 100)
        mock_agui.scroll.assert_called_once_with(-3)

    @pytest.mark.asyncio
    async def test_playback_key_events(self, recorder: MacroRecorder) -> None:
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Keys", events=[
            MacroEvent(event_type=MacroEventType.KEY_PRESS, key="a", delay_ms=0),
            MacroEvent(event_type=MacroEventType.KEY_RELEASE, key="a", delay_ms=0),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro)
        mock_agui.keyDown.assert_called_once_with("a")
        mock_agui.keyUp.assert_called_once_with("a")

    @pytest.mark.asyncio
    async def test_playback_loop(self, recorder: MacroRecorder) -> None:
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Loop", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=10, y=20, delay_ms=0),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro, loop_count=3)
        assert mock_agui.moveTo.call_count == 3

    @pytest.mark.asyncio
    async def test_playback_speed_half(self, recorder: MacroRecorder) -> None:
        """HALF 速度应让延迟加倍（更长等待），此处仅验证不崩溃。"""
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Slow", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=0, y=0, delay_ms=1),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro, speed=PlaybackSpeed.HALF)
        assert recorder.status == MacroStatus.STOPPED

    @pytest.mark.asyncio
    async def test_playback_speed_double(self, recorder: MacroRecorder) -> None:
        mock_agui = MagicMock()
        macro = MacroDefinition(name="Fast", events=[
            MacroEvent(event_type=MacroEventType.MOUSE_MOVE, x=0, y=0, delay_ms=1),
        ])
        with patch("src.tools.macro_recorder.pyautogui", mock_agui):
            await recorder.playback(macro, speed=PlaybackSpeed.DOUBLE)
        assert recorder.status == MacroStatus.STOPPED


# ---------------------------------------------------------------------------
# 按键映射测试
# ---------------------------------------------------------------------------


class TestKeyNormalization:
    """按键名称标准化测试。"""

    def test_common_keys(self) -> None:
        assert MacroRecorder._normalize_key("enter") == "enter"
        assert MacroRecorder._normalize_key("space") == "space"
        assert MacroRecorder._normalize_key("tab") == "tab"
        assert MacroRecorder._normalize_key("backspace") == "backspace"
        assert MacroRecorder._normalize_key("escape") == "escape"

    def test_modifier_keys(self) -> None:
        assert MacroRecorder._normalize_key("ctrl_l") == "ctrlleft"
        assert MacroRecorder._normalize_key("ctrl_r") == "ctrlright"
        assert MacroRecorder._normalize_key("shift_l") == "shiftleft"
        assert MacroRecorder._normalize_key("alt_l") == "altleft"
        assert MacroRecorder._normalize_key("cmd") == "win"

    def test_arrow_keys(self) -> None:
        assert MacroRecorder._normalize_key("up") == "up"
        assert MacroRecorder._normalize_key("down") == "down"
        assert MacroRecorder._normalize_key("left") == "left"
        assert MacroRecorder._normalize_key("right") == "right"

    def test_unknown_key_passthrough(self) -> None:
        assert MacroRecorder._normalize_key("x") == "x"
        assert MacroRecorder._normalize_key("Z") == "Z"

    def test_function_keys(self) -> None:
        for i in range(1, 13):
            assert MacroRecorder._normalize_key(f"f{i}") == f"f{i}"
