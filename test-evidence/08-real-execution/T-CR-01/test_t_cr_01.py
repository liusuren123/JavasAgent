"""T-CR-01: Planner 生成计划 — 实操测试。

Mock LLMClient，验证 planner.plan() 返回 TaskPlan 结构。
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# 确保 src 在路径中
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from src.core.models import Priority, Step, TaskPlan
from src.core.planner import Planner


FAKE_LLM_JSON = json.dumps({
    "intent_summary": "写一个Python脚本",
    "steps": [
        {
            "action": "创建Python脚本文件",
            "tool": "code_dev",
            "params": {"language": "python", "task": "写脚本"},
            "depends_on": [],
        },
        {
            "action": "运行脚本验证",
            "tool": "shell",
            "params": {"command": "python script.py"},
            "depends_on": [0],
        },
    ],
    "priority": 10,
    "need_clarification": False,
})


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.chat_with_system = AsyncMock(return_value=FAKE_LLM_JSON)
    return llm


@pytest.fixture
def planner(mock_llm):
    return Planner(llm=mock_llm)


@pytest.mark.asyncio
async def test_plan_returns_taskplan(planner, mock_llm):
    """plan() 应返回 TaskPlan 实例。"""
    result = await planner.plan("帮我写个脚本")
    assert isinstance(result, TaskPlan), f"预期 TaskPlan，实际 {type(result)}"
    print(f"[OK] 返回类型: TaskPlan (id={result.id})")


@pytest.mark.asyncio
async def test_plan_intent(planner):
    """plan() 的 intent 应来自 LLM 返回的 intent_summary。"""
    result = await planner.plan("帮我写个脚本")
    assert result.intent == "写一个Python脚本", f"intent 不匹配: {result.intent}"
    print(f"[OK] intent: {result.intent}")


@pytest.mark.asyncio
async def test_plan_steps_count(planner):
    """plan() 应正确解析步骤数量。"""
    result = await planner.plan("帮我写个脚本")
    assert len(result.steps) == 2, f"预期 2 个步骤，实际 {len(result.steps)}"
    print(f"[OK] 步骤数: {len(result.steps)}")


@pytest.mark.asyncio
async def test_plan_step_fields(planner):
    """每个 Step 的字段应正确。"""
    result = await planner.plan("帮我写个脚本")
    step0 = result.steps[0]
    assert isinstance(step0, Step)
    assert step0.action == "创建Python脚本文件"
    assert step0.tool == "code_dev"
    assert step0.params == {"language": "python", "task": "写脚本"}
    assert step0.id == "step_0"
    print(f"[OK] step_0: action={step0.action}, tool={step0.tool}")

    step1 = result.steps[1]
    assert step1.depends_on == ["step_0"]
    print(f"[OK] step_1: depends_on={step1.depends_on}")


@pytest.mark.asyncio
async def test_plan_priority(planner):
    """priority 应正确解析为 Priority 枚举。"""
    result = await planner.plan("帮我写个脚本")
    assert result.priority == Priority.HIGH, f"预期 Priority.HIGH(10)，实际 {result.priority}"
    print(f"[OK] priority: {result.priority} (value={result.priority.value})")


@pytest.mark.asyncio
async def test_plan_with_registered_tools(planner, mock_llm):
    """注册工具后，系统提示应包含注册的工具。"""
    planner.register_tool("custom_tool", "自定义工具描述")
    await planner.plan("测试")
    # 验证 LLM 被调用
    assert mock_llm.chat_with_system.called
    call_args = mock_llm.chat_with_system.call_args
    system_prompt = call_args.kwargs.get("system_prompt", call_args[1].get("system_prompt", ""))
    assert "custom_tool" in system_prompt, "注册的工具应出现在系统提示中"
    print(f"[OK] 注册工具出现在系统提示中")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
