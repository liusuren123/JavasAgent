"""数据模型测试。"""

from src.core.models import (
    ActionItem,
    DecisionPoint,
    PlanStatus,
    Priority,
    Step,
    StepStatus,
    TaskPlan,
)


class TestStep:
    """Step 数据模型测试。"""

    def test_can_retry_default(self) -> None:
        step = Step(id="s1", action="test", tool="shell")
        assert step.can_retry is True
        assert step.retry_count == 0

    def test_can_retry_exhausted(self) -> None:
        step = Step(id="s1", action="test", tool="shell", retry_count=3, max_retries=3)
        assert step.can_retry is False

    def test_default_status(self) -> None:
        step = Step(id="s1", action="test", tool="shell")
        assert step.status == StepStatus.PENDING


class TestTaskPlan:
    """TaskPlan 数据模型测试。"""

    def _make_plan(self) -> TaskPlan:
        return TaskPlan(
            id="plan_test",
            intent="测试计划",
            steps=[
                Step(id="s0", action="步骤0", tool="shell"),
                Step(id="s1", action="步骤1", tool="shell", depends_on=["s0"]),
                Step(id="s2", action="步骤2", tool="shell", depends_on=["s0"]),
            ],
        )

    def test_progress_empty(self) -> None:
        plan = TaskPlan(id="p1", intent="空计划")
        assert plan.progress == 0.0

    def test_progress_partial(self) -> None:
        plan = self._make_plan()
        plan.steps[0].status = StepStatus.DONE
        assert plan.progress == pytest.approx(1.0 / 3.0)

    def test_progress_complete(self) -> None:
        plan = self._make_plan()
        for s in plan.steps:
            s.status = StepStatus.DONE
        assert plan.progress == 1.0

    def test_current_step_first(self) -> None:
        plan = self._make_plan()
        assert plan.current_step is not None
        assert plan.current_step.id == "s0"

    def test_current_step_with_deps(self) -> None:
        plan = self._make_plan()
        plan.steps[0].status = StepStatus.DONE
        step = plan.current_step
        assert step is not None
        assert step.id == "s1"

    def test_all_done_no_current(self) -> None:
        plan = self._make_plan()
        for s in plan.steps:
            s.status = StepStatus.DONE
        assert plan.current_step is None


class TestDecisionPoint:
    """DecisionPoint 测试。"""

    def test_default_values(self) -> None:
        dp = DecisionPoint(context="test", question="what?", confidence=0.8)
        assert dp.auto_decided is False
        assert dp.options == []
