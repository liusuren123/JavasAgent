"""任务调度器测试。"""

import asyncio

import pytest

from src.core.models import PlanStatus, Priority, Step, StepStatus, TaskPlan
from src.core.scheduler import Scheduler


class TestScheduler:
    """Scheduler 基本功能测试。"""

    def _make_plan(
        self,
        plan_id: str = "plan_test",
        intent: str = "测试任务",
        priority: Priority = Priority.NORMAL,
    ) -> TaskPlan:
        return TaskPlan(
            id=plan_id,
            intent=intent,
            steps=[Step(id="s0", action="步骤", tool="shell")],
            priority=priority,
        )

    def _make_scheduler(self, max_concurrent: int = 1) -> Scheduler:
        return Scheduler(max_concurrent=max_concurrent)

    # --- 提交测试 ---

    def test_submit_plan(self) -> None:
        """提交任务应返回 plan_id。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()

        plan_id = asyncio.get_event_loop().run_until_complete(scheduler.submit(plan))

        assert plan_id == "plan_test"
        assert scheduler.queue_size == 1

    def test_submit_multiple_plans(self) -> None:
        """提交多个不同优先级的任务应入队。

        注意：PriorityQueue 要求元素可比较。相同优先级的 TaskPlan
        不具备可比性，因此使用不同优先级。
        """
        scheduler = self._make_scheduler()

        plans = [
            self._make_plan(f"plan_{i}", priority=p)
            for i, p in enumerate([Priority.LOW, Priority.NORMAL, Priority.HIGH])
        ]

        async def submit_all():
            for p in plans:
                await scheduler.submit(p)

        asyncio.get_event_loop().run_until_complete(submit_all())
        assert scheduler.queue_size == 3

    def test_submit_sets_pending(self) -> None:
        """提交后 plan 状态应为 PENDING。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        plan.status = PlanStatus.RUNNING  # 先设为非 PENDING

        asyncio.get_event_loop().run_until_complete(scheduler.submit(plan))

        assert plan.status == PlanStatus.PENDING

    # --- 取消测试 ---

    def test_cancel_running_task(self) -> None:
        """取消运行中的任务应成功。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)

        result = asyncio.get_event_loop().run_until_complete(scheduler.cancel("plan_test"))

        assert result is True
        assert plan.status == PlanStatus.PAUSED
        assert not scheduler.has_running_task

    def test_cancel_nonexistent_task(self) -> None:
        """取消不存在的任务应返回 False。"""
        scheduler = self._make_scheduler()

        result = asyncio.get_event_loop().run_until_complete(scheduler.cancel("nonexistent"))

        assert result is False

    # --- 状态查询测试 ---

    def test_get_status_empty(self) -> None:
        """空调度器状态。"""
        scheduler = self._make_scheduler()
        status = scheduler.get_status()

        assert status["running"] == 0
        assert status["queued"] == 0
        assert status["completed"] == 0
        assert status["max_concurrent"] == 1

    def test_get_status_with_running(self) -> None:
        """有运行中任务的状态。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)

        status = scheduler.get_status()

        assert status["running"] == 1
        assert len(status["running_tasks"]) == 1
        assert status["running_tasks"][0]["id"] == "plan_test"

    def test_get_status_after_complete(self) -> None:
        """任务完成后的状态。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)
        scheduler.mark_done(plan, success=True)

        status = scheduler.get_status()

        assert status["running"] == 0
        assert status["completed"] == 1

    def test_get_status_after_failure(self) -> None:
        """任务失败后的状态。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)
        scheduler.mark_done(plan, success=False)

        status = scheduler.get_status()

        assert status["running"] == 0
        assert status["completed"] == 1
        assert plan.status == PlanStatus.FAILED

    # --- get_next 测试 ---

    def test_get_next_from_queue(self) -> None:
        """从队列获取下一个任务。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()

        loop = asyncio.get_event_loop()
        loop.run_until_complete(scheduler.submit(plan))
        next_plan = loop.run_until_complete(scheduler.get_next())

        assert next_plan is not None
        assert next_plan.id == "plan_test"

    def test_get_next_empty_queue(self) -> None:
        """空队列获取下一个应返回 None。"""
        scheduler = self._make_scheduler()

        result = asyncio.get_event_loop().run_until_complete(scheduler.get_next())

        assert result is None

    def test_get_next_respects_concurrency(self) -> None:
        """超过最大并发数时不应返回新任务。

        使用不同优先级避免 PriorityQueue 比较问题。
        """
        scheduler = self._make_scheduler(max_concurrent=1)
        plan1 = self._make_plan("plan_1", priority=Priority.HIGH)
        plan2 = self._make_plan("plan_2", priority=Priority.LOW)

        async def setup():
            await scheduler.submit(plan1)
            await scheduler.submit(plan2)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(setup())

        # 取出第一个
        first = loop.run_until_complete(scheduler.get_next())
        assert first is not None
        scheduler.mark_running(first)

        # 已达并发上限
        second = loop.run_until_complete(scheduler.get_next())
        assert second is None

    # --- mark_running / mark_done 测试 ---

    def test_mark_running(self) -> None:
        """标记运行中应更新状态和内部字典。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)

        assert plan.status == PlanStatus.RUNNING
        assert scheduler.has_running_task is True
        assert len(scheduler.running_tasks) == 1
        assert scheduler.running_tasks[0].id == "plan_test"

    def test_mark_done_success(self) -> None:
        """标记成功完成。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)
        scheduler.mark_done(plan, success=True)

        assert plan.status == PlanStatus.DONE
        assert scheduler.has_running_task is False

    def test_mark_done_failure(self) -> None:
        """标记失败完成。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)
        scheduler.mark_done(plan, success=False)

        assert plan.status == PlanStatus.FAILED
        assert scheduler.has_running_task is False

    def test_mark_done_removes_from_running(self) -> None:
        """完成后应从 running 中移除。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)
        assert scheduler.has_running_task is True

        scheduler.mark_done(plan, success=True)
        assert scheduler.has_running_task is False
        assert scheduler.running_tasks == []

    # --- 边界情况测试 ---

    def test_multiple_concurrent(self) -> None:
        """多个并发任务。使用不同优先级避免 PriorityQueue 比较问题。"""
        scheduler = self._make_scheduler(max_concurrent=3)
        priorities = [Priority.LOW, Priority.NORMAL, Priority.HIGH]
        plans = [self._make_plan(f"plan_{i}", priority=priorities[i]) for i in range(3)]

        async def submit_and_get():
            for p in plans:
                await scheduler.submit(p)
                next_p = await scheduler.get_next()
                assert next_p is not None
                scheduler.mark_running(next_p)

        asyncio.get_event_loop().run_until_complete(submit_and_get())

        assert len(scheduler.running_tasks) == 3
        assert scheduler.get_status()["running"] == 3

    def test_cancel_already_completed(self) -> None:
        """取消已完成的任务应返回 False。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        scheduler.mark_running(plan)
        scheduler.mark_done(plan, success=True)

        result = asyncio.get_event_loop().run_until_complete(scheduler.cancel("plan_test"))
        assert result is False

    def test_history_recorded_on_submit(self) -> None:
        """提交任务时应记录历史。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()

        asyncio.get_event_loop().run_until_complete(scheduler.submit(plan))

        assert len(scheduler._history) == 1
        assert scheduler._history[0]["plan_id"] == "plan_test"
        assert scheduler._history[0]["status"] == "queued"

    def test_status_running_tasks_includes_progress(self) -> None:
        """运行中任务状态应包含进度信息。"""
        scheduler = self._make_scheduler()
        plan = self._make_plan()
        plan.steps[0].status = StepStatus.DONE
        scheduler.mark_running(plan)

        status = scheduler.get_status()
        task_info = status["running_tasks"][0]
        assert task_info["progress"] == 1.0

    # --- PriorityQueue 优先级排序测试 ---

    def test_same_priority_plans_no_crash(self) -> None:
        """相同优先级的多个任务不应因比较失败而报错。

        验证 _PrioritizedPlan 包装通过序列号解决同优先级比较问题。
        """
        scheduler = self._make_scheduler()
        plans = [
            self._make_plan(f"plan_{i}", priority=Priority.NORMAL)
            for i in range(5)
        ]

        async def submit_all():
            for p in plans:
                await scheduler.submit(p)

        asyncio.get_event_loop().run_until_complete(submit_all())
        assert scheduler.queue_size == 5

    def test_priority_ordering(self) -> None:
        """优先级高的任务应先出队。"""
        scheduler = self._make_scheduler()

        low = self._make_plan("low", priority=Priority.LOW)
        high = self._make_plan("high", priority=Priority.HIGH)
        normal = self._make_plan("normal", priority=Priority.NORMAL)

        async def submit_all():
            await scheduler.submit(low)
            await scheduler.submit(high)
            await scheduler.submit(normal)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(submit_all())

        first = loop.run_until_complete(scheduler.get_next())
        assert first is not None
        assert first.id == "high"  # HIGH 优先出队

        second = loop.run_until_complete(scheduler.get_next())
        assert second is not None
        assert second.id == "normal"  # NORMAL 第二

        third = loop.run_until_complete(scheduler.get_next())
        assert third is not None
        assert third.id == "low"  # LOW 最后

    def test_fifo_for_same_priority(self) -> None:
        """同优先级任务应按 FIFO 顺序出队。"""
        scheduler = self._make_scheduler()
        plans = [
            self._make_plan(f"plan_{i}", priority=Priority.NORMAL)
            for i in range(3)
        ]

        async def submit_all():
            for p in plans:
                await scheduler.submit(p)

        loop = asyncio.get_event_loop()
        loop.run_until_complete(submit_all())

        for expected_id in ["plan_0", "plan_1", "plan_2"]:
            plan = loop.run_until_complete(scheduler.get_next())
            assert plan is not None
            assert plan.id == expected_id
