"""技能自动优化器模块。

监听 SkillLearner 产生的新技能建议，当模式被成功验证后自动注册到
SkillRegistry，并根据使用频率和成功率动态调整技能优先级。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.models import ExecutionResult, StepStatus, TaskPlan
from src.memory.skill_auto_updater_models import SkillUpdate, ToolUsageRecord
from src.memory.skill_models import SkillDefinition, SkillSuggestion
from src.memory.skill_registry import SkillRegistry

# 自动注册阈值：成功次数 ≥ 此值时自动注册
REGISTER_THRESHOLD = 3
# 默认清理天数
STALE_DEFAULT_DAYS = 30


class SkillAutoUpdater:
    """技能自动优化器。

    监听 SkillLearner 产生的新技能建议，当模式被成功验证后
    自动注册到 SkillRegistry，并根据使用频率和成功率动态
    调整技能优先级。

    Usage::

        registry = SkillRegistry()
        updater = SkillAutoUpdater(skill_registry=registry, data_dir=Path("./data"))

        # 学习器产生建议后通知
        await updater.on_skill_suggestion(suggestion)

        # 任务完成后更新使用记录
        await updater.on_task_completed(plan, result)

        # 获取推荐工具
        tools = updater.get_recommended_tools("截取屏幕并保存文件")
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        data_dir: Path | None = None,
    ) -> None:
        """初始化技能自动优化器。

        Args:
            skill_registry: 技能注册表实例。
            data_dir: 持久化目录路径。None 则仅内存模式。
        """
        self._registry = skill_registry
        self._data_dir = data_dir

        # 挂起的建议：suggestion_id -> SkillSuggestion
        self._pending_suggestions: dict[str, SkillSuggestion] = {}
        # 已注册的技能更新：skill_id -> SkillUpdate
        self._skill_updates: dict[str, SkillUpdate] = {}
        # 工具使用记录：tool_name -> ToolUsageRecord
        self._tool_records: dict[str, ToolUsageRecord] = {}

        # 持久化文件路径
        self._state_file: Path | None = None
        if self._data_dir is not None:
            self._data_dir.mkdir(parents=True, exist_ok=True)
            self._state_file = self._data_dir / "skill_updates.json"

        logger.debug(
            "SkillAutoUpdater 初始化 (dir={})",
            self._data_dir or "内存模式",
        )

    # ------------------------------------------------------------------
    # 技能建议处理
    # ------------------------------------------------------------------

    async def on_skill_suggestion(self, suggestion: SkillSuggestion) -> bool:
        """处理学习器产生的技能建议。

        当建议对应的模式成功次数 ≥ REGISTER_THRESHOLD 时，
        自动将其注册到 SkillRegistry。

        Args:
            suggestion: 技能建议

        Returns:
            是否触发了自动注册
        """
        pattern = suggestion.pattern
        self._pending_suggestions[suggestion.id] = suggestion
        logger.debug(
            "收到技能建议: {} (success={}/{})",
            suggestion.suggested_name,
            pattern.success_count,
            pattern.total_count,
        )

        if pattern.success_count >= REGISTER_THRESHOLD:
            registered = await self._auto_register(suggestion)
            return registered
        return False

    async def _auto_register(self, suggestion: SkillSuggestion) -> bool:
        """将建议自动注册为正式技能。"""
        pattern = suggestion.pattern

        skill_def = SkillDefinition.create(
            name=suggestion.suggested_name,
            description=suggestion.suggested_description,
            category=suggestion.suggested_category,
            source="auto_learned",
            pattern_steps=pattern.steps,
            tags=pattern.tools_used,
            metadata={
                "pattern_key": pattern.pattern_key,
                "success_count": pattern.success_count,
                "success_rate": pattern.success_rate,
                "suggestion_id": suggestion.id,
                "auto_registered": True,
            },
        )

        skill_id = await self._registry.register(skill_def)
        suggestion.status = "approved"

        update = SkillUpdate(
            skill_id=skill_id,
            suggestion_id=suggestion.id,
            registered_at=time.time(),
        )
        self._skill_updates[skill_id] = update
        self._pending_suggestions.pop(suggestion.id, None)

        # 初始化关联工具的使用记录
        for tool_name in pattern.tools_used:
            if tool_name not in self._tool_records:
                self._tool_records[tool_name] = ToolUsageRecord(
                    tool_name=tool_name,
                    success_count=pattern.success_count,
                    last_used=time.time(),
                )

        logger.info(
            "自动注册技能: {} ({}), pattern tools={}",
            skill_def.name,
            skill_id,
            pattern.tools_used,
        )
        self.save_state()
        return True

    # ------------------------------------------------------------------
    # 任务完成处理
    # ------------------------------------------------------------------

    async def on_task_completed(
        self,
        task_plan: TaskPlan,
        result: ExecutionResult,
    ) -> None:
        """任务完成后更新使用记录。

        从 TaskPlan 的步骤中提取使用的工具，更新每个工具的
        成功/失败计数和执行时间。
        """
        for step in task_plan.steps:
            tool_name = step.tool
            if not tool_name:
                continue

            record = self._tool_records.get(tool_name)
            if record is None:
                record = ToolUsageRecord(tool_name=tool_name)
                self._tool_records[tool_name] = record

            step_success = step.status == StepStatus.DONE
            exec_time = 0.0  # Step 模型暂无执行时间字段

            if step_success:
                record.record_success(exec_time)
            else:
                record.record_failure(exec_time)

        self._update_skill_effectiveness(task_plan, result)
        logger.debug(
            "任务完成: plan={}, success={}, tools tracked={}",
            task_plan.id,
            result.success,
            len(task_plan.steps),
        )
        self.save_state()

    def _update_skill_effectiveness(
        self,
        task_plan: TaskPlan,
        result: ExecutionResult,
    ) -> None:
        """更新技能的有效性分数。

        有效性分数 = 关联工具成功率的均值
        """
        tools_used = {step.tool for step in task_plan.steps if step.tool}

        for skill_id, update in self._skill_updates.items():
            skill = self._registry._skills.get(skill_id)
            if skill is None:
                continue

            skill_tools = set(skill.tags)
            if not skill_tools.intersection(tools_used):
                continue

            update.usage_count += 1

            tool_scores: list[float] = []
            for tool_name in skill_tools:
                rec = self._tool_records.get(tool_name)
                if rec and rec.total_count > 0:
                    tool_scores.append(rec.success_rate)

            if tool_scores:
                update.effectiveness_score = sum(tool_scores) / len(tool_scores)

    # ------------------------------------------------------------------
    # 工具推荐
    # ------------------------------------------------------------------

    def get_recommended_tools(self, task_description: str) -> list[str]:
        """基于历史经验推荐最适合的工具组合。

        根据工具的成功率、使用频率和平均执行时间进行排序。

        Args:
            task_description: 任务描述（用于未来扩展语义匹配）

        Returns:
            按推荐度排序的工具名称列表
        """
        if not self._tool_records:
            return []

        scored: list[tuple[str, float]] = []
        for tool_name, record in self._tool_records.items():
            if record.total_count == 0:
                continue

            success_weight = record.success_rate
            frequency_factor = min(1.0, record.total_count / 10.0)

            if record.last_used > 0:
                days_since = (time.time() - record.last_used) / 86400.0
                recency_factor = max(0.1, 1.0 / (1.0 + days_since / 7.0))
            else:
                recency_factor = 0.1

            score = success_weight * frequency_factor * recency_factor
            scored.append((tool_name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [name for name, _ in scored]

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_skill_stats(self) -> dict[str, Any]:
        """获取技能优化的统计信息。"""
        total_auto_registered = len(self._skill_updates)
        effective_skills = sum(
            1 for u in self._skill_updates.values() if u.effectiveness_score >= 0.6
        )
        pending_count = len(self._pending_suggestions)

        tool_stats: list[dict[str, Any]] = []
        for tool_name, record in self._tool_records.items():
            tool_stats.append({
                "tool_name": tool_name,
                "success_count": record.success_count,
                "failure_count": record.failure_count,
                "success_rate": round(record.success_rate, 4),
                "avg_execution_time": round(record.avg_execution_time, 4),
            })

        update_stats: list[dict[str, Any]] = []
        for skill_id, update in self._skill_updates.items():
            update_stats.append({
                "skill_id": skill_id,
                "suggestion_id": update.suggestion_id,
                "usage_count": update.usage_count,
                "effectiveness_score": round(update.effectiveness_score, 4),
            })

        return {
            "total_auto_registered": total_auto_registered,
            "effective_skills": effective_skills,
            "pending_suggestions": pending_count,
            "tracked_tools": len(self._tool_records),
            "tool_records": tool_stats,
            "skill_updates": update_stats,
        }

    # ------------------------------------------------------------------
    # 批量注册与清理
    # ------------------------------------------------------------------

    async def auto_register_skills(self) -> int:
        """自动注册所有满足条件的挂起建议。

        Returns:
            本次注册的技能数量
        """
        registered_count = 0
        suggestion_ids = list(self._pending_suggestions.keys())

        for suggestion_id in suggestion_ids:
            suggestion = self._pending_suggestions.get(suggestion_id)
            if suggestion is None:
                continue
            if suggestion.pattern.success_count >= REGISTER_THRESHOLD:
                await self._auto_register(suggestion)
                registered_count += 1

        if registered_count > 0:
            logger.info("批量自动注册了 {} 个技能", registered_count)
            self.save_state()
        return registered_count

    async def cleanup_stale_skills(self, days: int = STALE_DEFAULT_DAYS) -> int:
        """清理长期未使用且成功率低的技能。

        条件：超过指定天数未使用 且 有效性分数低于 0.5 且
        关联工具也长期未使用。

        Args:
            days: 未使用的天数阈值

        Returns:
            清理的技能数量
        """
        cutoff_time = time.time() - days * 86400
        stale_skill_ids: list[str] = []

        for skill_id, update in list(self._skill_updates.items()):
            if update.registered_at >= cutoff_time:
                continue
            if update.effectiveness_score >= 0.5:
                continue

            skill = self._registry._skills.get(skill_id)
            if skill is None:
                continue

            tools_stale = True
            for tool_name in skill.tags:
                rec = self._tool_records.get(tool_name)
                if rec and rec.last_used >= cutoff_time:
                    tools_stale = False
                    break
            if tools_stale:
                stale_skill_ids.append(skill_id)

        cleaned = 0
        for skill_id in stale_skill_ids:
            unregistered = await self._registry.unregister(skill_id)
            if unregistered:
                self._skill_updates.pop(skill_id, None)
                cleaned += 1
                logger.info("清理过期技能: {}", skill_id)

        if cleaned > 0:
            logger.info("清理了 {} 个过期技能", cleaned)
            self.save_state()
        return cleaned

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def save_state(self) -> None:
        """将当前状态保存到 JSON 文件。"""
        if self._state_file is None:
            return

        state = {
            "pending_suggestions": {
                sid: s.to_dict() for sid, s in self._pending_suggestions.items()
            },
            "skill_updates": {
                sid: u.to_dict() for sid, u in self._skill_updates.items()
            },
            "tool_records": {
                name: r.to_dict() for name, r in self._tool_records.items()
            },
        }

        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("SkillAutoUpdater 状态已保存到 {}", self._state_file)

    def load_state(self) -> None:
        """从 JSON 文件加载状态。"""
        if self._state_file is None or not self._state_file.exists():
            return

        try:
            raw = self._state_file.read_text(encoding="utf-8")
            state = json.loads(raw) if raw.strip() else {}

            self._pending_suggestions = {
                sid: SkillSuggestion.from_dict(s)
                for sid, s in state.get("pending_suggestions", {}).items()
            }
            self._skill_updates = {
                sid: SkillUpdate.from_dict(u)
                for sid, u in state.get("skill_updates", {}).items()
            }
            self._tool_records = {
                name: ToolUsageRecord.from_dict(r)
                for name, r in state.get("tool_records", {}).items()
            }

            logger.info(
                "SkillAutoUpdater 状态已加载: {} pending, {} updates, {} tools",
                len(self._pending_suggestions),
                len(self._skill_updates),
                len(self._tool_records),
            )
        except Exception:
            logger.exception("加载 SkillAutoUpdater 状态失败: {}", self._state_file)
