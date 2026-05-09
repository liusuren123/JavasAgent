"""技能执行引擎测试。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.memory.skill_models import SkillDefinition
from src.memory.skill_registry import SkillRegistry
from src.tools.skill_executor import SkillExecutor
from src.tools.skill_executor_models import (
    ExecutionRecord,
    SkillChainResult,
    SkillChainStep,
    SkillMatch,
)


# ---------------------------------------------------------------------------
# 辅助 fixtures
# ---------------------------------------------------------------------------


def _make_skill(
    name: str = "测试技能",
    description: str = "用于测试的技能",
    category: str = "tool",
    parameters: dict | None = None,
    tags: list[str] | None = None,
) -> SkillDefinition:
    """创建测试用的 SkillDefinition。"""
    return SkillDefinition.create(
        name=name,
        description=description,
        category=category,
        parameters=parameters or {},
        tags=tags or [name],
    )


def _make_registry_with_skills(*skills: SkillDefinition) -> SkillRegistry:
    """创建包含指定技能的注册表（内存模式）。"""
    registry = SkillRegistry()
    for skill in skills:
        registry._skills[skill.id] = skill
        registry._name_index[skill.name] = skill.id
    return registry


async def _register_skills_async(registry: SkillRegistry, *skills: SkillDefinition) -> None:
    """异步注册技能到注册表。"""
    for skill in skills:
        await registry.register(skill)


# ---------------------------------------------------------------------------
# 测试：execute_skill 执行已知技能
# ---------------------------------------------------------------------------


class TestExecuteSkill:
    """测试直接执行指定技能。"""

    @pytest.mark.asyncio
    async def test_execute_known_skill(self) -> None:
        """执行已注册且有执行函数的技能应返回成功。"""
        skill = _make_skill(name="截图", description="截取屏幕截图")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        async def mock_fn(params: dict) -> dict:
            return {"path": "/tmp/screenshot.png"}

        executor.register_executor("截图", mock_fn)

        result = await executor.execute("execute_skill", {
            "skill_name": "截图",
            "params": {"region": "full"},
        })

        assert result["success"] is True
        assert result["data"]["path"] == "/tmp/screenshot.png"
        assert "duration_ms" in result

    @pytest.mark.asyncio
    async def test_execute_sync_function(self) -> None:
        """执行同步的执行函数也应正常工作。"""
        skill = _make_skill(name="计算", description="执行计算")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        def sync_fn(params: dict) -> dict:
            return {"result": 42}

        executor.register_executor("计算", sync_fn)

        result = await executor.execute("execute_skill", {
            "skill_name": "计算",
            "params": {},
        })

        assert result["success"] is True
        assert result["data"]["result"] == 42

    @pytest.mark.asyncio
    async def test_execute_skill_with_empty_params(self) -> None:
        """不传 params 时应使用空字典。"""
        skill = _make_skill(name="问候", description="打招呼")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        async def greet(params: dict) -> dict:
            return {"message": "hello"}

        executor.register_executor("问候", greet)

        result = await executor.execute("execute_skill", {
            "skill_name": "问候",
        })

        assert result["success"] is True


# ---------------------------------------------------------------------------
# 测试：技能不存在时的错误处理
# ---------------------------------------------------------------------------


class TestSkillNotFound:
    """测试技能不存在的情况。"""

    @pytest.mark.asyncio
    async def test_skill_not_registered(self) -> None:
        """执行不存在的技能应返回失败。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        result = await executor.execute("execute_skill", {
            "skill_name": "不存在的技能",
            "params": {},
        })

        assert result["success"] is False
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_skill_exists_but_no_executor(self) -> None:
        """技能已注册但没有执行函数应返回失败。"""
        skill = _make_skill(name="无执行器", description="没有执行函数")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        result = await executor.execute("execute_skill", {
            "skill_name": "无执行器",
            "params": {},
        })

        assert result["success"] is False
        assert "没有注册执行函数" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_skill_name_param(self) -> None:
        """不传 skill_name 参数应返回失败。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        result = await executor.execute("execute_skill", {"params": {}})

        assert result["success"] is False
        assert "缺少 skill_name" in result["error"]


# ---------------------------------------------------------------------------
# 测试：参数校验
# ---------------------------------------------------------------------------


class TestParamValidation:
    """测试参数校验逻辑。"""

    @pytest.mark.asyncio
    async def test_missing_required_param(self) -> None:
        """缺少必填参数应返回失败。"""
        skill = _make_skill(
            name="文件操作",
            description="操作文件",
            parameters={
                "required": ["file_path"],
                "properties": {
                    "file_path": {"type": "string"},
                },
            },
        )
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("文件操作", lambda p: {})

        result = await executor.execute("execute_skill", {
            "skill_name": "文件操作",
            "params": {},
        })

        assert result["success"] is False
        assert "缺少必填参数" in result["error"]
        assert "file_path" in result["error"]

    @pytest.mark.asyncio
    async def test_wrong_param_type(self) -> None:
        """参数类型错误应返回失败。"""
        skill = _make_skill(
            name="数值计算",
            description="计算数值",
            parameters={
                "required": [],
                "properties": {
                    "count": {"type": "integer"},
                },
            },
        )
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("数值计算", lambda p: {})

        result = await executor.execute("execute_skill", {
            "skill_name": "数值计算",
            "params": {"count": "not_a_number"},
        })

        assert result["success"] is False
        assert "类型错误" in result["error"]

    @pytest.mark.asyncio
    async def test_valid_params_pass(self) -> None:
        """参数校验通过时应正常执行。"""
        skill = _make_skill(
            name="合法参数",
            description="合法参数测试",
            parameters={
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                },
            },
        )
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        async def valid_fn(params: dict) -> dict:
            return {"greeting": f"hello {params['name']}"}

        executor.register_executor("合法参数", valid_fn)

        result = await executor.execute("execute_skill", {
            "skill_name": "合法参数",
            "params": {"name": "test"},
        })

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_no_schema_skips_validation(self) -> None:
        """没有参数 schema 时应跳过校验。"""
        skill = _make_skill(name="无参数", description="无参数 schema")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("无参数", lambda p: {"ok": True})

        result = await executor.execute("execute_skill", {
            "skill_name": "无参数",
            "params": {"anything": "goes"},
        })

        assert result["success"] is True


# ---------------------------------------------------------------------------
# 测试：执行历史
# ---------------------------------------------------------------------------


class TestExecutionHistory:
    """测试执行历史记录。"""

    @pytest.mark.asyncio
    async def test_successful_execution_recorded(self) -> None:
        """成功执行应被记录到历史。"""
        skill = _make_skill(name="历史记录", description="测试历史记录")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("历史记录", lambda p: {"ok": True})

        await executor.execute("execute_skill", {
            "skill_name": "历史记录",
            "params": {},
        })

        assert executor.history_count == 1
        history = await executor.get_execution_history()
        assert len(history) == 1
        assert history[0].skill_name == "历史记录"
        assert history[0].success is True
        assert history[0].duration_ms >= 0

    @pytest.mark.asyncio
    async def test_failed_execution_recorded(self) -> None:
        """失败执行也应被记录到历史。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        await executor.execute("execute_skill", {
            "skill_name": "不存在",
            "params": {},
        })

        assert executor.history_count == 1
        history = await executor.get_execution_history()
        assert history[0].success is False

    @pytest.mark.asyncio
    async def test_history_order_newest_first(self) -> None:
        """历史记录应按时间倒序返回（最新在前）。"""
        skill_a = _make_skill(name="技能A", description="技能A描述")
        skill_b = _make_skill(name="技能B", description="技能B描述")
        registry = _make_registry_with_skills(skill_a, skill_b)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("技能A", lambda p: {"a": True})
        executor.register_executor("技能B", lambda p: {"b": True})

        await executor.execute("execute_skill", {"skill_name": "技能A", "params": {}})
        await executor.execute("execute_skill", {"skill_name": "技能B", "params": {}})

        history = await executor.get_execution_history()
        assert history[0].skill_name == "技能B"
        assert history[1].skill_name == "技能A"

    @pytest.mark.asyncio
    async def test_history_limit(self) -> None:
        """get_execution_history 应遵守 limit 参数。"""
        skill = _make_skill(name="限制测试", description="测试 limit")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("限制测试", lambda p: {"ok": True})

        for _ in range(5):
            await executor.execute("execute_skill", {
                "skill_name": "限制测试",
                "params": {},
            })

        assert executor.history_count == 5
        history = await executor.get_execution_history(limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_history_action(self) -> None:
        """通过 history action 查询历史。"""
        skill = _make_skill(name="历史查询", description="测试历史查询")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("历史查询", lambda p: {"ok": True})

        await executor.execute("execute_skill", {
            "skill_name": "历史查询",
            "params": {},
        })

        result = await executor.execute("history", {"limit": 10})
        assert result["success"] is True
        assert len(result["history"]) == 1
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# 测试：auto_execute 自动匹配
# ---------------------------------------------------------------------------


class TestAutoExecute:
    """测试自动匹配并执行技能。"""

    @pytest.mark.asyncio
    async def test_auto_execute_matches_skill(self) -> None:
        """根据任务描述自动匹配并执行最合适的技能。"""
        skill = _make_skill(
            name="截图",
            description="截取屏幕截图",
            tags=["截图", "屏幕", "screenshot"],
        )
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("截图", lambda p: {"path": "/tmp/shot.png"})

        result = await executor.execute("auto_execute", {
            "task_description": "截取屏幕",
        })

        assert result["success"] is True
        assert result["data"]["path"] == "/tmp/shot.png"
        assert "match" in result
        assert result["match"]["skill_name"] == "截图"

    @pytest.mark.asyncio
    async def test_auto_execute_no_match(self) -> None:
        """没有匹配的技能应返回失败。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        result = await executor.execute("auto_execute", {
            "task_description": "发射火箭",
        })

        assert result["success"] is False
        assert "未找到" in result["error"]

    @pytest.mark.asyncio
    async def test_auto_execute_missing_description(self) -> None:
        """缺少任务描述应返回失败。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        result = await executor.execute("auto_execute", {})

        assert result["success"] is False
        assert "缺少 task_description" in result["error"]

    @pytest.mark.asyncio
    async def test_auto_execute_picks_best_match(self) -> None:
        """有多个候选时应选择匹配度最高的。"""
        skill_a = _make_skill(name="截图保存", description="截取屏幕并保存", tags=["截图"])
        skill_b = _make_skill(name="截图编辑", description="截图后编辑图片", tags=["截图", "编辑"])
        skill_c = _make_skill(
            name="屏幕截图保存到桌面",
            description="截取屏幕截图并保存到桌面",
            tags=["截图", "保存", "桌面"],
        )
        registry = _make_registry_with_skills(skill_a, skill_b, skill_c)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("截图保存", lambda p: {"a": True})
        executor.register_executor("截图编辑", lambda p: {"b": True})
        executor.register_executor("屏幕截图保存到桌面", lambda p: {"c": True})

        result = await executor.execute("auto_execute", {
            "task_description": "屏幕截图保存到桌面",
        })

        assert result["success"] is True
        # skill_c 名称完全包含任务描述，应有最高分
        assert result["match"]["skill_name"] == "屏幕截图保存到桌面"


# ---------------------------------------------------------------------------
# 测试：技能推荐
# ---------------------------------------------------------------------------


class TestRecommendations:
    """测试技能推荐功能。"""

    @pytest.mark.asyncio
    async def test_recommend_returns_matches(self) -> None:
        """推荐应返回匹配的技能列表。"""
        skill = _make_skill(
            name="文件压缩",
            description="压缩文件为 zip 或 tar.gz",
            tags=["压缩", "zip"],
        )
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        result = await executor.execute("recommend", {
            "task_description": "压缩文件",
        })

        assert result["success"] is True
        assert len(result["recommendations"]) >= 1
        rec = result["recommendations"][0]
        assert rec["skill_name"] == "文件压缩"
        assert rec["relevance_score"] > 0.0

    @pytest.mark.asyncio
    async def test_recommend_with_history(self) -> None:
        """推荐应包含历史成功率信息。"""
        skill = _make_skill(name="计算器", description="执行数学计算", tags=["计算"])
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("计算器", lambda p: {"result": 42})

        # 执行几次以积累历史
        for _ in range(3):
            await executor.execute("execute_skill", {
                "skill_name": "计算器",
                "params": {},
            })

        recommendations = await executor.get_skill_recommendations("计算")
        assert len(recommendations) >= 1
        rec = recommendations[0]
        assert rec["historical_success_rate"] == 1.0
        assert rec["historical_executions"] == 3

    @pytest.mark.asyncio
    async def test_recommend_no_history(self) -> None:
        """没有历史执行记录时成功率应为 None。"""
        skill = _make_skill(name="新技能", description="一个新技能")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        recommendations = await executor.get_skill_recommendations("新技能")
        assert len(recommendations) >= 1
        assert recommendations[0]["historical_success_rate"] is None


# ---------------------------------------------------------------------------
# 测试：技能链执行
# ---------------------------------------------------------------------------


class TestSkillChain:
    """测试技能链执行。"""

    @pytest.mark.asyncio
    async def test_simple_chain(self) -> None:
        """简单的两步技能链应顺序执行。"""
        skill_a = _make_skill(name="步骤A", description="第一步")
        skill_b = _make_skill(name="步骤B", description="第二步")
        registry = _make_registry_with_skills(skill_a, skill_b)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("步骤A", lambda p: {"value": "a_result"})
        executor.register_executor("步骤B", lambda p: {"value": "b_result"})

        steps = [
            SkillChainStep(step_index=0, skill_name="步骤A", params={}, depends_on=[]),
            SkillChainStep(step_index=1, skill_name="步骤B", params={}, depends_on=[0]),
        ]

        result = await executor.execute_chain(steps)

        assert result.success is True
        assert len(result.step_results) == 2
        assert result.step_results[0]["success"] is True
        assert result.step_results[1]["success"] is True
        assert result.total_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_chain_stops_on_failure(self) -> None:
        """链中某步失败时应停止执行后续步骤。"""
        skill_a = _make_skill(name="成功步骤", description="会成功的")
        skill_b = _make_skill(name="失败步骤", description="会失败的")
        skill_c = _make_skill(name="不应执行", description="不应被执行")
        registry = _make_registry_with_skills(skill_a, skill_b, skill_c)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("成功步骤", lambda p: {"ok": True})
        executor.register_executor("失败步骤", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
        executor.register_executor("不应执行", lambda p: {"ok": True})

        steps = [
            SkillChainStep(step_index=0, skill_name="成功步骤", params={}, depends_on=[]),
            SkillChainStep(step_index=1, skill_name="失败步骤", params={}, depends_on=[0]),
            SkillChainStep(step_index=2, skill_name="不应执行", params={}, depends_on=[1]),
        ]

        result = await executor.execute_chain(steps)

        assert result.success is False
        assert "执行失败" in result.error
        assert len(result.step_results) == 2  # 只有前两步的结果

    @pytest.mark.asyncio
    async def test_chain_dependency_injection(self) -> None:
        """依赖步骤的结果应被注入到参数中。"""
        skill_a = _make_skill(name="数据源", description="提供数据")
        skill_b = _make_skill(name="消费者", description="消费数据")
        registry = _make_registry_with_skills(skill_a, skill_b)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("数据源", lambda p: {"items": [1, 2, 3]})

        received_params: dict = {}

        def consumer(params: dict) -> dict:
            received_params.update(params)
            return {"processed": True}

        executor.register_executor("消费者", consumer)

        steps = [
            SkillChainStep(step_index=0, skill_name="数据源", params={}, depends_on=[]),
            SkillChainStep(step_index=1, skill_name="消费者", params={}, depends_on=[0]),
        ]

        result = await executor.execute_chain(steps)

        assert result.success is True
        assert "$step_0" in received_params
        assert received_params["$step_0"]["items"] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_chain_unmet_dependency(self) -> None:
        """依赖未满足时应报告错误。"""
        skill_a = _make_skill(name="独立步骤", description="独立")
        registry = _make_registry_with_skills(skill_a)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("独立步骤", lambda p: {"ok": True})

        steps = [
            SkillChainStep(step_index=0, skill_name="独立步骤", params={}, depends_on=[]),
            # 步骤 1 依赖步骤 2（不存在），跳过了步骤 2
            SkillChainStep(step_index=1, skill_name="独立步骤", params={}, depends_on=[2]),
        ]

        result = await executor.execute_chain(steps)

        assert result.success is False
        assert "依赖未完成" in result.error


# ---------------------------------------------------------------------------
# 测试：执行结果反馈到 SkillLearner
# ---------------------------------------------------------------------------


class TestLearnerFeedback:
    """测试执行结果反馈到 SkillLearner。"""

    @pytest.mark.asyncio
    async def test_successful_execution_feedback(self) -> None:
        """成功执行应反馈到学习器。"""
        skill = _make_skill(name="反馈测试", description="测试学习反馈")
        registry = _make_registry_with_skills(skill)
        mock_learner = AsyncMock()
        executor = SkillExecutor(skill_registry=registry, skill_learner=mock_learner)

        executor.register_executor("反馈测试", lambda p: {"ok": True})

        await executor.execute("execute_skill", {
            "skill_name": "反馈测试",
            "params": {},
        })

        # 学习器的 record_execution 应被调用
        mock_learner.record_execution.assert_called_once()
        call_args = mock_learner.record_execution.call_args
        plan = call_args[0][0]
        exec_result = call_args[0][1]

        assert plan.intent == "执行技能: 反馈测试"
        assert exec_result.success is True
        assert exec_result.completed_steps == 1

    @pytest.mark.asyncio
    async def test_failed_execution_feedback(self) -> None:
        """失败执行也应反馈到学习器。"""
        registry = _make_registry_with_skills()
        mock_learner = AsyncMock()
        executor = SkillExecutor(skill_registry=registry, skill_learner=mock_learner)

        await executor.execute("execute_skill", {
            "skill_name": "不存在",
            "params": {},
        })

        mock_learner.record_execution.assert_called_once()
        call_args = mock_learner.record_execution.call_args
        exec_result = call_args[0][1]
        assert exec_result.success is False

    @pytest.mark.asyncio
    async def test_no_learner_no_error(self) -> None:
        """没有学习器时不应报错。"""
        skill = _make_skill(name="无学习器", description="没有学习器")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("无学习器", lambda p: {"ok": True})

        result = await executor.execute("execute_skill", {
            "skill_name": "无学习器",
            "params": {},
        })

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_learner_exception_does_not_break(self) -> None:
        """学习器抛异常时不应影响执行结果。"""
        skill = _make_skill(name="学习器异常", description="测试异常")
        registry = _make_registry_with_skills(skill)
        mock_learner = AsyncMock()
        mock_learner.record_execution.side_effect = RuntimeError("学习器崩了")
        executor = SkillExecutor(skill_registry=registry, skill_learner=mock_learner)

        executor.register_executor("学习器异常", lambda p: {"ok": True})

        result = await executor.execute("execute_skill", {
            "skill_name": "学习器异常",
            "params": {},
        })

        # 执行仍然成功
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 测试：执行超时
# ---------------------------------------------------------------------------


class TestExecutionTimeout:
    """测试执行超时处理。"""

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self) -> None:
        """执行超时应返回失败。"""
        skill = _make_skill(name="超时技能", description="会超时的技能")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry, execution_timeout=0.1)

        async def slow_fn(params: dict) -> dict:
            await asyncio.sleep(10)
            return {"ok": True}

        executor.register_executor("超时技能", slow_fn)

        result = await executor.execute("execute_skill", {
            "skill_name": "超时技能",
            "params": {},
        })

        assert result["success"] is False
        assert "超时" in result["error"]


