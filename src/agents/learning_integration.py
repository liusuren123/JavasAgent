"""学习集成模块。

封装 SkillLearner 与 SkillRegistry 的交互逻辑，
提供简洁接口供 BaseAgent 在执行循环的各阶段调用。

Usage::

    integration = LearningIntegration(storage_dir="./data/learning")
    await integration.initialize()

    # 规划前获取技能建议
    suggestions = await integration.on_planning_start(context)

    # 执行完成后记录并学习
    await integration.on_execution_complete(plan, result)

    # 确认注册建议
    skill = await integration.approve_and_register(suggestion_id)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from src.core.models import ExecutionResult, TaskPlan
from src.memory.skill_models import SkillDefinition, SkillSuggestion
from src.memory.skill_learner import SkillLearner
from src.memory.skill_registry import SkillRegistry


class LearningIntegration:
    """学习集成类。

    将 SkillLearner（模式提取）和 SkillRegistry（技能注册）组合为
    统一接口，供 BaseAgent 在任务执行循环中使用。

    职责：
    - 执行完成后记录执行历史，让 SkillLearner 学习模式
    - 规划前查询可复用的已学技能，返回建议列表
    - 提供确认/拒绝建议的接口，将建议转为正式注册技能
    """

    def __init__(
        self,
        storage_dir: str | Path | None = None,
        min_success_count: int = 3,
        min_success_rate: float = 0.6,
    ) -> None:
        """初始化学习集成。

        Args:
            storage_dir: 持久化目录。None 则仅内存模式。
            min_success_count: 触发建议的最低成功次数。
            min_success_rate: 触发建议的最低成功率。
        """
        self._learner = SkillLearner(
            storage_dir=storage_dir,
            min_success_count=min_success_count,
            min_success_rate=min_success_rate,
        )
        self._registry = SkillRegistry(storage_dir=storage_dir)
        self._initialized = False
        logger.debug(
            "LearningIntegration 初始化 (dir={})",
            storage_dir or "内存模式",
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """初始化学习器和注册表（从磁盘加载数据）。

        应在 Agent 启动时调用一次。
        """
        await self._learner.initialize()
        await self._registry.initialize()
        self._initialized = True
        logger.info(
            "LearningIntegration 初始化完成: {} 个模式, {} 个已注册技能",
            self._learner.pattern_count,
            self._registry.count,
        )

    async def save(self) -> None:
        """持久化学习器和注册表数据到磁盘。

        应在 Agent 关闭前调用。
        """
        await self._learner.save()
        await self._registry.save()
        logger.debug("LearningIntegration 数据已保存")

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    async def on_execution_complete(
        self,
        plan: TaskPlan,
        result: ExecutionResult,
    ) -> None:
        """任务执行完成后调用：记录执行历史并尝试生成建议。

        将执行记录交给 SkillLearner 分析，如果检测到可复用模式
        且达到阈值，自动生成技能注册建议。

        Args:
            plan: 任务计划
            result: 执行结果
        """
        # 1. 记录执行
        await self._learner.record_execution(plan, result)

        # 2. 检查是否有新的建议
        new_suggestions = await self._learner.suggest_skills()
        if new_suggestions:
            for suggestion in new_suggestions:
                logger.info(
                    "发现可复用模式 → 建议注册技能: {} (成功率 {:.0%})",
                    suggestion.suggested_name,
                    suggestion.pattern.success_rate,
                )

        # 3. 持久化
        await self._learner.save()

        logger.debug(
            "执行记录已处理: plan={}, success={}, patterns={}",
            plan.id,
            result.success,
            self._learner.pattern_count,
        )

    async def on_planning_start(
        self,
        context: str = "",
    ) -> list[SkillSuggestion]:
        """规划新任务前调用：返回当前可用的技能建议。

        从 SkillLearner 中获取所有 pending 状态的建议，
        供规划器参考以复用已学模式。

        Args:
            context: 当前任务上下文（预留扩展用）。

        Returns:
            pending 状态的技能建议列表
        """
        suggestions = self._learner.pending_suggestions
        if suggestions:
            names = [s.suggested_name for s in suggestions]
            logger.debug("规划时发现 {} 个可复用技能: {}", len(suggestions), names)
        return suggestions

    async def approve_and_register(
        self,
        suggestion_id: str,
    ) -> SkillDefinition | None:
        """确认注册一条技能建议。

        将 SkillLearner 中的建议转为 SkillDefinition 并注册到
        SkillRegistry，完成学习闭环。

        Args:
            suggestion_id: 建议 ID

        Returns:
            注册成功的技能定义，失败返回 None
        """
        try:
            skill_def = await self._learner.approve_suggestion(suggestion_id)
        except (KeyError, ValueError) as e:
            logger.warning("确认建议失败 (id={}): {}", suggestion_id, e)
            return None

        # 注册到 SkillRegistry
        skill_id = await self._registry.register(skill_def)
        logger.info("技能已注册: {} ({})", skill_def.name, skill_id)

        # 持久化
        await self._learner.save()
        await self._registry.save()

        return skill_def

    async def reject_suggestion(self, suggestion_id: str) -> bool:
        """拒绝一条技能建议。

        Args:
            suggestion_id: 建议 ID

        Returns:
            是否成功拒绝
        """
        result = await self._learner.reject_suggestion(suggestion_id)
        if result:
            await self._learner.save()
            logger.debug("建议已拒绝: {}", suggestion_id)
        return result

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    async def search_skills(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[SkillDefinition]:
        """搜索已注册的技能。

        Args:
            query: 搜索关键词
            category: 按类别过滤
            top_k: 返回最多 K 个结果

        Returns:
            匹配的技能列表
        """
        return await self._registry.search(query, category=category, top_k=top_k)

    async def list_registered_skills(
        self,
        category: str | None = None,
    ) -> list[SkillDefinition]:
        """列出所有已注册的技能。

        Args:
            category: 按类别过滤

        Returns:
            技能列表
        """
        return await self._registry.list_all(category=category)

    @property
    def pattern_count(self) -> int:
        """已记录的学习模式数量。"""
        return self._learner.pattern_count

    @property
    def suggestion_count(self) -> int:
        """建议总数。"""
        return self._learner.suggestion_count

    @property
    def registered_count(self) -> int:
        """已注册技能数量。"""
        return self._registry.count
