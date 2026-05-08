"""反思审查引擎测试。"""

import asyncio

from src.core.models import (
    PlanStatus,
    ReflectionReport,
    Step,
    StepStatus,
    TaskPlan,
)
from src.core.reflector import Reflector
from src.utils.config import ReflectionConfig


class TestReflectorRuleBased:
    """Reflector 规则模式测试。"""

    def _make_plan(
        self,
        steps: list[Step] | None = None,
        status: PlanStatus = PlanStatus.RUNNING,
    ) -> TaskPlan:
        """创建测试用的 TaskPlan。"""
        if steps is None:
            steps = [
                Step(id="s0", action="初始化环境", tool="shell"),
                Step(id="s1", action="读取文件", tool="system_control", depends_on=["s0"]),
                Step(id="s2", action="输出结果", tool="shell", depends_on=["s1"]),
            ]
        return TaskPlan(
            id="plan_test",
            intent="测试计划",
            steps=steps,
            status=status,
        )

    def _make_reflector(
        self,
        checklist: list[str] | None = None,
    ) -> Reflector:
        """创建无 LLM 的 Reflector（纯规则模式）。"""
        config = ReflectionConfig(checklist=checklist or [])
        return Reflector(config=config, llm=None)

    def _reflect(self, plan: TaskPlan) -> ReflectionReport:
        """同步执行反思审查。"""
        return asyncio.get_event_loop().run_until_complete(
            self._make_reflector().reflect(plan)
        )

    # --- 基本功能测试 ---

    def test_all_pass(self) -> None:
        """所有步骤完成 → 大部分维度应通过，测试覆盖在规则模式下始终 warn。"""
        plan = self._make_plan()
        for s in plan.steps:
            s.status = StepStatus.DONE
        plan.status = PlanStatus.DONE

        report = self._reflect(plan)

        assert isinstance(report, ReflectionReport)
        # 规则模式下测试覆盖始终 warn，因此最高分为 6/7 ≈ 0.857
        assert report.overall_score >= 0.85
        assert report.should_continue is True
        # 除测试覆盖外其他维度都应 pass
        for dim, result in report.checklist_results.items():
            if dim != "测试覆盖":
                assert result == "pass", f"{dim} 应为 pass"

    def test_empty_plan(self) -> None:
        """空计划（无步骤）→ 功能完整性应失败。"""
        plan = TaskPlan(id="empty", intent="空计划", steps=[])
        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["功能完整性"] == "fail"
        assert any(
            item.category == "功能完整性" and item.severity == "high"
            for item in report.action_items
        )

    def test_failed_plan(self) -> None:
        """计划失败 → 目标对齐应为 fail。"""
        plan = self._make_plan()
        plan.steps[0].status = StepStatus.DONE
        plan.steps[1].status = StepStatus.FAILED
        plan.steps[2].status = StepStatus.SKIPPED
        plan.status = PlanStatus.FAILED

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["目标对齐"] == "fail"
        assert any(
            item.category == "目标对齐" and item.severity == "high"
            for item in report.action_items
        )

    def test_high_failure_rate(self) -> None:
        """高失败率 → 功能完整性应为 fail。"""
        steps = [
            Step(id=f"s{i}", action=f"步骤{i}", tool="shell")
            for i in range(4)
        ]
        steps[0].status = StepStatus.DONE
        steps[1].status = StepStatus.FAILED
        steps[2].status = StepStatus.FAILED
        steps[3].status = StepStatus.FAILED
        plan = self._make_plan(steps=steps)

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["功能完整性"] == "fail"

    def test_some_failures(self) -> None:
        """少量失败 → 功能完整性应为 warn。"""
        steps = [
            Step(id=f"s{i}", action=f"步骤{i}", tool="shell")
            for i in range(4)
        ]
        steps[0].status = StepStatus.DONE
        steps[1].status = StepStatus.DONE
        steps[2].status = StepStatus.DONE
        steps[3].status = StepStatus.FAILED
        plan = self._make_plan(steps=steps)

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["功能完整性"] == "warn"

    def test_many_skipped(self) -> None:
        """过多跳过步骤 → 性能应 warn。"""
        steps = [
            Step(id=f"s{i}", action=f"步骤{i}", tool="shell")
            for i in range(4)
        ]
        steps[0].status = StepStatus.DONE
        steps[1].status = StepStatus.SKIPPED
        steps[2].status = StepStatus.SKIPPED
        steps[3].status = StepStatus.SKIPPED
        plan = self._make_plan(steps=steps)

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["性能"] == "warn"

    def test_risky_actions_pending(self) -> None:
        """包含高风险操作 → 安全应 warn。"""
        plan = self._make_plan(steps=[
            Step(id="s0", action="读取文件", tool="shell"),
            Step(id="s1", action="删除临时文件", tool="shell"),
        ])
        plan.steps[0].status = StepStatus.DONE
        # s1 still pending → risky

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["安全"] == "warn"

    def test_risky_actions_done(self) -> None:
        """高风险操作已完成 → 安全应 pass。"""
        plan = self._make_plan(steps=[
            Step(id="s0", action="读取文件", tool="shell"),
            Step(id="s1", action="删除临时文件", tool="shell"),
        ])
        for s in plan.steps:
            s.status = StepStatus.DONE

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["安全"] == "pass"

    def test_complex_deps(self) -> None:
        """步骤依赖过深 → 架构应 warn。"""
        steps = [
            Step(id="s0", action="步骤0", tool="shell", depends_on=["a", "b", "c", "d"]),
        ]
        plan = self._make_plan(steps=steps)

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["架构"] == "warn"

    def test_low_progress_running(self) -> None:
        """低进度运行中 → 目标对齐应 warn。"""
        steps = [
            Step(id=f"s{i}", action=f"步骤{i}", tool="shell")
            for i in range(5)
        ]
        steps[0].status = StepStatus.DONE
        plan = self._make_plan(steps=steps, status=PlanStatus.RUNNING)

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["目标对齐"] == "warn"

    def test_many_retries(self) -> None:
        """重试次数过多 → 代码质量应 warn。"""
        steps = [
            Step(id="s0", action="步骤0", tool="shell", retry_count=5),
            Step(id="s1", action="步骤1", tool="shell", retry_count=4),
            Step(id="s2", action="步骤2", tool="shell", retry_count=3),
        ]
        # total_retries = 12 > total_steps * 2 = 6
        plan = self._make_plan(steps=steps)

        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.checklist_results["代码质量"] == "warn"

    # --- should_continue 逻辑测试 ---

    def test_should_continue_true_when_good(self) -> None:
        """状态良好时 should_continue 应为 True。"""
        plan = self._make_plan()
        for s in plan.steps:
            s.status = StepStatus.DONE
        plan.status = PlanStatus.DONE

        report = self._reflect(plan)
        assert report.should_continue is True

    def test_should_continue_false_on_high_severity(self) -> None:
        """存在 high severity 行动项时 should_continue 应为 False。"""
        plan = TaskPlan(id="empty", intent="空", steps=[])
        reflector = self._make_reflector()
        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.should_continue is False

    # --- 属性测试 ---

    def test_last_reflection_stored(self) -> None:
        """审查后 last_reflection 应被更新。"""
        plan = self._make_plan()
        reflector = self._make_reflector()

        assert reflector.last_reflection is None
        asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))
        assert reflector.last_reflection is not None
        assert isinstance(reflector.last_reflection, ReflectionReport)

    def test_checklist_default(self) -> None:
        """不指定 checklist 时应使用默认清单（7 个维度）。"""
        reflector = Reflector(config=ReflectionConfig(), llm=None)
        assert len(reflector.checklist) == 7
        assert "功能完整性" in reflector.checklist

    def test_checklist_custom(self) -> None:
        """指定 checklist 时应使用自定义清单。"""
        custom = ["自定义维度A", "自定义维度B"]
        reflector = self._make_reflector(checklist=custom)
        assert reflector.checklist == custom

    def test_checklist_immutable(self) -> None:
        """checklist 属性返回副本，修改不影响内部。"""
        reflector = self._make_reflector()
        cls = reflector.checklist
        cls.append("新维度")
        assert "新维度" not in reflector.checklist

    # --- summary 测试 ---

    def test_summary_contains_plan_info(self) -> None:
        """摘要应包含计划信息。"""
        plan = self._make_plan()
        for s in plan.steps:
            s.status = StepStatus.DONE

        report = self._reflect(plan)
        assert "测试计划" in report.summary
        assert "通过" in report.summary


