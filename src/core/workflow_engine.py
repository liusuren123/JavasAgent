"""任务工作流引擎。

将多步骤任务定义为可复用工作流，支持模板变量、条件执行和失败处理。
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


class FailureStrategy(str, Enum):
    """步骤失败处理策略。"""

    ABORT = "abort"  # 终止整个工作流
    SKIP = "skip"    # 跳过当前步骤，继续后续
    RETRY = "retry"  # 重试当前步骤（最多 3 次）


class WorkflowStatus(str, Enum):
    """工作流执行状态。"""

    SUCCESS = "success"  # 全部步骤成功
    PARTIAL = "partial"  # 部分步骤跳过
    FAILED = "failed"    # 有关键步骤失败


@dataclass
class WorkflowStep:
    """工作流中的单个步骤定义。"""

    step_id: str
    tool_name: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    condition: str | None = None       # 前置条件表达式，为 None 或空串表示无条件
    on_failure: FailureStrategy = FailureStrategy.ABORT

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "action": self.action,
            "params": self.params,
            "condition": self.condition,
            "on_failure": self.on_failure.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowStep:
        """从字典反序列化。"""
        return cls(
            step_id=data["step_id"],
            tool_name=data["tool_name"],
            action=data["action"],
            params=data.get("params", {}),
            condition=data.get("condition"),
            on_failure=FailureStrategy(data.get("on_failure", "abort")),
        )


@dataclass
class WorkflowDefinition:
    """工作流定义。"""

    id: str
    name: str
    description: str
    steps: list[WorkflowStep] = field(default_factory=list)
    trigger: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "trigger": self.trigger,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowDefinition:
        """从字典反序列化。"""
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            steps=[WorkflowStep.from_dict(s) for s in data.get("steps", [])],
            trigger=data.get("trigger"),
        )


@dataclass
class StepResult:
    """单个步骤的执行结果。"""

    step_id: str
    success: bool
    output: Any = None
    error: str | None = None
    skipped: bool = False
    retried: int = 0


@dataclass
class WorkflowResult:
    """工作流执行结果。"""

    workflow_id: str
    status: WorkflowStatus
    step_results: list[StepResult] = field(default_factory=list)
    total_time: float = 0.0
    error_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典。"""
        return {
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "step_results": [
                {
                    "step_id": r.step_id,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                    "skipped": r.skipped,
                    "retried": r.retried,
                }
                for r in self.step_results
            ],
            "total_time": self.total_time,
            "error_summary": self.error_summary,
        }


# ---------------------------------------------------------------------------
# 模板变量渲染
# ---------------------------------------------------------------------------

