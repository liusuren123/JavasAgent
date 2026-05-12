# -*- coding: utf-8 -*-
"""集成测试 — YAML 技能完整流程。

测试：YAML → SkillLoader → SkillDefinition → StepExecutor → 结果
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.skills.context import SkillContext
from src.skills.skill_loader import SkillLoader
from src.skills.step_executor import StepExecutor
from src.skills.validator import SkillValidator
from src.skills.expression import ExpressionEvaluator


# ======================================================================
# 测试用 YAML 技能文件
# ======================================================================

YAML_SIMPLE = """
name: "简单测试"
description: "只做等待的简单技能"
steps:
  - action: wait
    duration: 0.01
"""

YAML_WITH_PARAMS = """
name: "带参数测试"
description: "使用参数的技能"
parameters:
  shortcut:
    type: string
    default: "ctrl+s"
steps:
  - action: key_combo
    keys: "{{parameters.shortcut}}"
"""

YAML_WITH_CONDITION = """
name: "条件测试"
description: "带条件分支的技能"
parameters:
  mode:
    type: string
    default: ""
steps:
  - action: condition
    when: 'parameters.mode == "fast"'
    then:
      - action: wait
        duration: 0.01
"""

YAML_WITH_LOOP = """
name: "循环测试"
description: "循环执行步骤"
steps:
  - action: loop
    max_iterations: 3
    steps:
      - action: wait
        duration: 0.01
"""


# ======================================================================
# Mock action 注册
# ======================================================================

async def _mock_wait(step, context, platform=None, perception=None,
                     humanhand=None, executor=None, skill_executor=None):
    return {"success": True, "duration": step.get("duration", 1.0)}

async def _mock_key_combo(step, context, platform=None, perception=None,
                          humanhand=None, executor=None, skill_executor=None):
    return {"success": True, "keys": step.get("keys", "")}

async def _mock_condition(step, context, platform=None, perception=None,
                          humanhand=None, executor=None, skill_executor=None):
    from src.skills.expression import ExpressionEvaluator
    when_expr = step.get("when", "")
    evaluator = ExpressionEvaluator()
    result = evaluator.evaluate(when_expr, context)
    steps_to_run = step.get("then", []) if result else step.get("else", [])
    if steps_to_run and executor:
        exec_result = await executor.execute_steps(steps_to_run, context)
        return {"success": exec_result.get("success", True), "branch": "then" if result else "else"}
    return {"success": True, "branch": "then" if result else "else", "executed": 0}

async def _mock_loop(step, context, platform=None, perception=None,
                     humanhand=None, executor=None, skill_executor=None):
    from src.skills.expression import ExpressionEvaluator
    steps = step.get("steps", [])
    max_iter = min(int(step.get("max_iterations", 10)), 100)
    break_when = step.get("break_when")
    evaluator = ExpressionEvaluator()
    if not steps:
        return {"success": True, "iterations": 0}
    if not executor:
        return {"success": False, "error": "executor 未提供"}
    actual_iterations = 0
    for i in range(max_iter):
        actual_iterations = i + 1
        if break_when and evaluator.evaluate(break_when, context):
            break
        exec_result = await executor.execute_steps(steps, context)
        if not exec_result.get("success", True):
            return {"success": False, "iterations": actual_iterations}
    return {"success": True, "iterations": actual_iterations}


@pytest.fixture(autouse=True)
def patch_registry(monkeypatch):
    """替换 ACTION_REGISTRY 为 mock 版本。"""
    from src.skills import actions
    mock_registry = {
        "wait": _mock_wait,
        "key_combo": _mock_key_combo,
        "condition": _mock_condition,
        "loop": _mock_loop,
    }
    monkeypatch.setattr(actions, "ACTION_REGISTRY", mock_registry)
    monkeypatch.setattr(actions, "get_action_registry", lambda: mock_registry)


# ======================================================================
# 测试
# ======================================================================

class TestSimpleYAMLExecution:
    @pytest.mark.asyncio
    async def test_simple_yaml_loads_and_executes(self, tmp_path):
        """测试：YAML → SkillLoader → StepExecutor"""
        # 1. 写入 YAML 文件
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "simple.yaml").write_text(YAML_SIMPLE, encoding="utf-8")

        # 2. SkillLoader 加载
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills = loader.load_all()
        assert len(skills) == 1
        assert skills[0].name == "简单测试"

        # 3. StepExecutor 执行
        executor = StepExecutor()
        ctx = SkillContext(parameters={})
        result = await executor.execute_steps(skills[0].steps, ctx)
        assert result["success"] is True
        assert result["completed_steps"] == 1


class TestYAMLWithParameters:
    @pytest.mark.asyncio
    async def test_yaml_with_template_params(self, tmp_path):
        """测试模板变量替换"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "params.yaml").write_text(YAML_WITH_PARAMS, encoding="utf-8")

        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills = loader.load_all()
        assert len(skills) == 1

        executor = StepExecutor()
        ctx = SkillContext(parameters={"shortcut": "alt+f4"})
        result = await executor.execute_steps(skills[0].steps, ctx)
        assert result["success"] is True