class TestReflectorLLM:
    """Reflector LLM 模式测试（mock LLM）。"""

    def _make_mock_llm(self, return_value: str) -> object:
        """创建 mock LLM 客户端。"""
        from unittest.mock import AsyncMock, MagicMock

        mock = MagicMock()
        mock.chat_with_system = AsyncMock(return_value=return_value)
        return mock

    def test_llm_reflect_success(self) -> None:
        """LLM 返回有效 JSON → 应正确解析。"""
        mock_llm = self._make_mock_llm("""```json
{
    "checklist_results": {"功能完整性": "pass", "代码质量": "pass"},
    "overall_score": 0.9,
    "action_items": [],
    "should_continue": true,
    "summary": "LLM 审查通过"
}
```""")

        reflector = Reflector(config=ReflectionConfig(), llm=mock_llm)
        plan = TaskPlan(id="p1", intent="测试", steps=[
            Step(id="s0", action="步骤", tool="shell"),
        ])

        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.overall_score == 0.9
        assert report.should_continue is True
        assert report.summary == "LLM 审查通过"

    def test_llm_reflect_with_action_items(self) -> None:
        """LLM 返回带行动项的 JSON → 应正确解析。"""
        mock_llm = self._make_mock_llm("""```json
{
    "checklist_results": {"功能完整性": "warn", "代码质量": "fail"},
    "overall_score": 0.3,
    "action_items": [
        {
            "category": "代码质量",
            "description": "代码结构混乱",
            "severity": "high",
            "suggestion": "重构代码"
        }
    ],
    "should_continue": false,
    "summary": "需要修复"
}
```""")

        reflector = Reflector(config=ReflectionConfig(), llm=mock_llm)
        plan = TaskPlan(id="p1", intent="测试", steps=[
            Step(id="s0", action="步骤", tool="shell"),
        ])

        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert report.overall_score == 0.3
        assert report.should_continue is False
        assert len(report.action_items) == 1
        assert report.action_items[0].category == "代码质量"
        assert report.action_items[0].severity == "high"

    def test_llm_reflect_bad_json_fallback(self) -> None:
        """LLM 返回无效 JSON → 应使用默认报告。"""
        mock_llm = self._make_mock_llm("这不是JSON")

        reflector = Reflector(config=ReflectionConfig(), llm=mock_llm)
        plan = TaskPlan(id="p1", intent="测试", steps=[
            Step(id="s0", action="步骤", tool="shell"),
        ])

        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert isinstance(report, ReflectionReport)
        assert report.overall_score == 0.5
        assert report.should_continue is True

    def test_llm_reflect_exception_fallback(self) -> None:
        """LLM 抛出异常 → 应回退到规则审查。"""
        from unittest.mock import AsyncMock, MagicMock

        mock_llm = MagicMock()
        mock_llm.chat_with_system = AsyncMock(side_effect=Exception("API error"))

        reflector = Reflector(config=ReflectionConfig(), llm=mock_llm)
        plan = TaskPlan(id="p1", intent="测试", steps=[
            Step(id="s0", action="步骤", tool="shell"),
        ])

        report = asyncio.get_event_loop().run_until_complete(reflector.reflect(plan))

        assert isinstance(report, ReflectionReport)
        assert "功能完整性" in report.checklist_results
