"""技能学习器模块。

从任务执行历史中自动提取可复用模式，当同一模式被成功执行多次后
建议注册为新技能。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.models import ExecutionResult, PlanStatus, StepStatus, TaskPlan
from src.memory.skill_models import LearnedPattern, SkillDefinition, SkillSuggestion


def _make_pattern_key(steps: list[str], tools: list[str]) -> str:
    """根据步骤描述和工具列表生成模式唯一键。"""
    raw = "|".join(steps) + "||" + "|".join(sorted(tools))
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


class SkillLearner:
    """技能学习器。

    从任务执行历史中自动提取可复用的模式。当同一模式被成功执行
    超过指定阈值（默认 3 次）后，自动建议注册为新技能。

    Usage::

        learner = SkillLearner(storage_dir="./data/learned_patterns")
        await learner.initialize()

        # 记录执行
        await learner.record_execution(plan, result)

        # 获取建议
        suggestions = await learner.suggest_skills()

        # 确认注册
        skill_def = await learner.approve_suggestion(suggestion_id)
    """

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        min_success_count: int = 3,
        min_success_rate: float = 0.6,
    ) -> None:
        """初始化技能学习器。

        Args:
            storage_dir: 学习记录持久化目录。None 则仅内存模式。
            min_success_count: 触发建议的最低成功次数。
            min_success_rate: 触发建议的最低成功率。
        """
        self._patterns: dict[str, LearnedPattern] = {}  # pattern_key -> LearnedPattern
        self._suggestions: dict[str, SkillSuggestion] = {}  # suggestion_id -> SkillSuggestion
        self._storage_dir: Path | None = Path(storage_dir) if storage_dir else None
        self._min_success_count = min_success_count
        self._min_success_rate = min_success_rate
        logger.debug(
            "技能学习器初始化 (dir={}, min_success={}, min_rate={})",
            self._storage_dir or "内存模式",
            min_success_count,
            min_success_rate,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """从磁盘加载已有的学习记录。"""
        if self._storage_dir is None:
            logger.debug("内存模式，跳过磁盘加载")
            return

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        await self._load_patterns()
        await self._load_suggestions()

    async def _load_patterns(self) -> None:
        """加载学习模式。"""
        if self._storage_dir is None:
            return

        patterns_file = self._storage_dir / "patterns.json"
        if not patterns_file.exists():
            return

        try:
            raw = patterns_file.read_text(encoding="utf-8")
            items: list[dict] = json.loads(raw) if raw.strip() else []
            for item in items:
                pattern = LearnedPattern.from_dict(item)
                self._patterns[pattern.pattern_key] = pattern
            logger.info("从 {} 加载了 {} 个学习模式", patterns_file, len(self._patterns))
        except Exception:
            logger.exception("加载学习模式失败: {}", patterns_file)

    async def _load_suggestions(self) -> None:
        """加载建议记录。"""
        if self._storage_dir is None:
            return

        suggestions_file = self._storage_dir / "suggestions.json"
        if not suggestions_file.exists():
            return

        try:
            raw = suggestions_file.read_text(encoding="utf-8")
            items: list[dict] = json.loads(raw) if raw.strip() else []
            for item in items:
                suggestion = SkillSuggestion.from_dict(item)
                self._suggestions[suggestion.id] = suggestion
            logger.info("从 {} 加载了 {} 条建议", suggestions_file, len(self._suggestions))
        except Exception:
            logger.exception("加载建议记录失败: {}", suggestions_file)

    async def save(self) -> None:
        """持久化到磁盘。"""
        if self._storage_dir is None:
            logger.debug("内存模式，跳过持久化")
            return

        self._storage_dir.mkdir(parents=True, exist_ok=True)

        # 保存模式
        patterns_file = self._storage_dir / "patterns.json"
        items = [p.to_dict() for p in self._patterns.values()]
        patterns_file.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 保存建议
        suggestions_file = self._storage_dir / "suggestions.json"
        items = [s.to_dict() for s in self._suggestions.values()]
        suggestions_file.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug(
            "学习记录已保存: {} 个模式, {} 条建议",
            len(self._patterns),
            len(self._suggestions),
        )

    # ------------------------------------------------------------------
    # 记录执行
    # ------------------------------------------------------------------

    async def record_execution(
        self,
        plan: TaskPlan,
        result: ExecutionResult,
    ) -> None:
        """记录任务执行结果。

        从 TaskPlan 和 ExecutionResult 中提取步骤和工具信息，
        归入对应的学习模式。

        Args:
            plan: 任务计划
            result: 执行结果
        """
        # 只记录有实际步骤的执行
        if not plan.steps:
            logger.debug("计划 {} 无步骤，跳过记录", plan.id)
            return

        # 提取步骤描述和工具
        step_descriptions: list[str] = []
        tools_used: list[str] = []

        for step in plan.steps:
            step_descriptions.append(f"{step.action}:{step.tool}")
            if step.tool and step.tool not in tools_used:
                tools_used.append(step.tool)

        pattern_key = _make_pattern_key(step_descriptions, tools_used)

        is_success = result.success

        now = __import__("datetime").datetime.now()
        if pattern_key in self._patterns:
            pattern = self._patterns[pattern_key]
            if is_success:
                pattern.success_count += 1
            else:
                pattern.failure_count += 1
            pattern.last_seen_at = now
        else:
            pattern = LearnedPattern(
                id=f"pat_{uuid.uuid4().hex[:12]}",
                pattern_key=pattern_key,
                steps=step_descriptions,
                tools_used=tools_used,
                success_count=1 if is_success else 0,
                failure_count=0 if is_success else 1,
                last_seen_at=now,
                first_seen_at=now,
            )
            self._patterns[pattern_key] = pattern

        logger.debug(
            "记录执行: plan={}, pattern={}, success={}",
            plan.id,
            pattern_key[:8],
            is_success,
        )

    # ------------------------------------------------------------------
    # 分析模式
    # ------------------------------------------------------------------

    async def analyze_patterns(self) -> list[LearnedPattern]:
        """分析并返回所有学习到的模式。

        按成功次数降序排列。

        Returns:
            学习模式列表
        """
        patterns = sorted(
            self._patterns.values(),
            key=lambda p: p.success_count,
            reverse=True,
        )
        return patterns

    # ------------------------------------------------------------------
    # 建议注册
    # ------------------------------------------------------------------

    async def suggest_skills(self) -> list[SkillSuggestion]:
        """生成技能注册建议。

        遍历所有模式，找到满足条件的模式（成功次数 >= 阈值且
        成功率 >= 阈值），为尚未生成建议的模式创建建议。

        Returns:
            新生成的建议列表（不含已有的）
        """
        new_suggestions: list[SkillSuggestion] = []

        for pattern in self._patterns.values():
            # 跳过不满足条件的模式
            if pattern.success_count < self._min_success_count:
                continue
            if pattern.success_rate < self._min_success_rate:
                continue

            # 检查是否已有 pending 建议
            existing = self._find_pending_suggestion(pattern.pattern_key)
            if existing is not None:
                continue

            # 生成建议
            name = self._generate_skill_name(pattern)
            description = self._generate_skill_description(pattern)

            suggestion = SkillSuggestion(
                id=f"sug_{uuid.uuid4().hex[:12]}",
                pattern=pattern,
                suggested_name=name,
                suggested_description=description,
                suggested_category="learned",
                status="pending",
            )
            self._suggestions[suggestion.id] = suggestion
            new_suggestions.append(suggestion)
            logger.info(
                "生成技能建议: {} (pattern={}, success={})",
                name,
                pattern.pattern_key[:8],
                pattern.success_count,
            )

        return new_suggestions

    def _find_pending_suggestion(self, pattern_key: str) -> SkillSuggestion | None:
        """查找指定模式的 pending 状态建议。"""
        for suggestion in self._suggestions.values():
            if (
                suggestion.pattern.pattern_key == pattern_key
                and suggestion.status == "pending"
            ):
                return suggestion
        return None

    async def approve_suggestion(self, suggestion_id: str) -> SkillDefinition:
        """确认注册建议。

        将建议转为正式的 SkillDefinition，标记建议为 approved。

        Args:
            suggestion_id: 建议 ID

        Returns:
            生成的技能定义

        Raises:
            KeyError: 建议不存在
            ValueError: 建议状态不是 pending
        """
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            raise KeyError(f"建议不存在: {suggestion_id}")
        if suggestion.status != "pending":
            raise ValueError(f"建议状态不是 pending: {suggestion.status}")

        # 标记建议为 approved
        suggestion.status = "approved"

        # 创建技能定义
        skill = SkillDefinition.create(
            name=suggestion.suggested_name,
            description=suggestion.suggested_description,
            category=suggestion.suggested_category,
            source="auto_learned",
            pattern_steps=suggestion.pattern.steps,
            tags=suggestion.pattern.tools_used,
            metadata={
                "pattern_key": suggestion.pattern.pattern_key,
                "success_count": suggestion.pattern.success_count,
                "success_rate": suggestion.pattern.success_rate,
            },
        )

        logger.info("确认注册技能: {} ({})", skill.name, skill.id)
        return skill

    async def reject_suggestion(self, suggestion_id: str) -> bool:
        """拒绝建议。

        Args:
            suggestion_id: 建议 ID

        Returns:
            是否成功拒绝
        """
        suggestion = self._suggestions.get(suggestion_id)
        if suggestion is None:
            return False
        if suggestion.status != "pending":
            return False

        suggestion.status = "rejected"
        logger.debug("拒绝建议: {}", suggestion_id)
        return True

    # ------------------------------------------------------------------
    # 建议生成辅助
    # ------------------------------------------------------------------

    def _generate_skill_name(self, pattern: LearnedPattern) -> str:
        """从模式中生成技能名称。"""
        tools = pattern.tools_used
        if len(tools) == 1:
            return f"workflow_{tools[0]}_{pattern.pattern_key[:6]}"
        elif len(tools) <= 3:
            return f"workflow_{'_'.join(tools)}_{pattern.pattern_key[:6]}"
        else:
            return f"workflow_multi_{pattern.pattern_key[:6]}"

    def _generate_skill_description(self, pattern: LearnedPattern) -> str:
        """从模式中生成技能描述。"""
        tools_str = ", ".join(pattern.tools_used)
        steps_count = len(pattern.steps)
        return (
            f"自动学习的技能: 使用 [{tools_str}] 完成 {steps_count} 步操作。"
            f" 成功 {pattern.success_count} 次，成功率 {pattern.success_rate:.0%}。"
        )

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    @property
    def pattern_count(self) -> int:
        """已记录的模式数量。"""
        return len(self._patterns)

    @property
    def suggestion_count(self) -> int:
        """建议总数。"""
        return len(self._suggestions)

    @property
    def pending_suggestions(self) -> list[SkillSuggestion]:
        """所有 pending 状态的建议。"""
        return [s for s in self._suggestions.values() if s.status == "pending"]
