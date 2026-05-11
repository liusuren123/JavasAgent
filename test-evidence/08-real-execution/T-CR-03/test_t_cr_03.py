"""T-CR-03: Scheduler 优先级队列 — 实操测试。

添加多个不同优先级任务，验证按优先级排序出队。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.core.models import Priority, Step, TaskPlan
from src.core.scheduler import Scheduler


def _make_plan(plan_id: str, intent: str, priority: Priority) -> TaskPlan:
    return TaskPlan(
        id=plan_id,
        intent=intent,
        steps=[Step(id="s0", action="do", tool="test")],
        priority=priority,
    )


@pytest.fixture
def scheduler():
    return Scheduler(max_concurrent=1)


@pytest.mark.asyncio
async def test_submit_and_queue_size(scheduler):
    """提交后队列大小应增加。"""
    plan = _make_plan("p1", "任务1", Priority.NORMAL)
    await scheduler.submit(plan)
    assert scheduler.queue_size == 1
    print(f"[OK] 提交后 queue_size=1")


@pytest.mark.asyncio
async def test_priority_ordering(scheduler):
    """高优先级任务应先出队。"""
    plans = [
        _make_plan("p_low", "低优先级", Priority.LOW),       # 0
        _make_plan("p_urgent", "紧急任务", Priority.URGENT), # 20
        _make_plan("p_normal", "普通任务", Priority.NORMAL), # 5
        _make_plan("p_high", "高优先级", Priority.HIGH),     # 10
    ]

    # 按随机顺序提交
    for plan in plans:
        await scheduler.submit(plan)

    assert scheduler.queue_size == 4

    # 取出并验证顺序
    results = []
    while scheduler.queue_size > 0:
        plan = await scheduler.get_next()
        if plan:
            results.append(plan)
            scheduler.mark_running(plan)
            scheduler.mark_done(plan, success=True)

    # 期望顺序：urgent(20) > high(10) > normal(5) > low(0)
    priority_values = [p.priority.value for p in results]
    assert priority_values == [20, 10, 5, 0], f"优先级顺序错误: {priority_values}"
    print(f"[OK] 出队顺序: {[p.intent for p in results]}")
    print(f"[OK] 优先级值: {priority_values}")


@pytest.mark.asyncio
async def test_max_concurrent_limit(scheduler):
    """达到 max_concurrent 时 get_next 应返回 None。"""
    plan = _make_plan("p1", "运行中", Priority.NORMAL)
    await scheduler.submit(plan)
    next_plan = await scheduler.get_next()
    assert next_plan is not None
    scheduler.mark_running(next_plan)

    # max_concurrent=1，已有运行任务，再取应返回 None
    assert scheduler.has_running_task is True
    next2 = await scheduler.get_next()
    assert next2 is None
    print(f"[OK] max_concurrent 限制生效: get_next 返回 None")


@pytest.mark.asyncio
async def test_cancel_running_task(scheduler):
    """取消运行中的任务。"""
    plan = _make_plan("p1", "可取消任务", Priority.NORMAL)
    await scheduler.submit(plan)
    next_plan = await scheduler.get_next()
    scheduler.mark_running(next_plan)

    cancelled = await scheduler.cancel("p1")
    assert cancelled is True
    assert not scheduler.has_running_task
    print(f"[OK] 取消任务成功")


@pytest.mark.asyncio
async def test_get_status(scheduler):
    """get_status 返回正确的状态信息。"""
    plan = _make_plan("p1", "状态测试", Priority.NORMAL)
    await scheduler.submit(plan)

    status = scheduler.get_status()
    assert status["queued"] == 1
    assert status["running"] == 0
    assert status["completed"] == 0
    print(f"[OK] 状态查询: queued={status['queued']}, running={status['running']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
