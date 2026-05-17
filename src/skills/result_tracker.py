# -*- coding: utf-8 -*-
"""技能执行结果评分模块。

记录技能执行的结果评分（success/failure/partial），用于技能质量追踪。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


class ResultRating(str, Enum):
    """技能执行结果评分等级。"""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


@dataclass
class SkillResult:
    """单次技能执行结果记录。

    Attributes:
        skill_name: 技能名称。
        rating: 执行评分。
        confidence: 匹配置信度。
        query: 用户原始指令。
        steps_total: 总步骤数。
        steps_completed: 完成的步骤数。
        error_message: 错误信息（如果有）。
        executed_at: 执行时间。
        duration_sec: 执行耗时（秒）。
    """

    skill_name: str
    rating: ResultRating
    confidence: float = 0.0
    query: str = ""
    steps_total: int = 0
    steps_completed: int = 0
    error_message: str = ""
    executed_at: datetime = field(default_factory=datetime.now)
    duration_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """转换为字典。"""
        data = asdict(self)
        data["rating"] = self.rating.value
        data["executed_at"] = self.executed_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillResult:
        """从字典还原。"""
        data = dict(data)
        if isinstance(data.get("rating"), str):
            data["rating"] = ResultRating(data["rating"])
        if isinstance(data.get("executed_at"), str):
            data["executed_at"] = datetime.fromisoformat(data["executed_at"])
        return cls(**data)


class ResultTracker:
    """技能执行结果追踪器。

    记录每次技能执行的结果，持久化到 JSON 文件，支持统计查询。

    用法:
        tracker = ResultTracker()
        tracker.record(SkillResult(
            skill_name="打开应用程序",
            rating=ResultRating.SUCCESS,
            confidence=0.95,
            query="打开微信",
        ))
        stats = tracker.get_stats("打开应用程序")
    """

    def __init__(self, storage_path: str | Path | None = None) -> None:
        """初始化追踪器。

        Args:
            storage_path: 持久化存储路径。默认为 data/skill_results.jsonl。
        """
        if storage_path is None:
            storage_path = Path("data") / "skill_results.jsonl"
        self._path = Path(storage_path)
        self._results: list[SkillResult] = []
        self._load()

    @property
    def results(self) -> list[SkillResult]:
        """所有已记录的结果。"""
        return list(self._results)

    def record(self, result: SkillResult) -> None:
        """记录一条执行结果。

        Args:
            result: 技能执行结果。
        """
        self._results.append(result)
        self._append_to_file(result)
        logger.info(
            "技能结果: skill={} rating={} confidence={:.2f}",
            result.skill_name,
            result.rating.value,
            result.confidence,
        )

    def get_stats(self, skill_name: str) -> dict[str, Any]:
        """获取指定技能的执行统计。

        Args:
            skill_name: 技能名称。

        Returns:
            统计信息字典。
        """
        skill_results = [
            r for r in self._results if r.skill_name == skill_name
        ]
        if not skill_results:
            return {
                "skill_name": skill_name,
                "total": 0,
                "success": 0,
                "failure": 0,
                "partial": 0,
                "success_rate": 0.0,
                "avg_confidence": 0.0,
            }

        success = sum(1 for r in skill_results if r.rating == ResultRating.SUCCESS)
        failure = sum(1 for r in skill_results if r.rating == ResultRating.FAILURE)
        partial = sum(1 for r in skill_results if r.rating == ResultRating.PARTIAL)
        total = len(skill_results)

        return {
            "skill_name": skill_name,
            "total": total,
            "success": success,
            "failure": failure,
            "partial": partial,
            "success_rate": round(success / total, 4) if total else 0.0,
            "avg_confidence": round(
                sum(r.confidence for r in skill_results) / total, 4
            ) if total else 0.0,
        }

    def get_all_stats(self) -> list[dict[str, Any]]:
        """获取所有技能的统计。

        Returns:
            各技能统计信息列表。
        """
        names = sorted({r.skill_name for r in self._results})
        return [self.get_stats(name) for name in names]

    def clear(self) -> None:
        """清空所有记录（内存和文件）。"""
        self._results.clear()
        if self._path.exists():
            self._path.write_text("", encoding="utf-8")
        logger.debug("已清空所有结果记录")

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """从文件加载历史记录。"""
        if not self._path.exists():
            return

        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                self._results.append(SkillResult.from_dict(data))
            logger.debug("从 {} 加载 {} 条结果记录", self._path, len(self._results))
        except Exception as e:
            logger.warning("加载结果记录失败: {}", e)

    def _append_to_file(self, result: SkillResult) -> None:
        """追加一条记录到文件。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("写入结果记录失败: {}", e)
