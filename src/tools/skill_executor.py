"""技能执行引擎模块。

根据任务描述自动匹配、加载、执行已注册的技能，
并将执行结果反馈给 SkillLearner 形成学习闭环。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime
from typing import Any

from loguru import logger

from src.memory.skill_models import SkillDefinition
from src.memory.skill_registry import SkillRegistry
from src.tools.skill_chain import SkillChainExecutor
from src.tools.skill_executor_models import (
    ExecutionRecord,
    SkillChainStep,
    SkillMatch,
)
from src.tools.skill_feedback import SkillFeedback
from src.tools.skill_matcher import SkillMatcher

# 执行超时（秒）
DEFAULT_EXECUTION_TIMEOUT = 60
# 最大历史记录数
MAX_HISTORY_SIZE = 200


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

        result = await executor.execute("execute_skill", {
            "skill_name": "截图",
            "params": {"region": "full"},
        })

        result = await executor.execute("auto_execute", {
            "task_description": "截取屏幕并保存到桌面",
        })
    """

    def __init__(
        self,
        skill_registry: SkillRegistry,
        skill_learner: Any | None = None,
        execution_timeout: float = DEFAULT_EXECUTION_TIMEOUT,
        step_executor: Any | None = None,
    ) -> None:
        self._registry = skill_registry
        self._learner = skill_learner
        self._timeout = execution_timeout
        self._step_executor = step_executor  # YAML 技能的步骤执行器

        self._matcher = SkillMatcher()
        self._feedback = SkillFeedback(learner=skill_learner)
        self._chain_executor = SkillChainExecutor(self._execute_skill)

        self._history: list[ExecutionRecord] = []
        self._executors: dict[str, Any] = {}

        logger.debug(
            "SkillExecutor 初始化 (timeout={}s, learner={}, yaml_executor={})",
            self._timeout,
            "已绑定" if self._learner else "未绑定",
            "已绑定" if self._step_executor else "未绑定",
        )

    # ------------------------------------------------------------------
    # 执行函数注册
    # ------------------------------------------------------------------

    def register_executor(self, skill_name: str, executor_fn: Any) -> None:
        """注册技能的实际执行函数。"""
        self._executors[skill_name] = executor_fn
        logger.debug("注册执行函数: {}", skill_name)

    def unregister_executor(self, skill_name: str) -> bool:
        """注销技能的执行函数。"""
        if skill_name in self._executors:
            del self._executors[skill_name]
            logger.debug("注销执行函数: {}", skill_name)
            return True
        return False

    # ------------------------------------------------------------------
    # 统一执行入口
    # ------------------------------------------------------------------

    async def execute(self, action: str, params: dict) -> Any:
        """统一执行入口，根据 action 分发到不同的处理逻辑。"""
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
        """处理 execute_skill action。"""
        skill_name = params.get("skill_name")
        if not skill_name:
            return {"success": False, "error": "缺少 skill_name 参数"}

        skill_params = params.get("params", {})
        return await self._execute_skill(skill_name, skill_params)

    async def _handle_auto_execute(self, params: dict) -> dict:
        """处理 auto_execute action。"""
        task_description = params.get("task_description")
        if not task_description:
            return {"success": False, "error": "缺少 task_description 参数"}

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
        result["match"] = best_match.to_dict()
        return result

    async def _handle_recommend(self, params: dict) -> dict:
        """处理 recommend action。"""
        task_description = params.get("task_description", "")
        top_k = params.get("top_k", 5)

        recommendations = await self.get_skill_recommendations(
            task_description, top_k=top_k
        )
        return {"success": True, "recommendations": recommendations}

    async def _handle_history(self, params: dict) -> dict:
        """处理 history action。"""
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
        """执行单个技能：查找定义 → 校验参数 → 执行 → 记录。"""
        skill = await self._registry.get_by_name(skill_name)
        if skill is None:
            error_msg = f"技能不存在: {skill_name}"
            logger.warning(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=0
            )
            return {"success": False, "error": error_msg}

        validation_error = await self._validate_params(skill, params)
        if validation_error is not None:
            error_msg = f"参数校验失败: {validation_error}"
            logger.warning(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=0
            )
            return {"success": False, "error": error_msg}

        # --- YAML 技能执行路径 ---
        if getattr(skill, "yaml_path", "") and self._step_executor:
            return await self._execute_yaml_skill(skill, params)

        # --- 注册函数执行路径（原有逻辑） ---
        executor_fn = self._executors.get(skill_name)
        if executor_fn is None:
            error_msg = f"技能 '{skill_name}' 没有注册执行函数"
            logger.warning(error_msg)
            await self._record_execution(
                skill_name, params, {}, success=False, error=error_msg, duration_ms=0
            )
            return {"success": False, "error": error_msg}

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
            logger.info("技能执行成功: {} (耗时 {}ms)", skill_name, duration_ms)
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
        """调用执行函数，兼容同步和异步。"""
        if asyncio.iscoroutinefunction(executor_fn):
            return await executor_fn(params)
        else:
            return executor_fn(params)

    # ------------------------------------------------------------------
    # YAML 技能执行
    # ------------------------------------------------------------------

    async def _execute_yaml_skill(self, skill: SkillDefinition, params: dict) -> dict:
        """执行 YAML 技能：创建上下文 → 调用 StepExecutor。"""
        from src.skills.context import SkillContext

        start_time = time.monotonic()
        try:
            context = SkillContext(parameters=params)
            steps = getattr(skill, "steps", [])
            result = await self._step_executor.execute_steps(steps, context)
            duration_ms = int((time.monotonic() - start_time) * 1000)

            await self._record_execution(
                skill.name, params, result,
                success=result.get("success", True),
                error=result.get("error", ""),
                duration_ms=duration_ms,
            )
            result["duration_ms"] = duration_ms
            return result

        except Exception as e:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            error_msg = f"YAML 技能执行异常: {e}"
            logger.exception(error_msg)
            await self._record_execution(
                skill.name, params, {}, success=False, error=error_msg, duration_ms=duration_ms
            )
            return {"success": False, "error": error_msg, "duration_ms": duration_ms}

    # ------------------------------------------------------------------
    # 技能匹配（委托给 SkillMatcher）
    # ------------------------------------------------------------------

    async def _match_skill(self, task_description: str) -> list[SkillMatch]:
        """根据任务描述匹配最合适的技能。"""
        candidates = await self._registry.search(task_description, top_k=10)
        return self._matcher.match(task_description, candidates)

    # ------------------------------------------------------------------
    # 参数校验
    # ------------------------------------------------------------------

    async def _validate_params(
        self, skill: SkillDefinition, params: dict
    ) -> str | None:
        """校验执行参数。"""
        schema = skill.parameters
        if not schema:
            return None

        required_fields = schema.get("required", [])
        properties = schema.get("properties", {})

        for field_name in required_fields:
            if field_name not in params:
                return f"缺少必填参数: {field_name}"

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
        """检查值是否符合预期 JSON Schema 类型。"""
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
    # 执行记录（委托给 SkillFeedback）
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
        """记录执行结果并反馈学习。"""
        record = ExecutionRecord(
            record_id=f"exec_{uuid.uuid4().hex[:12]}",
            skill_name=skill_name,
            params_summary=self._feedback.summarize_params(params),
            result_summary=self._feedback.summarize_result(result),
            success=success,
            error=error,
            duration_ms=duration_ms,
            timestamp=datetime.now().isoformat(),
        )

        self._history.append(record)

        if len(self._history) > MAX_HISTORY_SIZE:
            self._history = self._history[-MAX_HISTORY_SIZE:]

        await self._feedback.send(record, params, result)

        logger.debug(
            "记录执行: {} success={}, duration={}ms",
            skill_name, success, duration_ms,
        )

    # ------------------------------------------------------------------
    # 技能链执行（委托给 SkillChainExecutor）
    # ------------------------------------------------------------------

    async def execute_chain(self, steps: list[SkillChainStep]) -> Any:
        """执行技能链（委托给 SkillChainExecutor）。"""
        return await self._chain_executor.run(steps)

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    async def get_execution_history(self, limit: int = 20) -> list[ExecutionRecord]:
        """获取执行历史记录（按时间倒序）。"""
        return list(reversed(self._history[-limit:]))

    async def get_skill_recommendations(
        self,
        task_description: str,
        top_k: int = 5,
    ) -> list[dict]:
        """获取技能推荐，考虑历史执行成功率。"""
        matches = await self._match_skill(task_description)
        recommendations: list[dict] = []

        for match in matches[:top_k]:
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
