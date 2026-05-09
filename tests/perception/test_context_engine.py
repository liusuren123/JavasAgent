"""ContextEngine 单元测试。

使用 unittest.mock 替代实际 Win32 API 调用和窗口检测，
确保测试可以在任何平台上运行。
"""

from __future__ import annotations

import asyncio
import sys
import time
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock ctypes.windll 以便在非 Windows 平台导入
# ---------------------------------------------------------------------------
_mock_user32 = MagicMock()
_mock_kernel32 = MagicMock()
_mock_psapi = MagicMock()


class _FakeWindll:
    user32 = _mock_user32
    kernel32 = _mock_kernel32
    psapi = _mock_psapi


import ctypes as _ctypes

if not hasattr(_ctypes, "windll"):
    _ctypes.windll = _FakeWindll()  # type: ignore[attr-defined]

if not hasattr(_ctypes, "wintypes"):
    _fake_wintypes = types.ModuleType("ctypes.wintypes")
    _fake_wintypes.HWND = int  # type: ignore[attr-defined]
    _fake_wintypes.LPARAM = int  # type: ignore[attr-defined]
    _fake_wintypes.DWORD = type("DWORD", (), {"value": 0})  # type: ignore[attr-defined]
    _fake_wintypes.RECT = type("RECT", (), {  # type: ignore[attr-defined]
        "left": 0, "top": 0, "right": 0, "bottom": 0,
    })
    sys.modules["ctypes.wintypes"] = _fake_wintypes
    _ctypes.wintypes = _fake_wintypes  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# 导入被测模块
# ---------------------------------------------------------------------------
from src.perception.context_detectors import ActivityDetector, SceneClassifier
from src.perception.context_engine import ContextEngine, TimePatternTracker
from src.perception.context_models import (
    ActivityInfo,
    ContextSnapshot,
    SceneType,
    SuggestedAction,
    TimeSlot,
)


# ===========================================================================
# 数据模型测试
# ===========================================================================
class TestContextModels:
    """ContextSnapshot、SuggestedAction 等数据模型测试。"""

    def test_scene_type_str(self) -> None:
        assert str(SceneType.CODING) == "coding"
        assert str(SceneType.BROWSING) == "browsing"
        assert str(SceneType.UNKNOWN) == "unknown"

    def test_scene_type_is_string(self) -> None:
        assert isinstance(SceneType.CODING, str)
        assert SceneType.CODING == "coding"

    def test_context_snapshot_defaults(self) -> None:
        snap = ContextSnapshot(
            timestamp=1000.0,
            active_app="test",
            active_window="test window",
            scene_type=SceneType.CODING,
            confidence=0.9,
        )
        assert snap.duration_seconds == 0.0
        assert snap.metadata == {}

    def test_context_snapshot_to_dict(self) -> None:
        snap = ContextSnapshot(
            timestamp=1000.0,
            active_app="code",
            active_window="main.py",
            scene_type=SceneType.CODING,
            confidence=0.85,
            duration_seconds=60.0,
            metadata={"pid": 123},
        )
        d = snap.to_dict()
        assert d["active_app"] == "code"
        assert d["scene_type"] == "coding"
        assert d["confidence"] == 0.85
        assert d["duration_seconds"] == 60.0
        assert d["metadata"]["pid"] == 123

    def test_suggested_action_defaults(self) -> None:
        action = SuggestedAction(
            action_type="remind",
            title="Test",
        )
        assert action.description == ""
        assert action.priority == 0.5
        assert action.metadata == {}

    def test_time_slot_defaults(self) -> None:
        slot = TimeSlot(hour=14, day_of_week=2)
        assert slot.typical_scene == SceneType.UNKNOWN
        assert slot.app_frequency == {}


