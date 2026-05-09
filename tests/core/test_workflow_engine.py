"""工作流引擎测试。"""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.workflow_engine import (
    FailureStrategy,
    WorkflowDefinition,
    WorkflowEngine,
    WorkflowResult,
    WorkflowStatus,
    WorkflowStep,
    render_template,
)


# ---------------------------------------------------------------------------
# 辅助工厂
# ---------------------------------------------------------------------------


def _make_step(
    step_id: str = "s0",
    tool_name: str = "mock_tool",
    action: str = "测试动作",
    params: dict | None = None,
    condition: str | None = None,
    on_failure: FailureStrategy = FailureStrategy.ABORT,
) -> WorkflowStep:
    return WorkflowStep(
        step_id=step_id,
        tool_name=tool_name,
        action=action,
        params=params or {},
        condition=condition,
        on_failure=on_failure,
    )


def _make_tool(return_value: str = "ok") -> MagicMock:
    """创建 mock 工具。"""
    tool = MagicMock()
    tool.execute = AsyncMock(return_value=return_value)
    return tool


def _make_failing_tool() -> MagicMock:
    """创建始终失败的 mock 工具。"""
    tool = MagicMock()
    tool.execute = AsyncMock(side_effect=RuntimeError("工具执行错误"))
    return tool


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


class TestWorkflowDefinition:
    """工作流定义测试。"""

    def test_define_workflow_returns_id(self, tmp_path: Path) -> None:
        """定义工作流应返回有效 ID。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        wf_id = engine.define_workflow("测试工作流", "描述", [
            {"step_id": "s1", "tool_name": "t", "action": "a"},
        ])
        assert wf_id.startswith("wf_")
        assert engine.get_workflow(wf_id) is not None

    def test_list_workflows(self, tmp_path: Path) -> None:
        """列出已定义的工作流。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.define_workflow("wf1", "desc1")
        engine.define_workflow("wf2", "desc2")
        wfs = engine.list_workflows()
        assert len(wfs) == 2
        names = {w.name for w in wfs}
        assert names == {"wf1", "wf2"}

    def test_delete_workflow(self, tmp_path: Path) -> None:
        """删除工作流。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        wf_id = engine.define_workflow("to_delete", "desc")
        assert engine.delete_workflow(wf_id) is True
        assert engine.get_workflow(wf_id) is None
        assert engine.delete_workflow("nonexistent") is False


class TestWorkflowExecution:
    """工作流执行测试。"""

    def test_execute_single_step(self, tmp_path: Path) -> None:
        """单步骤工作流执行。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("mock_tool", _make_tool("result_ok"))

        wf_id = engine.define_workflow("单步测试", steps=[
            {"step_id": "s1", "tool_name": "mock_tool", "action": "do_something"},
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id)
        )
        assert result.status == WorkflowStatus.SUCCESS
        assert len(result.step_results) == 1
        assert result.step_results[0].success is True
        assert result.step_results[0].output == "result_ok"

    def test_execute_multiple_steps(self, tmp_path: Path) -> None:
        """多步骤顺序执行。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("t", _make_tool())

        wf_id = engine.define_workflow("多步测试", steps=[
            {"step_id": "s1", "tool_name": "t", "action": "a1"},
            {"step_id": "s2", "tool_name": "t", "action": "a2"},
            {"step_id": "s3", "tool_name": "t", "action": "a3"},
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id)
        )
        assert result.status == WorkflowStatus.SUCCESS
        assert len(result.step_results) == 3
        assert all(r.success for r in result.step_results)

    def test_execute_nonexistent_workflow(self, tmp_path: Path) -> None:
        """执行不存在的工作流应返回 FAILED。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow("wf_nonexistent")
        )
        assert result.status == WorkflowStatus.FAILED
        assert "不存在" in result.error_summary


