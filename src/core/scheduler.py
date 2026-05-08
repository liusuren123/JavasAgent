"""任务调度器。

管理任务队列，支持优先级和并发控制。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from loguru import logger

from src.core.models import PlanStatus, TaskPlan


class Scheduler:
    """任务调度器。"""

    def __init__(self, max_concurrent: int = 1) -> None:
        self._max_concurrent = max_concurrent
        self._queue: asyncio.PriorityQueue[TaskPlan] = asyncio.PriorityQueue()
        self._running: dict[str, TaskPlan] = {}
        self._completed: dict[str, TaskPlan] = {}
        self._history: list[dict[str, Any]] = []

    @property
    def has_running_task(self) -> bool:
        """是否有正在运行的任务。"""
        return len(self._running) > 0

    @property
    def running_tasks(self) -> list[TaskPlan]:
        """当前运行中的任务列表。"""
        return list(self._running.values())

    @property
    def queue_size(self) -> int:
        """队列中等待的任务数。"""
        return self._queue.qsize()

    async def submit(self, plan: TaskPlan) -> str:
        """提交任务到队列。

        Args:
            plan: 任务计划

        Returns:
            任务 ID
        """
        plan.status = PlanStatus.PENDING
        await self._queue.put(plan)
        self._history.append({
            "plan_id": plan.id,
            "intent": plan.intent,
            "submitted_at": plan.created_at.isoformat(),
            "status": "queued",
        })
        logger.info(f"任务已入队: {plan.id} - {plan.intent[:50]} (优先级: {plan.priority.value})")
        return plan.id

    async def cancel(self, task_id: str) -> bool:
        """取消任务。

        Args:
            task_id: 任务 ID

        Returns:
            是否成功取消
        """
        if task_id in self._running:
            self._running[task_id].status = PlanStatus.PAUSED
            del self._running[task_id]
            logger.info(f"任务已取消: {task_id}")
            return True
        logger.warning(f"未找到运行中的任务: {task_id}")
        return False

    def mark_running(self, plan: TaskPlan) -> None:
        """标记任务为运行中。"""
        plan.status = PlanStatus.RUNNING
        self._running[plan.id] = plan
        logger.debug(f"任务标记为运行中: {plan.id}")

    def mark_done(self, plan: TaskPlan, success: bool) -> None:
        """标记任务完成。"""
        plan.status = PlanStatus.DONE if success else PlanStatus.FAILED
        self._running.pop(plan.id, None)
        self._completed[plan.id] = plan
        logger.info(f"任务完成: {plan.id} (成功: {success})")

    async def get_next(self) -> TaskPlan | None:
        """获取下一个待执行的任务。"""
        if len(self._running) >= self._max_concurrent:
            return None

        try:
            plan = self._queue.get_nowait()
            return plan
        except asyncio.QueueEmpty:
            return None

    def get_status(self) -> dict[str, Any]:
        """获取调度器状态。"""
        return {
            "running": len(self._running),
            "queued": self._queue.qsize(),
            "completed": len(self._completed),
            "max_concurrent": self._max_concurrent,
            "running_tasks": [
                {"id": p.id, "intent": p.intent[:50], "progress": p.progress}
                for p in self._running.values()
            ],
        }
