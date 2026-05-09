"""用户场景感知引擎。

综合屏幕内容、活跃窗口、时间模式等信息，理解用户当前的活动场景。
提供场景分类、持续追踪和智能建议功能。

典型用法::

    engine = ContextEngine()
    snapshot = await engine.get_current_context()
    print(snapshot.scene_type, snapshot.confidence)

    actions = await engine.get_suggested_actions(snapshot)
    for action in actions:
        print(action.title, action.priority)
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any

from loguru import logger

from src.perception.context_detectors import ActivityDetector, SceneClassifier
from src.perception.context_models import (
    ContextSnapshot,
    SceneType,
    SuggestedAction,
    TimeSlot,
)


# ---------------------------------------------------------------------------
# TimePatternTracker
# ---------------------------------------------------------------------------
class TimePatternTracker:
    """追踪时间模式。

    记录不同时段的应用使用习惯，用于辅助场景判断和建议生成。
    维护一个按 (星期, 小时) 索引的历史记录表。
    """

    def __init__(self, max_history_per_slot: int = 100) -> None:
        self._max_history = max_history_per_slot
        self._usage_map: dict[tuple[int, int], Counter[str]] = {}
        self._scene_map: dict[tuple[int, int], SceneType] = {}

    def record(self, snapshot: ContextSnapshot) -> None:
        """记录一个场景快照到时间模式中。"""
        import datetime

        dt = datetime.datetime.fromtimestamp(snapshot.timestamp)
        key = (dt.weekday(), dt.hour)

        if key not in self._usage_map:
            self._usage_map[key] = Counter()
        counter = self._usage_map[key]
        counter[snapshot.active_app] += 1

        # 限制历史长度：超过上限时按比例缩减
        total = sum(counter.values())
        if total > self._max_history:
            target = self._max_history // 2
            # 按比例缩减各应用计数
            factor = target / total
            new_counter = Counter()
            for app, count in counter.items():
                new_count = max(1, int(count * factor))
                new_counter[app] = new_count
            self._usage_map[key] = new_counter

        if snapshot.scene_type != SceneType.UNKNOWN:
            self._scene_map[key] = snapshot.scene_type

    def get_time_slot(self, timestamp: float) -> TimeSlot:
        """获取指定时间的时间段信息。"""
        import datetime

        dt = datetime.datetime.fromtimestamp(timestamp)
        key = (dt.weekday(), dt.hour)

        return TimeSlot(
            hour=dt.hour,
            day_of_week=dt.weekday(),
            typical_scene=self._scene_map.get(key, SceneType.UNKNOWN),
            app_frequency=dict(self._usage_map.get(key, Counter())),
        )

    def get_typical_scene(self, timestamp: float) -> SceneType:
        """获取指定时间的典型场景。"""
        return self.get_time_slot(timestamp).typical_scene

    def get_most_used_app(self, timestamp: float) -> str:
        """获取指定时段最常用的应用。"""
        slot = self.get_time_slot(timestamp)
        if not slot.app_frequency:
            return ""
        return max(slot.app_frequency, key=slot.app_frequency.get)  # type: ignore[arg-type]

    def is_work_hour(self, timestamp: float) -> bool:
        """判断是否在工作时段（周一至周五 9:00-18:00）。"""
        import datetime

        dt = datetime.datetime.fromtimestamp(timestamp)
        return dt.weekday() < 5 and 9 <= dt.hour < 18

    def get_stats(self) -> dict[str, Any]:
        """获取时间模式统计信息。"""
        total_records = sum(sum(c.values()) for c in self._usage_map.values())
        covered_slots = len(self._usage_map)
        total_slots = 7 * 24

        return {
            "total_records": total_records,
            "covered_slots": covered_slots,
            "total_slots": total_slots,
            "coverage_ratio": covered_slots / total_slots if total_slots > 0 else 0,
            "scene_types_known": len(self._scene_map),
        }


# ---------------------------------------------------------------------------
# ContextEngine
# ---------------------------------------------------------------------------
class ContextEngine:
    """用户场景感知引擎。

    整合 ActivityDetector、SceneClassifier、TimePatternTracker，
    提供场景感知和智能建议功能。
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._detector = ActivityDetector()
        self._classifier = SceneClassifier()
        self._time_tracker = TimePatternTracker(
            max_history_per_slot=self._config.get("max_history_per_slot", 100)
        )

        # 场景历史记录
        self._history: list[ContextSnapshot] = []
        self._max_history = self._config.get("max_history", 1000)

        # 当前场景追踪（用于计算持续时间）
        self._current_scene: SceneType = SceneType.UNKNOWN
        self._current_app: str = ""
        self._scene_start_time: float = 0.0

        # 监控任务控制
        self._monitoring = False
        self._monitor_task: asyncio.Task[None] | None = None

        logger.debug("ContextEngine 初始化完成")

    async def get_current_context(self) -> ContextSnapshot:
        """获取当前用户的场景快照。

        Returns:
            ContextSnapshot 包含当前场景的所有信息
        """
        activity = await self._detector.detect()
        scene_type, confidence = self._classifier.classify(activity)

        now = time.time()
        duration = self._calculate_duration(scene_type, activity.app_name, now)

        snapshot = ContextSnapshot(
            timestamp=now,
            active_app=activity.app_name,
            active_window=activity.window_title,
            scene_type=scene_type,
            confidence=confidence,
            duration_seconds=duration,
            metadata={"pid": activity.pid},
        )

        self._record_snapshot(snapshot)

        logger.debug(
            f"场景快照: scene={scene_type.value}, "
            f"app={activity.app_name}, "
            f"confidence={confidence:.2f}, "
            f"duration={duration:.1f}s"
        )
        return snapshot

    async def get_suggested_actions(
        self, snapshot: ContextSnapshot | None = None
    ) -> list[SuggestedAction]:
        """获取基于当前场景的建议操作。

        Args:
            snapshot: 场景快照，为 None 则自动获取

        Returns:
            建议操作列表，按优先级降序排列
        """
        if snapshot is None:
            snapshot = await self.get_current_context()

        actions: list[SuggestedAction] = []

        # 基于场景类型提供建议
        match snapshot.scene_type:
            case SceneType.CODING:
                actions.extend(self._coding_suggestions(snapshot))
            case SceneType.MEETING:
                actions.extend(self._meeting_suggestions(snapshot))
            case SceneType.BROWSING:
                actions.extend(self._browsing_suggestions(snapshot))
            case SceneType.WRITING:
                actions.extend(self._writing_suggestions(snapshot))
            case SceneType.IDLE:
                actions.extend(self._idle_suggestions(snapshot))
            case SceneType.GAMING:
                actions.append(SuggestedAction(
                    action_type="info", title="游戏模式",
                    description="当前正在游戏中，暂停非紧急通知", priority=0.3,
                ))
            case SceneType.MEDIA:
                actions.append(SuggestedAction(
                    action_type="info", title="媒体播放中",
                    description="正在观看/收听媒体内容", priority=0.3,
                ))
            case SceneType.UNKNOWN:
                actions.append(SuggestedAction(
                    action_type="monitor", title="场景识别中",
                    description="暂未识别当前场景，继续监测", priority=0.2,
                ))

        actions.extend(self._duration_suggestions(snapshot))
        actions.extend(self._time_pattern_suggestions(snapshot))

        actions.sort(key=lambda a: a.priority, reverse=True)
        return actions

    async def start_monitoring(self, interval_seconds: float = 30.0) -> None:
        """启动后台场景监控。

        Args:
            interval_seconds: 监控间隔（秒），默认 30 秒
        """
        if self._monitoring:
            logger.warning("场景监控已在运行中")
            return

        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval_seconds))
        logger.info(f"场景监控已启动，间隔 {interval_seconds}s")

    async def stop_monitoring(self) -> None:
        """停止后台场景监控。"""
        if not self._monitoring:
            return

        self._monitoring = False
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        logger.info("场景监控已停止")

    def get_scene_history(self, limit: int = 100) -> list[ContextSnapshot]:
        """获取场景历史记录。

        Args:
            limit: 返回的最大记录数，默认 100

        Returns:
            最近的场景快照列表（按时间降序）
        """
        return list(reversed(self._history[-limit:]))

    @property
    def is_monitoring(self) -> bool:
        """是否正在监控。"""
        return self._monitoring

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _calculate_duration(
        self, scene_type: SceneType, app_name: str, now: float
    ) -> float:
        """计算当前场景的持续时间。场景或应用变化则重置计时。"""
        if scene_type == self._current_scene and app_name == self._current_app:
            return now - self._scene_start_time
        self._current_scene = scene_type
        self._current_app = app_name
        self._scene_start_time = now
        return 0.0

    def _record_snapshot(self, snapshot: ContextSnapshot) -> None:
        """记录快照到历史和时间模式。"""
        self._history.append(snapshot)
        if len(self._history) > self._max_history:
            self._history = self._history[-(self._max_history // 2):]
        self._time_tracker.record(snapshot)

    async def _monitor_loop(self, interval: float) -> None:
        """监控循环。"""
        try:
            while self._monitoring:
                try:
                    await self.get_current_context()
                except Exception as e:
                    logger.error(f"场景监控采样失败: {e}")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.debug("场景监控循环被取消")

    # ------------------------------------------------------------------
    # 场景建议
    # ------------------------------------------------------------------
    def _coding_suggestions(self, s: ContextSnapshot) -> list[SuggestedAction]:
        actions: list[SuggestedAction] = []
        if s.duration_seconds > 3600:
            actions.append(SuggestedAction(
                action_type="remind", title="休息提醒",
                description="连续编码已超过 1 小时，建议短暂休息", priority=0.7,
            ))
        actions.append(SuggestedAction(
            action_type="assist", title="编码助手就绪",
            description="当前处于编码环境，可以提供代码辅助", priority=0.5,
        ))
        return actions

    def _meeting_suggestions(self, s: ContextSnapshot) -> list[SuggestedAction]:
        actions: list[SuggestedAction] = [
            SuggestedAction(
                action_type="dnd", title="免打扰模式",
                description="当前处于会议中，建议暂停非紧急通知", priority=0.8,
            )
        ]
        if s.duration_seconds > 1800:
            actions.append(SuggestedAction(
                action_type="summarize", title="会议纪要",
                description="会议已持续 30 分钟，可以生成纪要", priority=0.6,
            ))
        return actions

    def _browsing_suggestions(self, s: ContextSnapshot) -> list[SuggestedAction]:
        return [SuggestedAction(
            action_type="bookmark", title="收藏提示",
            description="正在浏览网页，可以将有价值的内容收藏", priority=0.3,
        )]

    def _writing_suggestions(self, s: ContextSnapshot) -> list[SuggestedAction]:
        return [SuggestedAction(
            action_type="assist", title="写作助手",
            description="当前处于写作环境，可以提供写作辅助", priority=0.5,
        )]

    def _idle_suggestions(self, s: ContextSnapshot) -> list[SuggestedAction]:
        actions: list[SuggestedAction] = []
        if self._time_tracker.is_work_hour(s.timestamp):
            typical_scene = self._time_tracker.get_typical_scene(s.timestamp)
            typical_app = self._time_tracker.get_most_used_app(s.timestamp)
            if typical_app:
                actions.append(SuggestedAction(
                    action_type="switch_app", title=f"打开 {typical_app}",
                    description=f"当前时段通常使用 {typical_app}（{typical_scene.value}）",
                    priority=0.6, metadata={"target_app": typical_app},
                ))
        actions.append(SuggestedAction(
            action_type="summary", title="工作摘要",
            description="当前空闲，可以回顾近期工作", priority=0.4,
        ))
        return actions

    def _duration_suggestions(self, s: ContextSnapshot) -> list[SuggestedAction]:
        if s.duration_seconds > 7200:
            return [SuggestedAction(
                action_type="remind", title="长时间活动提醒",
                description=f"已在 {s.scene_type.value} 场景超过 2 小时", priority=0.8,
            )]
        return []

    def _time_pattern_suggestions(self, s: ContextSnapshot) -> list[SuggestedAction]:
        typical_scene = self._time_tracker.get_typical_scene(s.timestamp)
        if (
            typical_scene != SceneType.UNKNOWN
            and s.scene_type != typical_scene
            and s.scene_type != SceneType.IDLE
        ):
            return [SuggestedAction(
                action_type="info", title="场景变化提示",
                description=f"当前时段通常处于 {typical_scene.value} 场景，现在为 {s.scene_type.value}",
                priority=0.3,
            )]
        return []