# ---------------------------------------------------------------------------
# 测试：action 分发
# ---------------------------------------------------------------------------


class TestActionDispatch:
    """测试 action 分发逻辑。"""

    @pytest.mark.asyncio
    async def test_unsupported_action(self) -> None:
        """不支持的 action 应抛出 ValueError。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        with pytest.raises(ValueError, match="不支持的 action"):
            await executor.execute("unknown_action", {})

    @pytest.mark.asyncio
    async def test_all_supported_actions(self) -> None:
        """所有支持的 action 都应能正常分发。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        # execute_skill
        result = await executor.execute("execute_skill", {"skill_name": "test"})
        assert isinstance(result, dict)

        # auto_execute
        result = await executor.execute("auto_execute", {"task_description": "test"})
        assert isinstance(result, dict)

        # recommend
        result = await executor.execute("recommend", {"task_description": "test"})
        assert isinstance(result, dict)

        # history
        result = await executor.execute("history", {})
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 测试：统计信息
# ---------------------------------------------------------------------------


class TestStats:
    """测试统计信息接口。"""

    @pytest.mark.asyncio
    async def test_empty_stats(self) -> None:
        """没有执行记录时统计应为零。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        stats = executor.get_stats()
        assert stats["total_executions"] == 0
        assert stats["success_count"] == 0
        assert stats["failure_count"] == 0
        assert stats["success_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_stats_after_executions(self) -> None:
        """执行后统计应正确更新。"""
        skill = _make_skill(name="统计测试", description="测试统计")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("统计测试", lambda p: {"ok": True})

        await executor.execute("execute_skill", {"skill_name": "统计测试", "params": {}})
        await executor.execute("execute_skill", {"skill_name": "统计测试", "params": {}})
        await executor.execute("execute_skill", {"skill_name": "不存在", "params": {}})

        stats = executor.get_stats()
        assert stats["total_executions"] == 3
        assert stats["success_count"] == 2
        assert stats["failure_count"] == 1
        assert stats["success_rate"] == pytest.approx(2 / 3, abs=0.01)

    def test_registered_executor_count(self) -> None:
        """registered_executor_count 应返回已注册数量。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        assert executor.registered_executor_count == 0

        executor.register_executor("a", lambda p: {})
        executor.register_executor("b", lambda p: {})

        assert executor.registered_executor_count == 2


