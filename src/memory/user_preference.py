"""用户偏好学习引擎。

学习并适应用户的工具使用习惯、工作时间模式、风险偏好等行为特征，
为 JavasAgent 的决策提供个性化依据。

Usage::

    engine = UserPreferenceEngine()
    await engine.initialize()

    # 记录行为
    engine.record_tool_usage("browser", "open", success=True, duration_ms=320)
    engine.record_work_hours(hour=14, is_active=True)

    # 查询偏好
    tools = engine.get_preferred_tools("web")
    score = engine.get_preference_score("browser", "open")

    # 持久化
    await engine.save()
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.memory.user_preference_models import PreferenceData, WorkHourPattern

# 默认存储路径
_DEFAULT_STORAGE_DIR = Path.home() / ".javasagent"
_DEFAULT_STORAGE_FILE = "preferences.json"

# 活跃时间阈值：某小时计数 >= 此值视为"常活跃"
_ACTIVE_HOUR_THRESHOLD = 3

# 风险偏好阈值
_RISK_CAUTIOUS_RATIO = 0.30  # 纠正率 > 30% → cautious
_RISK_AGGRESSIVE_RATIO = 0.10  # 纠正率 < 10% → aggressive


class UserPreferenceEngine:
    """用户偏好学习引擎 - 学习并适应用户习惯。

    通过记录工具使用频率、命令模式、用户反馈和工作时间等数据，
    建立用户偏好画像，供其他模块在决策时参考。
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        """初始化偏好引擎。

        Args:
            storage_path: 偏好数据文件路径。None 则使用默认路径
                          ``~/.javasagent/preferences.json``。
        """
        if storage_path is None:
            self._path = _DEFAULT_STORAGE_DIR / _DEFAULT_STORAGE_FILE
        else:
            self._path = Path(storage_path)

        self._data: PreferenceData = PreferenceData()
        self._initialized: bool = False

    # ──────────────────────────────────
    # 生命周期
    # ──────────────────────────────────

    async def initialize(self) -> None:
        """加载已有偏好数据。若文件不存在则使用空数据。"""
        if self._initialized:
            return

        if self._path.exists():
            try:
                raw = self._path.read_text(encoding="utf-8")
                parsed = json.loads(raw)
                self._data = PreferenceData.from_dict(parsed)
                logger.info(
                    "用户偏好数据已加载: {} 次交互, {} 个工具记录",
                    self._data.total_interactions,
                    len(self._data.tool_usage),
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                logger.warning("偏好数据加载失败，使用空数据: {}", exc)
                self._data = PreferenceData()
        else:
            logger.info("未找到偏好数据文件，使用空数据")

        self._initialized = True

    async def save(self) -> None:
        """持久化偏好数据到文件。"""
        self._data.last_updated = time.time()

        # 确保目录存在
        self._path.parent.mkdir(parents=True, exist_ok=True)

        payload = self._data.to_dict()
        raw = json.dumps(payload, ensure_ascii=False, indent=2)
        self._path.write_text(raw, encoding="utf-8")
        logger.debug("偏好数据已保存到 {}", self._path)

    # ──────────────────────────────────
    # 记录用户行为
    # ──────────────────────────────────

    def record_tool_usage(
        self,
        tool_name: str,
        action: str,
        success: bool,
        duration_ms: int,
    ) -> None:
        """记录工具使用频率、成功率和平均耗时。

        Args:
            tool_name: 工具名称（如 "browser", "terminal"）。
            action: 具体动作（如 "open", "execute"）。
            success: 本次使用是否成功。
            duration_ms: 执行耗时（毫秒）。
        """
        key = tool_name
        entry = self._data.tool_usage.setdefault(
            key,
            {"count": 0, "success_count": 0, "total_duration_ms": 0},
        )
        entry["count"] += 1
        if success:
            entry["success_count"] += 1
        entry["total_duration_ms"] += duration_ms
        self._data.total_interactions += 1
        self._data.last_updated = time.time()

    def record_command_pattern(
        self,
        command: str,
        time_of_day: int,
        context: str,
    ) -> None:
        """记录用户发命令的时间模式和上下文。

        Args:
            command: 用户输入的原始命令文本。
            time_of_day: 发命令时的小时（0-23）。
            context: 命令所在上下文（如 "chat", "cli"）。
        """
        normalized = command.strip().lower()
        if not normalized:
            return

        self._data.command_patterns[normalized] = (
            self._data.command_patterns.get(normalized, 0) + 1
        )
        self._data.total_interactions += 1
        self._data.last_updated = time.time()

    def record_feedback(self, action_taken: str, user_rating: int) -> None:
        """记录用户对 agent 行为的反馈。

        Args:
            action_taken: agent 执行的动作描述。
            user_rating: 用户评分 1-5（1=非常不满意, 5=非常满意）。
        """
        rating = max(1, min(5, user_rating))

        self._data.add_feedback(
            {
                "action": action_taken,
                "rating": rating,
                "timestamp": time.time(),
            }
        )

        # 低评分（<=2）视为用户纠正
        if rating <= 2:
            self._data.risk_events += 1

        self._data.total_interactions += 1
        self._data.last_updated = time.time()

    def record_work_hours(self, hour: int, is_active: bool) -> None:
        """记录用户在某个小时的活跃状态。

        Args:
            hour: 0-23 整点小时。
            is_active: 该小时是否活跃。
        """
        if not (0 <= hour <= 23):
            return

        if not is_active:
            return

        # 简化实现：按工作日记录（外部调用者可按星期区分）
        hours_map = self._data.work_hours.weekday_hours
        hours_map[hour] = hours_map.get(hour, 0) + 1
        self._data.last_updated = time.time()

    def record_work_hours_v2(
        self,
        hour: int,
        is_active: bool,
        *,
        is_weekend: bool = False,
    ) -> None:
        """记录用户活跃时间（区分工作日/周末）。

        Args:
            hour: 0-23 整点小时。
            is_active: 是否活跃。
            is_weekend: 是否为周末。
        """
        if not (0 <= hour <= 23) or not is_active:
            return

        hours_map = (
            self._data.work_hours.weekend_hours
            if is_weekend
            else self._data.work_hours.weekday_hours
        )
        hours_map[hour] = hours_map.get(hour, 0) + 1
        self._data.last_updated = time.time()

    # ──────────────────────────────────
    # 查询偏好
    # ──────────────────────────────────

    def get_preferred_tools(self, task_type: str) -> list[str]:
        """根据任务类型返回推荐的工具列表，按偏好排序。

        偏好排序依据：成功率 * 使用频率归一化分。

        Args:
            task_type: 任务类型关键词（如 "web", "file", "system"）。

        Returns:
            按偏好降序排列的工具名称列表。
        """
        if not self._data.tool_usage:
            return []

        scored: list[tuple[str, float]] = []
        max_count = max(
            (e["count"] for e in self._data.tool_usage.values()),
            default=1,
        )

        for tool_name, entry in self._data.tool_usage.items():
            # 如果指定了 task_type，优先匹配包含该关键词的工具
            if task_type and task_type.lower() not in tool_name.lower():
                continue

            count = entry["count"]
            success_count = entry.get("success_count", count)
            success_rate = success_count / count if count > 0 else 0.0
            freq_norm = count / max_count if max_count > 0 else 0.0
            score = success_rate * 0.6 + freq_norm * 0.4
            scored.append((tool_name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored]

    def get_active_hours(self) -> dict[str, list[int]]:
        """返回用户活跃时间模式。

        Returns:
            ``{"weekday": [9, 10, 11, ...], "weekend": [11, 12, ...]}``
            仅包含活跃次数达到阈值的整点小时。
        """
        result: dict[str, list[int]] = {
            "weekday": [],
            "weekend": [],
        }

        for hour, count in self._data.work_hours.weekday_hours.items():
            if count >= _ACTIVE_HOUR_THRESHOLD:
                result["weekday"].append(hour)

        for hour, count in self._data.work_hours.weekend_hours.items():
            if count >= _ACTIVE_HOUR_THRESHOLD:
                result["weekend"].append(hour)

        result["weekday"].sort()
        result["weekend"].sort()
        return result

    def get_risk_tolerance(self) -> str:
        """返回用户风险偏好。

        基于用户历史反馈中纠正 agent 行为的比例判断。

        Returns:
            ``"cautious"`` | ``"moderate"`` | ``"aggressive"``
        """
        total = self._data.total_interactions
        if total == 0:
            return "moderate"

        ratio = self._data.risk_events / total
        if ratio > _RISK_CAUTIOUS_RATIO:
            return "cautious"
        elif ratio < _RISK_AGGRESSIVE_RATIO:
            return "aggressive"
        return "moderate"

    def get_command_shortcuts(self) -> dict[str, str]:
        """返回用户常用命令的快捷映射。

        从命令模式中提取出现 >= 3 次的命令，生成简短别名。
        映射格式：``{原始命令: 归一化命令}``。

        Returns:
            命令快捷映射字典。
        """
        shortcuts: dict[str, str] = {}
        min_count = 3

        for cmd, count in self._data.command_patterns.items():
            if count < min_count:
                continue
            # 生成简短别名：取前几个词
            words = cmd.split()
            if len(words) >= 2:
                shortcut = " ".join(words[:2])
            else:
                shortcut = cmd
            shortcuts[shortcut] = cmd

        return shortcuts

    def get_preference_score(self, tool_name: str, action: str) -> float:
        """返回 0.0-1.0 的偏好分数，用于工具选择决策。

        综合考虑使用频率和成功率。

        Args:
            tool_name: 工具名称。
            action: 具体动作。

        Returns:
            0.0（无记录）到 1.0（高频且全部成功）之间的分数。
        """
        entry = self._data.tool_usage.get(tool_name)
        if not entry or entry["count"] == 0:
            return 0.0

        count = entry["count"]
        max_count = max(
            (e["count"] for e in self._data.tool_usage.values()),
            default=1,
        )
        success_count = entry.get("success_count", count)

        success_rate = success_count / count
        freq_norm = count / max_count if max_count > 0 else 0.0

        score = success_rate * 0.6 + freq_norm * 0.4
        return round(min(1.0, max(0.0, score)), 4)

    def get_stats(self) -> dict[str, Any]:
        """返回引擎统计信息。

        Returns:
            包含总记录数、工具偏好排名、风险偏好等统计的字典。
        """
        # 工具偏好排名
        tool_ranking = sorted(
            self._data.tool_usage.items(),
            key=lambda x: x[1]["count"],
            reverse=True,
        )

        return {
            "total_interactions": self._data.total_interactions,
            "tool_count": len(self._data.tool_usage),
            "tool_ranking": [
                {
                    "name": name,
                    "count": entry["count"],
                    "success_rate": round(
                        entry.get("success_count", entry["count"]) / entry["count"],
                        4,
                    )
                    if entry["count"] > 0
                    else 0.0,
                    "avg_duration_ms": round(
                        entry.get("total_duration_ms", 0) / entry["count"], 2
                    )
                    if entry["count"] > 0
                    else 0.0,
                }
                for name, entry in tool_ranking
            ],
            "command_pattern_count": len(self._data.command_patterns),
            "feedback_count": len(self._data.feedback_history),
            "risk_tolerance": self.get_risk_tolerance(),
            "risk_events": self._data.risk_events,
            "last_updated": self._data.last_updated,
        }