_TEMPLATE_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def render_template(value: Any, context: dict[str, Any]) -> Any:
    """递归渲染模板变量 {{variable}}。

    对字符串做变量替换；对字典/列表递归处理；其他类型原样返回。
    """
    if isinstance(value, str):
        return _TEMPLATE_PATTERN.sub(
            lambda m: str(context.get(m.group(1), m.group(0))),
            value,
        )
    if isinstance(value, dict):
        return {k: render_template(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template(v, context) for v in value]
    return value


# ---------------------------------------------------------------------------
# 工作流引擎
# ---------------------------------------------------------------------------

_MAX_RETRIES = 3


class WorkflowEngine:
    """任务工作流引擎。

    管理工作流定义的增删查改，执行工作流并将结果返回。
    工作流定义持久化到 ``data/workflows/`` 目录。
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        if storage_dir is None:
            storage_dir = Path("data/workflows")
        self._storage: Path = Path(storage_dir)
        self._workflows: dict[str, WorkflowDefinition] = {}
        self._tool_registry: dict[str, Any] = {}
        self._load_all()

    # -- 工具注册 --

    def register_tool(self, name: str, tool: Any) -> None:
        """注册工具实例供工作流步骤调用。"""
        self._tool_registry[name] = tool
        logger.debug(f"WorkflowEngine: 注册工具 {name}")

    # -- 工作流 CRUD --

    def define_workflow(
        self,
        name: str,
        description: str = "",
        steps: list[dict[str, Any]] | list[WorkflowStep] | None = None,
    ) -> str:
        """定义一个新工作流并持久化。

        Args:
            name: 工作流名称
            description: 描述
            steps: 步骤列表（字典或 WorkflowStep 实例均可）

        Returns:
            新工作流的 ID
        """
        wf_id = f"wf_{uuid.uuid4().hex[:12]}"
        parsed_steps: list[WorkflowStep] = []
        if steps:
            for s in steps:
                if isinstance(s, WorkflowStep):
                    parsed_steps.append(s)
                elif isinstance(s, dict):
                    parsed_steps.append(WorkflowStep.from_dict(s))
                else:
                    raise TypeError(f"不支持的步骤类型: {type(s)}")

        wf = WorkflowDefinition(
            id=wf_id,
            name=name,
            description=description,
            steps=parsed_steps,
        )
        self._workflows[wf_id] = wf
        self._save(wf)
        logger.info(f"定义工作流: {wf_id} ({name}), {len(parsed_steps)} 步")
        return wf_id

    def list_workflows(self) -> list[WorkflowDefinition]:
        """列出所有已定义的工作流。"""
        return list(self._workflows.values())

    def get_workflow(self, workflow_id: str) -> WorkflowDefinition | None:
        """按 ID 获取工作流定义。"""
        return self._workflows.get(workflow_id)

    def delete_workflow(self, workflow_id: str) -> bool:
        """删除工作流定义（同时删除持久化文件）。"""
        wf = self._workflows.pop(workflow_id, None)
        if wf is None:
            return False
        self._delete_file(wf)
        logger.info(f"已删除工作流: {workflow_id}")
        return True

    # -- 导入 / 导出 --

    def export_workflow(self, workflow_id: str) -> str:
        """将工作流导出为 JSON 字符串。"""
        wf = self._workflows.get(workflow_id)
        if wf is None:
            raise KeyError(f"工作流不存在: {workflow_id}")
        return json.dumps(wf.to_dict(), ensure_ascii=False, indent=2)

    def import_workflow(self, json_str: str) -> str:
        """从 JSON 字符串导入工作流。

        Returns:
            导入后的工作流 ID
        """
        data = json.loads(json_str)
        wf = WorkflowDefinition.from_dict(data)
        # 确保 ID 唯一
        wf.id = f"wf_{uuid.uuid4().hex[:12]}"
        self._workflows[wf.id] = wf
        self._save(wf)
        logger.info(f"导入工作流: {wf.id} ({wf.name})")
        return wf.id

    # -- 执行 --

    async def execute_workflow(
        self,
        workflow_id: str,
        context: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """执行工作流。

        Args:
            workflow_id: 工作流 ID
            context: 模板变量上下文

        Returns:
            WorkflowResult 执行结果
        """
        wf = self._workflows.get(workflow_id)
        if wf is None:
            return WorkflowResult(
                workflow_id=workflow_id,
                status=WorkflowStatus.FAILED,
                error_summary=f"工作流不存在: {workflow_id}",
            )

        ctx = context or {}
        step_results: list[StepResult] = []
        errors: list[str] = []
        start_time = time.monotonic()
        aborted = False

        logger.info(f"开始执行工作流 {workflow_id}: {wf.name} ({len(wf.steps)} 步)")

        for step in wf.steps:
            if aborted:
                step_results.append(StepResult(
                    step_id=step.step_id,
                    success=False,
                    skipped=True,
                    error="前置步骤 abort，跳过",
                ))
                continue

            # 条件检查
            if step.condition and not self._evaluate_condition(step.condition, ctx):
                step_results.append(StepResult(
                    step_id=step.step_id,
                    success=True,
                    skipped=True,
                ))
                logger.debug(f"步骤 {step.step_id} 条件不满足，跳过")
                continue

            # 渲染模板变量
            rendered_params = render_template(step.params, ctx)
            rendered_action = render_template(step.action, ctx)

            # 执行步骤（含重试逻辑）
            sr = await self._execute_step(
                step, rendered_action, rendered_params, ctx,
            )
            step_results.append(sr)

            if not sr.success:
                errors.append(f"步骤 {step.step_id}: {sr.error or '执行失败'}")
                if step.on_failure == FailureStrategy.ABORT:
                    aborted = True
                # SKIP / RETRY 已在 _execute_step 内处理

        total_time = time.monotonic() - start_time

        # 判定整体状态
        has_failure = any(not r.success for r in step_results)
        has_skipped = any(r.skipped for r in step_results)

        if has_failure:
            status = WorkflowStatus.FAILED
        elif has_skipped:
            status = WorkflowStatus.PARTIAL
        else:
            status = WorkflowStatus.SUCCESS

        error_summary = "; ".join(errors) if errors else ""
        logger.info(
            f"工作流 {workflow_id} 执行完成: {status.value}, "
            f"耗时 {total_time:.2f}s"
        )

        return WorkflowResult(
            workflow_id=workflow_id,
            status=status,
            step_results=step_results,
            total_time=total_time,
            error_summary=error_summary,
        )

    # -- Agent 集成接口 --

    async def run_workflow(
        self,
        workflow_name_or_id: str,
        context: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """供 Agent 调用的工作流执行入口。

        支持 name 或 ID 查找。
        """
        # 先尝试 ID 查找
        wf = self._workflows.get(workflow_name_or_id)
        if wf is None:
            # 再尝试 name 查找
            for w in self._workflows.values():
                if w.name == workflow_name_or_id:
                    wf = w
                    break
        if wf is None:
            return WorkflowResult(
                workflow_id="",
                status=WorkflowStatus.FAILED,
                error_summary=f"找不到工作流: {workflow_name_or_id}",
            )
        return await self.execute_workflow(wf.id, context)

    # -- 内部方法 --

    async def _execute_step(
        self,
        step: WorkflowStep,
        action: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> StepResult:
        """执行单个步骤，处理重试。"""
        tool = self._tool_registry.get(step.tool_name)
        if tool is None:
            return StepResult(
                step_id=step.step_id,
                success=False,
                error=f"未注册的工具: {step.tool_name}",
            )

        max_attempts = _MAX_RETRIES if step.on_failure == FailureStrategy.RETRY else 1

        for attempt in range(max_attempts):
            try:
                result = await self._invoke_tool(tool, action, params)
                # 把结果写入 context，供后续步骤引用
                context[f"_step_{step.step_id}"] = result
                return StepResult(
                    step_id=step.step_id,
                    success=True,
                    output=result,
                    retried=attempt,
                )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"步骤 {step.step_id} 第 {attempt + 1} 次执行失败: {e}"
                )

        # 所有尝试都失败
        if step.on_failure == FailureStrategy.SKIP:
            return StepResult(
                step_id=step.step_id,
                success=True,
                skipped=True,
                error=last_error,
            )

        return StepResult(
            step_id=step.step_id,
            success=False,
            error=last_error,
            retried=max_attempts - 1,
        )

    @staticmethod
    async def _invoke_tool(tool: Any, action: str, params: dict[str, Any]) -> Any:
        """调用工具。"""
        if hasattr(tool, "execute"):
            return await tool.execute(action, params)
        if callable(tool):
            return await tool(action, params)
        raise TypeError(f"工具没有可调用的接口: {type(tool)}")

    @staticmethod
    def _evaluate_condition(condition: str, context: dict[str, Any]) -> bool:
        """评估条件表达式。

        支持简单的 ``variable==value`` 以及 ``variable`` (truthy) 形式。
        也支持 ``variable!=value``。
        """
        condition = condition.strip()

        # variable==value
        if "==" in condition:
            var, val = condition.split("==", 1)
            var = var.strip()
            val = val.strip()
            actual = context.get(var, "")
            return str(actual) == val

        # variable!=value
        if "!=" in condition:
            var, val = condition.split("!=", 1)
            var = var.strip()
            val = val.strip()
            actual = context.get(var, "")
            return str(actual) != val

        # bare variable → truthy
        return bool(context.get(condition, False))

    # -- 持久化 --

    def _save(self, wf: WorkflowDefinition) -> None:
        """保存工作流到 JSON 文件。"""
        self._storage.mkdir(parents=True, exist_ok=True)
        path = self._storage / f"{wf.id}.json"
        path.write_text(
            json.dumps(wf.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _delete_file(self, wf: WorkflowDefinition) -> None:
        """删除工作流对应的持久化文件。"""
        path = self._storage / f"{wf.id}.json"
        if path.exists():
            path.unlink()

    def _load_all(self) -> None:
        """从存储目录加载所有工作流。"""
        if not self._storage.exists():
            return
        for path in self._storage.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                wf = WorkflowDefinition.from_dict(data)
                self._workflows[wf.id] = wf
                logger.debug(f"加载工作流: {wf.id}")
            except Exception as e:
                logger.warning(f"加载工作流文件失败 ({path.name}): {e}")