class TestYAMLWithCondition:
    @pytest.mark.asyncio
    async def test_yaml_condition_true(self, tmp_path):
        """测试条件分支 — when=true"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "cond.yaml").write_text(YAML_WITH_CONDITION, encoding="utf-8")

        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills = loader.load_all()

        executor = StepExecutor()
        ctx = SkillContext(parameters={"mode": "fast"})
        result = await executor.execute_steps(skills[0].steps, ctx)
        assert result["success"] is True


class TestYAMLWithLoop:
    @pytest.mark.asyncio
    async def test_yaml_loop_iterations(self, tmp_path):
        """测试循环执行"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "loop.yaml").write_text(YAML_WITH_LOOP, encoding="utf-8")

        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills = loader.load_all()

        executor = StepExecutor()
        ctx = SkillContext()
        result = await executor.execute_steps(skills[0].steps, ctx)
        assert result["success"] is True


class TestYAMLAndPythonCoexistence:
    @pytest.mark.asyncio
    async def test_yaml_skill_has_source_yaml(self, tmp_path):
        """YAML 技能和 Python 函数技能可以共存"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "simple.yaml").write_text(YAML_SIMPLE, encoding="utf-8")

        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        yaml_skills = loader.load_all()

        # YAML 技能有 yaml_path
        assert yaml_skills[0].source == "yaml"
        assert yaml_skills[0].yaml_path != ""

        # Python 函数技能不会有 yaml_path（模拟）
        from src.memory.skill_models import SkillDefinition
        python_skill = SkillDefinition.create(
            name="Python技能",
            description="Python注册函数",
            category="tool",
            source="manual",
        )
        assert python_skill.yaml_path == ""
        assert python_skill.source == "manual"


class TestErrorPropagation:
    @pytest.mark.asyncio
    async def test_step_failure_propagates(self, tmp_path, monkeypatch):
        """步骤失败时整体返回失败"""
        yaml_content = """
name: "失败测试"
description: "第二步失败"
steps:
  - action: wait
    duration: 0.01
  - action: fail_action
"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "fail.yaml").write_text(yaml_content, encoding="utf-8")

        # 注册一个必定失败的 action
        async def _mock_fail(step, context, platform=None, perception=None,
                             humanhand=None, executor=None, skill_executor=None):
            return {"success": False, "error": "模拟失败"}

        from src.skills import actions
        from src.skills.validator import VALID_ACTIONS
        # 先 patch VALID_ACTIONS 包含 fail_action
        valid_with_fail = VALID_ACTIONS | {"fail_action"}
        monkeypatch.setattr("src.skills.validator.VALID_ACTIONS", valid_with_fail)

        registry = dict(actions.get_action_registry())
        registry["fail_action"] = _mock_fail
        monkeypatch.setattr(actions, "ACTION_REGISTRY", registry)
        monkeypatch.setattr(actions, "get_action_registry", lambda: registry)

        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills = loader.load_all()

        executor = StepExecutor()
        ctx = SkillContext()
        result = await executor.execute_steps(skills[0].steps, ctx)
        assert result["success"] is False
        assert result["failed_step"] is not None
