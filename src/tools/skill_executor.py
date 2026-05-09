"""技能执行引擎模块。

根据任务描述自动匹配、加载、执行已注册的技能，
并将执行结果反馈给 SkillLearner 形成学习闭环。
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from src.memory.skill_models import SkillDefinition
from src.memory.skill_registry import SkillRegistry
from src.tools.skill_executor_models import (
    ExecutionRecord,
    SkillChainResult,
    SkillChainStep,
    SkillMatch,
)

# 执行超时（秒）
DEFAULT_EXECUTION_TIMEOUT = 60
# 最大历史记录数
MAX_HISTORY_SIZE = 200
# 参数摘要最大长度
PARAM_SUMMARY_MAX_LEN = 200


class SkillExecutor:
    """技能执行引擎。

    根据任务描述自动匹配、加载、执行已注册的技能，
    并将执行结果反馈给 SkillLearner 形成学习闭环。

    支持四种 action：
    - ``execute_skill``  — 执行指定技能
    - ``auto_execute``   — 根据任务描述自动匹配并执行最合适的技能
    - ``recommend``      — 获取技能推荐
    - ``history``        — 查看执行历史

    Usage::

        registry = SkillRegistry()
        executor = SkillExecutor(skill_registry=registry)

        # 执行指定技能
        result = await executor.execute("execute_skill", {
            "skill_name": "截图",
            "params": {"region": "full"},
        })

        # 自动匹配并执行
        result = await executor.execute("auto_execute", {
            "task_description": "截取屏幕并保存到桌面",
        })
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        skill_learner: Any | None = None,
        execution_timeout: float = DEFAULT_EXECUTION_TIMEOUT,
    ) -> None:
        """初始化技能执行引擎。

        Args:
            skill_registry: 技能注册表实例。
            skill_learner: 技能学习器实例（可选，用于反馈学习）。
            execution_timeout: 单个技能执行的超时时间（秒）。
        """
        self._registry = skill_registry
        self._learner = skill_learner
        self._timeout = execution_timeout

        # 内存中的执行历史
        self._history: list[ExecutionRecord] = []

        # 已注册的执行函数：skill_name -> callable
        self._executors: dict[str, Any] = {}

        logger.debug(
            "SkillExecutor 初始化 (timeout={}s, learner={})",
            self._timeout,
            "已绑定" if self._learner else "未绑定",
        )

    # ------------------------------------------------------------------
    # 执行函数注册
    # ------------------------------------------------------------------

    def register_executor(self, skill_name: str, executor_fn: Any) -> None:
        """注册技能的实际执行函数。

        Args:
            skill_name: 技能名称。
            executor_fn: 可调用对象，接受 (params: dict) -> dict。
        """
        self._executors[skill_name] = executor_fn
        logger.debug("注册执行函数: {}", skill_name)

    def unregister_executor(self, skill_name: str) -> bool:
        """注销技能的执行函数。

        Args:
            skill_name: 技能名称。

        Returns:
            是否成功注销。
        """
        if skill_name in self._executors:
            del self._executors[skill_name]
            logger.debug("注销执行函数: {}", skill_name)
            return True
        return False

    # ------------------------------------------------------------------
    # 统一执行入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict) -> Any:
        """统一执行入口。

        根据 action 分发到不同的处理逻辑。

        Args:
            action: 操作类型。
            params: 操作参数。

        Returns:
            执行结果。

        Raises:
            ValueError: 不支持的 action。
        """
        logger.debug("SkillExecutor.execute: action={}, params={}", action, params)

        if action == "execute_skill":
            return await self._handle_execute_skill(params)
        elif action == "auto_execute":
            return await self._handle_auto_execute(params)
        elif action == "recommend":
            return await self._handle_recommend(params)
        elif action == "history":
            return await self._handle_history(params)
        else:
            raise ValueError(f"不支持的 action: {action}")

    # ------------------------------------------------------------------
    # action 处理
    # ------------------------------------------------------------------

    async def _handle_execute_skill(self, params: dict) -> dict:
        """处理 execute_skill action。

        执行指定名称的技能。

        Args:
            params: 包含 ``skill_name`` 和可选的 ``params``。

        Returns:
            执行结果字典。
        """
        skill_name = params.get("skill_name")
        if not skill_name:
            return {"success": False, "error": "缺少 skill_name 参数"}

        skill_params = params.get("params", {})
        return await self._execute_skill(skill_name, skill_params)

    async def _handle_auto_execute(self, params: dict) -> dict:
        """处理 auto_execute action。

        根据任务描述自动匹配最合适的技能并执行。

        Args:
            params: 包含 ``task_description`` 和可选的 ``params``。

        Returns:
            执行结果字典，附带匹配信息。
        """
        task_description = params.get("task_description")
        if not task_description:
            return {"success": False, "error": "缺少 task_description 参数"}

        # 匹配技能
        matches = await self._match_skill(task_description)
        if not matches:
            return {
                "success": False,
                "error": f"未找到匹配的技能: {task_description}",
                "matches": [],
            }

        best_match = matches[0]
        logger.info(
            "自动匹配: '{}' -> {} (score={:.2f})",
            task_description,
            best_match.skill_name,
            best_match.relevance_score,
        )

        skill_params = params.get("params", {})
        result = await self._execute_skill(best_match.skill_name, skill_params)

        # 附加匹配信息
        result["match"] = best_match.to_dict()
        return result

    async def _handle_recommend(self, params: dict) -> dict:
        """处理 recommend action。

        获取与任务描述相关的技能推荐列表。

        Args:
            params: 包含 ``task_description`` 和可选的 ``top_k``。

        Returns:
            推荐列表。
        """
        task_description = params.get("task_description", "")
        top_k = params.get("top_k", 5)

        recommendations = await self.get_skill_recommendations(
            task_description, top_k=top_k
        )
        return {"success": True, "recommendations": recommendations}

    async def _handle_history(self, params: dict) -> dict:
        """处理 history action。

        获取执行历史记录。

        Args:
            params: 可选的 ``limit``。

        Returns:
            历史记录列表。
        """
        limit = params.get("limit", 20)
        history = await self.get_execution_history(limit=limit)
        return {
            "success": True,
            "history": [r.to_dict() for r in history],
            "total": len(self._history),
        }

    # ------------------------------------------------------------------
    # 核心执行逻辑
    # ------------------------------------------------------------------

    async def _execute_skill(self, skill_name: str, params: dict) -> dict:
        """执行单个技能。

        查找技能定义和执行函数，校验参数，执行并记录结果。

        Args:
            skill_name: 技能名称。
            params: 执行参数。

        Returns:
            执行结果字典。
        """
        # 查找技能定义
        skill = await self._registry.get_by_name(skill_name)
        if skill is None:
            error_msg = f"技能不存在: {skill_name}"
            logger.warning(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=0
            )
            return {"success": False, "error": error_msg}

        # 参数校验
        validation_error = await self._validate_params(skill, params)
        if validation_error is not None:
            error_msg = f"参数校验失败: {validation_error}"
            logger.warning(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=0
            )
            return {"success": False, "error": error_msg}

        # 查找执行函数
        executor_fn = self._executors.get(skill_name)
        if executor_fn is None:
            error_msg = f"技能 '{skill_name}' 没有注册执行函数"
            logger.warning(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=0
            )
            return {"success": False, "error": error_msg}

        # 执行
        start_time = time.monotonic()
        try:
            result = await asyncio.wait_for(
                self._call_executor(executor_fn, params),
                timeout=self._timeout,
            )
            duration_ms = int((time.monotonic() - start_time) * 1000)

            result_data = result if isinstance(result, dict) else {"value": result}
            await self._record_execution(
                skill_name, params, result_data, success=True, error="", duration_ms=duration_ms
            )
            logger.info(
                "技能执行成功: {} (耗时 {}ms)", skill_name, duration_ms
            )
            return {"success": True, "data": result_data, "duration_ms": duration_ms}

        except asyncio.TimeoutError:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"技能 '{skill_name}' 执行超时 ({self._timeout}s)"
            logger.warning(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=duration_ms
            )
            return {"success": False, "error": error_msg, "duration_ms": duration_ms}

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"技能 '{skill_name}' 执行异常: {e}"
            logger.exception(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=duration_ms
            )
            return {"success": False, "error": error_msg, "duration_ms": duration_ms}

    async def _call_executor(self, executor_fn: Any, params: dict) -> Any:
        """调用执行函数，兼容同步和异步。

        Args:
            executor_fn: 执行函数。
            params: 参数。

        Returns:
            执行结果。
        """
        if asyncio.iscoroutinefunction(executor_fn):
            return await executor_fn(params)
        else:
            return executor_fn(params)

    # ------------------------------------------------------------------
    # 技能匹配
    # ------------------------------------------------------------------

    async def _match_skill(self, task_description: str) -> list[SkillMatch]:
        """根据任务描述匹配最合适的技能。

        使用 SkillRegistry 的搜索功能获取候选技能，
        然后计算每个候选的相关度分数。

        Args:
            task_description: 任务描述文本。

        Returns:
            按相关度降序排列的匹配列表。
        """
        candidates = await self._registry.search(task_description, top_k=10)
        if not candidates:
            return []

        matches: list[SkillMatch] = []
        desc_lower = task_description.lower()
        desc_terms = set(re.findall(r"\w+", desc_lower))

        for skill in candidates:
            score = self._compute_match_score(skill, desc_lower, desc_terms)
            reason = self._compute_match_reason(skill, desc_lower, desc_terms)

            # 归一化到 0.0-1.0
            normalized = min(1.0, score / 10.0)

            if normalized > 0.0:
                matches.append(
                    SkillMatch(
                        skill_name=skill.name,
                        relevance_score=round(normalized, 4),
                        match_reason=reason,
                    )
                )

        matches.sort(key=lambda m: m.relevance_score, reverse=True)
        return matches

    def _compute_match_score(
        self,
        skill: SkillDefinition,
        desc_lower: str,
        desc_terms: set[str],
    ) -> float:
        """计算技能与任务描述的匹配分数。

        Args:
            skill: 技能定义。
            desc_lower: 小写的任务描述。
            desc_terms: 任务描述的词汇集合。

        Returns:
            原始匹配分数。
        """
        score = 0.0
        name_lower = skill.name.lower()
        description_lower = skill.description.lower()

        # 精确名称匹配
        if desc_lower == name_lower:
            score += 10.0
        elif desc_lower in name_lower or name_lower in desc_lower:
            score += 6.0

        # 描述匹配
        if desc_lower in description_lower:
            score += 3.0

        # 标签匹配
        for tag in skill.tags:
            tag_lower = tag.lower()
            if desc_lower == tag_lower:
                score += 5.0
            elif desc_lower in tag_lower or tag_lower in desc_lower:
                score += 2.0

        # 词汇级别匹配
        name_terms = set(re.findall(r"\w+", name_lower))
        desc_skill_terms = set(re.findall(r"\w+", description_lower))

        name_overlap = len(desc_terms & name_terms)
        desc_overlap = len(desc_terms & desc_skill_terms)
        score += name_overlap * 1.5 + desc_overlap * 0.8

        return score

    def _compute_match_reason(
        self,
        skill: SkillDefinition,
        desc_lower: str,
        desc_terms: set[str],
    ) -> str:
        """生成匹配原因说明。"""
        reasons: list[str] = []
        name_lower = skill.name.lower()

        if desc_lower in name_lower or name_lower in desc_lower:
            reasons.append("名称匹配")
        if desc_lower in skill.description.lower():
            reasons.append("描述匹配")

        matched_tags = [
            tag for tag in skill.tags
            if desc_lower in tag.lower() or tag.lower() in desc_lower
        ]
        if matched_tags:
            reasons.append(f"标签匹配: {', '.join(matched_tags[:3])}")

        name_terms = set(re.findall(r"\w+", name_lower))
        overlap = desc_terms & name_terms
        if overlap:
            reasons.append(f"关键词命中: {', '.join(list(overlap)[:5])}")

        return "; ".join(reasons) if reasons else "语义关联"

    # ------------------------------------------------------------------
    # 参数校验
    # ------------------------------------------------------------------

    async def _validate_params(
        self, skill: SkillDefinition, params: dict
    ) -> str | None:
        """校验执行参数。

        检查必填参数是否存在，参数类型是否正确。

        Args:
            skill: 技能定义。
            params: 待校验的参数。

        Returns:
            错误信息字符串，校验通过返回 None。
        """
        schema = skill.parameters
        if not schema:
            return None

        # schema 中 "required" 列表
        required_fields = schema.get("required", [])
        properties = schema.get("properties", {})

        # 检查必填参数
        for field_name in required_fields:
            if field_name not in params:
                return f"缺少必填参数: {field_name}"

        # 检查参数类型（如果 schema 中定义了类型）
        for field_name, value in params.items():
            field_schema = properties.get(field_name)
            if field_schema is None:
                continue

            expected_type = field_schema.get("type")
            if expected_type and not self._check_type(value, expected_type):
                return (
                    f"参数 '{field_name}' 类型错误: "
                    f"期望 {expected_type}, 实际 {type(value).__name__}"
                )

        return None

    @staticmethod
    def _check_type(value: Any, expected_type: str) -> bool:
        """检查值是否符合预期类型。

        Args:
            value: 待检查的值。
            expected_type: JSON Schema 风格的类型名称。

        Returns:
            是否匹配。
        """
        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected = type_map.get(expected_type)
        if expected is None:
            return True
        return isinstance(value, expected)

    # ------------------------------------------------------------------
    # 执行记录
    # ------------------------------------------------------------------

    async def _record_execution(
        self,
        skill_name: str,
        params: dict,
        result: dict,
        success: bool,
        error: str,
        duration_ms: int,
    ) -> None:
        """记录执行结果。

        将执行记录添加到内部历史，并通过 SkillLearner 反馈学习。

        Args:
            skill_name: 技能名称。
            params: 执行参数。
            result: 执行结果。
            success: 是否成功。
            error: 错误信息。
            duration_ms: 耗时（毫秒）。
        """
        record = ExecutionRecord(
            record_id=f"exec_{uuid.uuid4().hex[:12]}",
            skill_name=skill_name,
            params_summary=self._summarize_params(params),
            result_summary=self._summarize_result(result),
            success=success,
            error=error,
            duration_ms=duration_ms,
            timestamp=datetime.now().isoformat(),
        )

        self._history.append(record)

        # 限制历史大小
        if len(self._history) > MAX_HISTORY_SIZE:
            self._history = self._history[-MAX_HISTORY_SIZE:]

        # 反馈给学习器
        await self._feedback_to_learner(record, params, result)

        logger.debug(
            "记录执行: {} success={}, duration={}ms",
            skill_name,
            success,
            duration_ms,
        )

    async def _feedback_to_learner(
        self,
        record: ExecutionRecord,
        params: dict,
        result: dict,
    ) -> None:
        """将执行结果反馈给 SkillLearner。

        如果学习器存在，构造一个简单的 TaskPlan 和 ExecutionResult
        传给 ``record_execution()`` 形成学习闭环。

        Args:
            record: 执行记录。
            params: 原始参数。
            result: 原始结果。
        """
        if self._learner is None:
            return

        try:
            from src.core.models import (
                ExecutionResult,
                PlanStatus,
                Step,
                StepStatus,
                TaskPlan,
            )

            step = Step(
                id=f"step_{record.record_id}",
                action="execute_skill",
                tool=record.skill_name,
                params=params,
                status=StepStatus.DONE if record.success else StepStatus.FAILED,
                result=str(record.result_summary) if record.success else None,
                error=record.error if not record.success else None,
            )

            plan = TaskPlan(
                id=f"plan_{record.record_id}",
                intent=f"执行技能: {record.skill_name}",
                steps=[step],
                status=PlanStatus.DONE if record.success else PlanStatus.FAILED,
            )

            exec_result = ExecutionResult(
                plan_id=plan.id,
                success=record.success,
                completed_steps=1 if record.success else 0,
                total_steps=1,
                errors=[record.error] if record.error else [],
                output=result,
            )

            await self._learner.record_execution(plan, exec_result)
            logger.debug("已反馈学习器: {}", record.skill_name)

        except Exception:
            logger.exception("反馈学习器失败: {}", record.skill_name)

    def _summarize_params(self, params: dict) -> dict:
        """生成参数摘要。

        对过长的值进行截断，避免历史记录占用过多内存。

        Args:
            params: 原始参数。

        Returns:
            参数摘要字典。
        """
        summary: dict[str, Any] = {}
        for key, value in params.items():
            if isinstance(value, str) and len(value) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = value[:PARAM_SUMMARY_MAX_LEN] + "..."
            elif isinstance(value, (list, dict)) and len(str(value)) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = f"<{type(value).__name__} len={len(value)}>"
            else:
                summary[key] = value
        return summary

    def _summarize_result(self, result: dict) -> dict:
        """生成结果摘要。

        Args:
            result: 原始结果。

        Returns:
            结果摘要字典。
        """
        summary: dict[str, Any] = {}
        for key, value in result.items():
            if isinstance(value, str) and len(value) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = value[:PARAM_SUMMARY_MAX_LEN] + "..."
            elif isinstance(value, (list, dict)) and len(str(value)) > PARAM_SUMMARY_MAX_LEN:
                summary[key] = f"<{type(value).__name__} len={len(value)}>"
            else:
                summary[key] = value
        return summary

    # ------------------------------------------------------------------
    # 技能链执行
    # ------------------------------------------------------------------

    async def execute_chain(self, steps: list[SkillChainStep]) -> SkillChainResult:
        """执行技能链。

        按顺序执行多个技能步骤，支持步骤间的依赖关系。
        前一步骤的结果可以作为后续步骤的参数（通过 ``$prev`` 引用）。

        Args:
            steps: 技能链步骤列表。

        Returns:
            技能链执行结果。
        """
        chain_id = f"chain_{uuid.uuid4().hex[:8]}"
        logger.info("开始技能链执行: {} ({} 步)", chain_id, len(steps))

        start_time = time.monotonic()
        step_results: list[dict[str, Any]] = []
        completed: dict[int, dict[str, Any]] = {}
        chain_success = True
        chain_error = ""

        for step in steps:
            # 检查依赖是否都已完成
            deps_ok = all(dep in completed for dep in step.depends_on)
            if not deps_ok:
                chain_success = False
                chain_error = f"步骤 {step.step_index} 的依赖未完成"
                step_results.append({"success": False, "error": chain_error})
                break

            # 注入前序步骤的结果
            resolved_params = self._resolve_chain_params(step, completed)

            # 执行
            result = await self._execute_skill(step.skill_name, resolved_params)
            step_results.append(result)

            if result.get("success", False):
                completed[step.step_index] = result.get("data", {})
            else:
                chain_success = False
                chain_error = f"步骤 {step.step_index} ({step.skill_name}) 执行失败: {result.get('error', '')}"
                break

        total_duration_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "技能链完成: {} success={}, duration={}ms",
            chain_id,
            chain_success,
            total_duration_ms,
        )

        return SkillChainResult(
            chain_id=chain_id,
            steps=steps,
            step_results=step_results,
            success=chain_success,
            error=chain_error,
            total_duration_ms=total_duration_ms,
        )

    def _resolve_chain_params(
        self,
        step: SkillChainStep,
        completed: dict[int, dict[str, Any]],
    ) -> dict[str, Any]:
        """解析技能链参数中的依赖引用。

        支持以 ``$step_{index}`` 格式引用前序步骤的结果。

        Args:
            step: 当前步骤。
            completed: 已完成步骤的结果映射。

        Returns:
            解析后的参数字典。
        """
        resolved = dict(step.params)

        # 将依赖步骤的结果注入到参数中
        for dep_index in step.depends_on:
            dep_key = f"$step_{dep_index}"
            if dep_index in completed:
                resolved[dep_key] = completed[dep_index]

        return resolved

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    async def get_execution_history(self, limit: int = 20) -> list[ExecutionRecord]:
        """获取执行历史记录。

        按时间倒序返回最近的执行记录。

        Args:
            limit: 返回的最大记录数。

        Returns:
            执行记录列表。
        """
        return list(reversed(self._history[-limit:]))

    async def get_skill_recommendations(
        self,
        task_description: str,
        top_k: int = 5,
    ) -> list[dict]:
        """获取技能推荐。

        根据任务描述匹配技能，并考虑历史执行成功率进行调整。

        Args:
            task_description: 任务描述。
            top_k: 返回的最大推荐数。

        Returns:
            推荐列表，每项包含技能名称、分数、原因和成功率。
        """
        matches = await self._match_skill(task_description)
        recommendations: list[dict] = []

        for match in matches[:top_k]:
            # 查询历史成功率
            success_count = 0
            total_count = 0
            for record in self._history:
                if record.skill_name == match.skill_name:
                    total_count += 1
                    if record.success:
                        success_count += 1

            success_rate = success_count / total_count if total_count > 0 else None

            recommendations.append({
                "skill_name": match.skill_name,
                "relevance_score": match.relevance_score,
                "match_reason": match.match_reason,
                "historical_success_rate": success_rate,
                "historical_executions": total_count,
            })

        return recommendations

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    @property
    def history_count(self) -> int:
        """执行历史记录总数。"""
        return len(self._history)

    @property
    def registered_executor_count(self) -> int:
        """已注册的执行函数数量。"""
        return len(self._executors)

    def get_stats(self) -> dict[str, Any]:
        """获取执行引擎统计信息。"""
        success_count = sum(1 for r in self._history if r.success)
        failure_count = len(self._history) - success_count

        avg_duration = 0.0
        if self._history:
            avg_duration = sum(r.duration_ms for r in self._history) / len(self._history)

        return {
            "total_executions": len(self._history),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": round(success_count / len(self._history), 4) if self._history else 0.0,
            "avg_duration_ms": round(avg_duration, 2),
            "registered_executors": len(self._executors),
        }