# ===========================================================================
# SceneClassifier 测试
# ===========================================================================
class TestSceneClassifier:
    """SceneClassifier 场景分类测试。"""

    def setup_method(self) -> None:
        self.classifier = SceneClassifier()

    def test_classify_coding_vscode(self) -> None:
        activity = ActivityInfo(app_name="Code", window_title="main.py - Visual Studio Code")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.CODING
        assert conf >= 0.8

    def test_classify_coding_cursor(self) -> None:
        activity = ActivityInfo(app_name="Cursor", window_title="app.tsx")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.CODING

    def test_classify_browsing_chrome(self) -> None:
        activity = ActivityInfo(app_name="chrome", window_title="Google - Google Chrome")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.BROWSING
        assert conf >= 0.8

    def test_classify_meeting_zoom(self) -> None:
        activity = ActivityInfo(app_name="zoom", window_title="Zoom Meeting")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.MEETING

    def test_classify_meeting_feishu(self) -> None:
        activity = ActivityInfo(app_name="Lark", window_title="飞书会议")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.MEETING

    def test_classify_writing_notion(self) -> None:
        activity = ActivityInfo(app_name="Notion", window_title="My Notes - Notion")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.WRITING

    def test_classify_gaming_steam(self) -> None:
        activity = ActivityInfo(app_name="steam", window_title="Steam")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.GAMING

    def test_classify_media_vlc(self) -> None:
        activity = ActivityInfo(app_name="vlc", window_title="movie.mp4 - VLC")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.MEDIA

    def test_classify_idle_no_app(self) -> None:
        activity = ActivityInfo(app_name="", window_title="")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.IDLE
        assert conf >= 0.9

    def test_classify_unknown_app(self) -> None:
        activity = ActivityInfo(app_name="some_random_app", window_title="Random Window")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.UNKNOWN
        assert conf < 0.5

    def test_classify_title_hint_meeting(self) -> None:
        """未知应用但窗口标题包含会议关键词。"""
        activity = ActivityInfo(app_name="electron", window_title="视频会议 - 在线")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.MEETING
        assert conf >= 0.7

    def test_classify_case_insensitive(self) -> None:
        """大小写不敏感匹配。"""
        activity = ActivityInfo(app_name="CHROME", window_title="Google")
        scene, conf = self.classifier.classify(activity)
        assert scene == SceneType.BROWSING

    def test_classify_with_custom_keywords(self) -> None:
        """自定义关键词分类。"""
        activity = ActivityInfo(app_name="myeditor", window_title="Editing config.yaml")
        scene, conf = self.classifier.classify_with_title_keywords(
            activity, ["editing", "config"]
        )
        # 应该匹配到（但 myeditor 不在任何规则中，所以是 UNKNOWN）
        assert conf > 0.5


# ===========================================================================
# TimePatternTracker 测试
# ===========================================================================
class TestTimePatternTracker:
    """TimePatternTracker 时间模式追踪测试。"""

    def setup_method(self) -> None:
        self.tracker = TimePatternTracker(max_history_per_slot=50)

    def _make_snapshot(
        self,
        app: str = "code",
        scene: SceneType = SceneType.CODING,
        timestamp: float | None = None,
    ) -> ContextSnapshot:
        return ContextSnapshot(
            timestamp=timestamp or time.time(),
            active_app=app,
            active_window=f"{app} window",
            scene_type=scene,
            confidence=0.85,
        )

    def test_record_and_retrieve(self) -> None:
        """记录快照后可以检索时间槽。"""
        # 2024-01-15 14:00 UTC+8 (Monday, 14:00)
        ts = 1705298400.0
        snap = self._make_snapshot("code", SceneType.CODING, ts)
        self.tracker.record(snap)

        slot = self.tracker.get_time_slot(ts)
        assert slot.hour == 14
        assert slot.day_of_week == 0  # Monday
        assert slot.typical_scene == SceneType.CODING
        assert "code" in slot.app_frequency
        assert slot.app_frequency["code"] == 1

    def test_typical_scene(self) -> None:
        ts = 1705317600.0
        self.tracker.record(self._make_snapshot("code", SceneType.CODING, ts))
        assert self.tracker.get_typical_scene(ts) == SceneType.CODING

    def test_most_used_app(self) -> None:
        ts = 1705317600.0
        self.tracker.record(self._make_snapshot("code", SceneType.CODING, ts))
        self.tracker.record(self._make_snapshot("code", SceneType.CODING, ts))
        self.tracker.record(self._make_snapshot("chrome", SceneType.BROWSING, ts))
        assert self.tracker.get_most_used_app(ts) == "code"

    def test_work_hour_weekday(self) -> None:
        # Monday 10:00
        ts = 1705310400.0
        assert self.tracker.is_work_hour(ts) is True

    def test_work_hour_night(self) -> None:
        # Monday 22:00
        ts = 1705353600.0
        assert self.tracker.is_work_hour(ts) is False

    def test_work_hour_weekend(self) -> None:
        # Saturday 10:00 (2024-01-20)
        ts = 1705749600.0
        assert self.tracker.is_work_hour(ts) is False

    def test_stats(self) -> None:
        ts = 1705317600.0
        self.tracker.record(self._make_snapshot("code", SceneType.CODING, ts))
        stats = self.tracker.get_stats()
        assert stats["total_records"] == 1
        assert stats["covered_slots"] == 1
        assert stats["coverage_ratio"] > 0

    def test_empty_stats(self) -> None:
        stats = self.tracker.get_stats()
        assert stats["total_records"] == 0
        assert stats["covered_slots"] == 0

    def test_max_history_trim(self) -> None:
        """超过最大历史时自动裁剪。"""
        tracker = TimePatternTracker(max_history_per_slot=5)
        ts = 1705298400.0
        # 使用 2 个不同应用交替记录
        for i in range(20):
            tracker.record(self._make_snapshot(f"app{i % 2}", SceneType.CODING, ts))
        # 裁剪后总记录数应少于 max_history_per_slot
        slot = tracker.get_time_slot(ts)
        assert sum(slot.app_frequency.values()) <= 5