class TestTemplateRendering:
    """模板变量替换测试。"""

    def test_render_string_template(self) -> None:
        """字符串模板替换。"""
        result = render_template("hello {{name}}", {"name": "world"})
        assert result == "hello world"

    def test_render_nested_dict(self) -> None:
        """嵌套字典中的模板替换。"""
        tpl = {"key": "{{val}}", "nested": {"inner": "{{val2}}"}}
        result = render_template(tpl, {"val": "a", "val2": "b"})
        assert result == {"key": "a", "nested": {"inner": "b"}}

    def test_render_list_template(self) -> None:
        """列表中的模板替换。"""
        tpl = ["{{x}}", "{{y}}"]
        result = render_template(tpl, {"x": "1", "y": "2"})
        assert result == ["1", "2"]

    def test_render_in_workflow_execution(self, tmp_path: Path) -> None:
        """工作流执行时模板变量替换。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("t", _make_tool("ok"))

        wf_id = engine.define_workflow("模板测试", steps=[
            {
                "step_id": "s1",
                "tool_name": "t",
                "action": "process {{filename}}",
                "params": {"path": "/data/{{filename}}"},
            },
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id, {"filename": "report.csv"})
        )
        assert result.status == WorkflowStatus.SUCCESS
        # 验证工具被调用时使用了替换后的参数
        call_args = engine._tool_registry["t"].execute.call_args
        assert call_args[0][0] == "process report.csv"
        assert call_args[0][1]["path"] == "/data/report.csv"


class TestConditionAndFailure:
    """条件执行和失败处理测试。"""

    def test_condition_skip(self, tmp_path: Path) -> None:
        """条件不满足时步骤应跳过。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("t", _make_tool())

        wf_id = engine.define_workflow("条件测试", steps=[
            {"step_id": "s1", "tool_name": "t", "action": "a", "condition": "skip_me"},
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id, {"skip_me": False})
        )
        # 条件为 False → 跳过 → 状态 PARTIAL
        assert result.status == WorkflowStatus.PARTIAL
        assert result.step_results[0].skipped is True

    def test_condition_equals(self, tmp_path: Path) -> None:
        """条件相等判断。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("t", _make_tool())

        wf_id = engine.define_workflow("等值条件", steps=[
            {"step_id": "s1", "tool_name": "t", "action": "a", "condition": "mode==fast"},
        ])
        # mode==fast → 条件满足
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id, {"mode": "fast"})
        )
        assert result.step_results[0].success is True
        assert result.step_results[0].skipped is False

    def test_condition_not_equals(self, tmp_path: Path) -> None:
        """条件不等判断。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("t", _make_tool())

        wf_id = engine.define_workflow("不等条件", steps=[
            {"step_id": "s1", "tool_name": "t", "action": "a", "condition": "env!=prod"},
        ])
        # env!=prod 且 env=dev → 条件满足
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id, {"env": "dev"})
        )
        assert result.step_results[0].success is True

    def test_failure_abort(self, tmp_path: Path) -> None:
        """失败策略 ABORT：终止后续步骤。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("fail", _make_failing_tool())
        engine.register_tool("ok", _make_tool())

        wf_id = engine.define_workflow("abort测试", steps=[
            {"step_id": "s1", "tool_name": "fail", "action": "a",
             "on_failure": "abort"},
            {"step_id": "s2", "tool_name": "ok", "action": "a2"},
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id)
        )
        assert result.status == WorkflowStatus.FAILED
        assert result.step_results[0].success is False
        assert result.step_results[1].skipped is True  # 被跳过

    def test_failure_skip(self, tmp_path: Path) -> None:
        """失败策略 SKIP：跳过并继续。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("fail", _make_failing_tool())
        engine.register_tool("ok", _make_tool())

        wf_id = engine.define_workflow("skip测试", steps=[
            {"step_id": "s1", "tool_name": "fail", "action": "a",
             "on_failure": "skip"},
            {"step_id": "s2", "tool_name": "ok", "action": "a2"},
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id)
        )
        # s1 失败但 skip，s2 成功
        assert result.step_results[0].skipped is True
        assert result.step_results[1].success is True
        assert result.status == WorkflowStatus.PARTIAL

    def test_failure_retry(self, tmp_path: Path) -> None:
        """失败策略 RETRY：重试后成功。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        tool = MagicMock()
        tool.execute = AsyncMock(side_effect=[RuntimeError("err"), "ok"])
        engine.register_tool("retry_tool", tool)

        wf_id = engine.define_workflow("retry测试", steps=[
            {"step_id": "s1", "tool_name": "retry_tool", "action": "a",
             "on_failure": "retry"},
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id)
        )
        assert result.step_results[0].success is True
        assert result.step_results[0].retried == 1
        assert tool.execute.call_count == 2


class TestPersistence:
    """持久化测试。"""

    def test_save_and_load(self, tmp_path: Path) -> None:
        """工作流应持久化到磁盘并能在新引擎实例中加载。"""
        storage = tmp_path / "wf"

        # 定义并保存
        engine1 = WorkflowEngine(storage_dir=storage)
        wf_id = engine1.define_workflow("持久化测试", "描述", [
            {"step_id": "s1", "tool_name": "t", "action": "a"},
        ])

        # 新实例加载
        engine2 = WorkflowEngine(storage_dir=storage)
        wf = engine2.get_workflow(wf_id)
        assert wf is not None
        assert wf.name == "持久化测试"
        assert len(wf.steps) == 1

    def test_delete_removes_file(self, tmp_path: Path) -> None:
        """删除工作流应同时删除文件。"""
        storage = tmp_path / "wf"
        engine = WorkflowEngine(storage_dir=storage)
        wf_id = engine.define_workflow("待删除", "desc")
        assert (storage / f"{wf_id}.json").exists()
        engine.delete_workflow(wf_id)
        assert not (storage / f"{wf_id}.json").exists()


class TestImportExport:
    """导入导出测试。"""

    def test_export_and_import(self, tmp_path: Path) -> None:
        """导出 JSON 后再导入应得到等效工作流。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        original_id = engine.define_workflow("导出测试", "描述", [
            {"step_id": "s1", "tool_name": "t", "action": "a",
             "params": {"key": "val"}},
        ])

        json_str = engine.export_workflow(original_id)
        data = json.loads(json_str)
        assert data["name"] == "导出测试"
        assert len(data["steps"]) == 1

        # 导入会得到新 ID
        new_id = engine.import_workflow(json_str)
        assert new_id != original_id
        wf = engine.get_workflow(new_id)
        assert wf is not None
        assert wf.name == "导出测试"
        assert len(wf.steps) == 1

    def test_export_nonexistent_raises(self, tmp_path: Path) -> None:
        """导出不存在的工作流应抛 KeyError。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        with pytest.raises(KeyError):
            engine.export_workflow("wf_nonexistent")


class TestRunWorkflowByName:
    """按名称执行工作流测试。"""

    def test_run_by_name(self, tmp_path: Path) -> None:
        """通过名称查找并执行工作流。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        engine.register_tool("t", _make_tool())
        engine.define_workflow("我的工作流", steps=[
            {"step_id": "s1", "tool_name": "t", "action": "a"},
        ])

        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow("我的工作流")
        )
        assert result.status == WorkflowStatus.SUCCESS

    def test_run_nonexistent_name(self, tmp_path: Path) -> None:
        """执行不存在的工作流名称应返回 FAILED。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")
        result = asyncio.get_event_loop().run_until_complete(
            engine.run_workflow("不存在的名称")
        )
        assert result.status == WorkflowStatus.FAILED


class TestStepResultInContext:
    """步骤结果传递到上下文测试。"""

    def test_step_output_available_in_later_steps(self, tmp_path: Path) -> None:
        """前一步的输出应可通过 {{_step_xxx}} 在后续步骤中引用。"""
        engine = WorkflowEngine(storage_dir=tmp_path / "wf")

        # 第一步返回特定值，第二步用该值作为参数
        engine.register_tool("t1", _make_tool("hello_world"))
        engine.register_tool("t2", _make_tool("done"))

        wf_id = engine.define_workflow("结果传递", steps=[
            {"step_id": "s1", "tool_name": "t1", "action": "generate"},
            {"step_id": "s2", "tool_name": "t2", "action": "use {{_step_s1}}",
             "params": {"input": "{{_step_s1}}"}},
        ])
        result = asyncio.get_event_loop().run_until_complete(
            engine.execute_workflow(wf_id)
        )
        assert result.status == WorkflowStatus.SUCCESS
        # 验证 t2 被调用时参数已替换
        call_args = engine._tool_registry["t2"].execute.call_args
        assert "hello_world" in call_args[0][0]
        assert call_args[0][1]["input"] == "hello_world"