# ---------------------------------------------------------------------------
# 测试：执行函数注册/注销
# ---------------------------------------------------------------------------


class TestExecutorRegistration:
    """测试执行函数的注册和注销。"""

    def test_register_and_unregister(self) -> None:
        """注册后可以注销。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        executor.register_executor("test", lambda p: {})
        assert executor.registered_executor_count == 1

        result = executor.unregister_executor("test")
        assert result is True
        assert executor.registered_executor_count == 0

    def test_unregister_nonexistent(self) -> None:
        """注销不存在的执行函数应返回 False。"""
        registry = _make_registry_with_skills()
        executor = SkillExecutor(skill_registry=registry)

        result = executor.unregister_executor("不存在")
        assert result is False


# ---------------------------------------------------------------------------
# 测试：异常处理
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    """测试执行中的异常处理。"""

    @pytest.mark.asyncio
    async def test_executor_raises_exception(self) -> None:
        """执行函数抛异常应返回失败并记录错误。"""
        skill = _make_skill(name="异常技能", description="会抛异常")
        registry = _make_registry_with_skills(skill)
        executor = SkillExecutor(skill_registry=registry)

        def raise_fn(params: dict) -> dict:
            raise ValueError("test error")

        executor.register_executor("异常技能", raise_fn)

        result = await executor.execute("execute_skill", {
            "skill_name": "异常技能",
            "params": {},
        })

        assert result["success"] is False
        assert "执行异常" in result["error"]
        assert "test error" in result["error"]

        # 应记录到历史
        assert executor.history_count == 1
        history = await executor.get_execution_history()
        assert history[0].success is False
        assert "test error" in history[0].error