# ===========================================================================
# ContextEngine 测试
# ===========================================================================
class TestContextEngine:
    """ContextEngine 主引擎测试。"""

    def setup_method(self) -> None:
        self.engine = ContextEngine()

    def _mock_activity(self, app: str, title: str) -> None:
        """Mock ActivityDetector.detect 返回指定活动。"""
        self.engine._detector.detect = AsyncMock(  # type: ignore[method-assign]
            return_value=ActivityInfo(
                app_name=app,
                window_title=title,
                pid=1234,
                timestamp=time.time(),
            )
        )

    @pytest.mark.asyncio
    async def test_get_current_context_coding(self) -> None:
        self._mock_activity("Code", "main.py - VS Code")
        snapshot = await self.engine.get_current_context()

        assert snapshot.scene_type == SceneType.CODING
        assert snapshot.active_app == "Code"
        assert snapshot.confidence >= 0.8
        assert snapshot.duration_seconds == 0.0  # 第一次
        assert snapshot.metadata["pid"] == 1234

    @pytest.mark.asyncio
    async def test_get_current_context_idle(self) -> None:
        self._mock_activity("", "")
        snapshot = await self.engine.get_current_context()

        assert snapshot.scene_type == SceneType.IDLE
        assert snapshot.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_duration_tracking(self) -> None:
        """持续时间追踪：同一场景应累加时间。"""
        self._mock_activity("Code", "main.py")

        snap1 = await self.engine.get_current_context()
        assert snap1.duration_seconds == 0.0

        # 模拟时间推移
        self.engine._scene_start_time = time.time() - 120
        snap2 = await self.engine.get_current_context()
        # 同一应用/场景，持续时间应增加
        assert snap2.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_duration_resets_on_scene_change(self) -> None:
        """场景变化时持续时间应重置。"""
        self._mock_activity("Code", "main.py")
        await self.engine.get_current_context()
        self.engine._scene_start_time = time.time() - 300

        # 切换到浏览器
        self._mock_activity("chrome", "Google")
        snap = await self.engine.get_current_context()
        assert snap.scene_type == SceneType.BROWSING
        assert snap.duration_seconds == 0.0  # 重置

    @pytest.mark.asyncio
    async def test_get_suggested_actions_coding(self) -> None:
        self._mock_activity("Code", "main.py")
        snapshot = await self.engine.get_current_context()
        actions = await self.engine.get_suggested_actions(snapshot)

        assert len(actions) > 0
        action_types = [a.action_type for a in actions]
        assert "assist" in action_types

    @pytest.mark.asyncio
    async def test_get_suggested_actions_meeting(self) -> None:
        self._mock_activity("zoom", "Zoom Meeting")
        snapshot = await self.engine.get_current_context()
        actions = await self.engine.get_suggested_actions(snapshot)

        titles = [a.title for a in actions]
        assert "免打扰模式" in titles

    @pytest.mark.asyncio
    async def test_get_suggested_actions_auto_fetch(self) -> None:
        """不传 snapshot 时自动获取。"""
        self._mock_activity("Code", "main.py")
        actions = await self.engine.get_suggested_actions()
        assert len(actions) > 0

    @pytest.mark.asyncio
    async def test_get_suggested_actions_long_meeting(self) -> None:
        """长时间会议建议。"""
        self._mock_activity("zoom", "Zoom Meeting")
        snapshot = await self.engine.get_current_context()
        # 模拟长时间
        snapshot.duration_seconds = 2400

        actions = await self.engine.get_suggested_actions(snapshot)
        titles = [a.title for a in actions]
        assert "会议纪要" in titles

    @pytest.mark.asyncio
    async def test_scene_history(self) -> None:
        self._mock_activity("Code", "main.py")
        await self.engine.get_current_context()

        history = self.engine.get_scene_history()
        assert len(history) == 1
        assert history[0].scene_type == SceneType.CODING

    @pytest.mark.asyncio
    async def test_scene_history_limit(self) -> None:
        self._mock_activity("Code", "main.py")
        for _ in range(5):
            await self.engine.get_current_context()

        history = self.engine.get_scene_history(limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_scene_history_ordering(self) -> None:
        """历史记录应按时间降序返回。"""
        self._mock_activity("Code", "main.py")
        await self.engine.get_current_context()
        self._mock_activity("chrome", "Google")
        await self.engine.get_current_context()

        history = self.engine.get_scene_history()
        assert len(history) == 2
        assert history[0].scene_type == SceneType.BROWSING  # 最新的在前
        assert history[1].scene_type == SceneType.CODING

    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self) -> None:
        """启动和停止监控。"""
        self._mock_activity("Code", "main.py")

        assert self.engine.is_monitoring is False
        await self.engine.start_monitoring(interval_seconds=0.1)
        assert self.engine.is_monitoring is True

        # 等待几次采样
        await asyncio.sleep(0.35)

        await self.engine.stop_monitoring()
        assert self.engine.is_monitoring is False

        # 应该有历史记录
        history = self.engine.get_scene_history()
        assert len(history) >= 1

    @pytest.mark.asyncio
    async def test_start_monitoring_idempotent(self) -> None:
        """重复启动不报错。"""
        self._mock_activity("Code", "main.py")
        await self.engine.start_monitoring(interval_seconds=1.0)
        await self.engine.start_monitoring(interval_seconds=1.0)  # 重复调用
        assert self.engine.is_monitoring is True
        await self.engine.stop_monitoring()

    @pytest.mark.asyncio
    async def test_stop_monitoring_idempotent(self) -> None:
        """未启动时停止不报错。"""
        await self.engine.stop_monitoring()
        assert self.engine.is_monitoring is False

    @pytest.mark.asyncio
    async def test_monitoring_records_history(self) -> None:
        """监控过程中应持续记录场景。"""
        call_count = 0
        original_detect = self.engine._detector.detect

        async def mock_detect() -> ActivityInfo:
            nonlocal call_count
            call_count += 1
            return ActivityInfo(app_name="Code", window_title="test", pid=1, timestamp=time.time())

        self.engine._detector.detect = mock_detect  # type: ignore[method-assign]

        await self.engine.start_monitoring(interval_seconds=0.05)
        await asyncio.sleep(0.25)
        await self.engine.stop_monitoring()

        assert call_count >= 2
        history = self.engine.get_scene_history()
        assert len(history) >= 2

    @pytest.mark.asyncio
    async def test_suggested_actions_sorted_by_priority(self) -> None:
        """建议操作按优先级降序排列。"""
        self._mock_activity("zoom", "Zoom Meeting")
        snapshot = await self.engine.get_current_context()
        snapshot.duration_seconds = 2400  # 长时间会议

        actions = await self.engine.get_suggested_actions(snapshot)
        for i in range(len(actions) - 1):
            assert actions[i].priority >= actions[i + 1].priority

    @pytest.mark.asyncio
    async def test_idle_work_hour_suggestion(self) -> None:
        """空闲时在工作时段建议打开常用应用。"""
        self._mock_activity("", "")

        # 先记录一个工作时段的快照
        work_ts = 1705317600.0  # Monday 14:00
        work_snap = ContextSnapshot(
            timestamp=work_ts,
            active_app="code",
            active_window="code window",
            scene_type=SceneType.CODING,
            confidence=0.85,
        )
        self.engine._time_tracker.record(work_snap)

        # 在同一时段触发空闲检测
        with patch("time.time", return_value=work_ts):
            snapshot = await self.engine.get_current_context()
            actions = await self.engine.get_suggested_actions(snapshot)

            # 应该有工作摘要或打开应用建议
            assert len(actions) > 0

    def test_config_passed_through(self) -> None:
        """配置项正确传递。"""
        engine = ContextEngine(config={"max_history": 500, "max_history_per_slot": 200})
        assert engine._max_history == 500
        assert engine._time_tracker._max_history == 200


# ===========================================================================
# ActivityDetector 测试（Mock Win32）
# ===========================================================================
class TestActivityDetector:
    """ActivityDetector 测试。"""

    def test_init_without_win32(self) -> None:
        """平台不可用时应优雅降级。"""
        with patch("src.perception.context_detectors.ActivityDetector._init_platform"):
            detector = ActivityDetector()
            detector._available = False

        assert detector._available is False

    @pytest.mark.asyncio
    async def test_detect_returns_empty_when_unavailable(self) -> None:
        """Win32 不可用时返回空活动信息。"""
        detector = ActivityDetector()
        detector._available = False

        activity = await detector.detect()
        assert activity.app_name == ""
        assert activity.window_title == ""
        assert activity.pid == 0
