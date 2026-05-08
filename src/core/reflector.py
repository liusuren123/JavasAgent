"""反思审查引擎。

定期审查任务执行状态和代码质量，生成 ReflectionReport，
判断是否需要重新规划或调整策略。

支持两种模式：
- LLM 智能审查：通过大语言模型进行深度分析
- 规则审查：基于预定义规则进行快速检查
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from src.core.models import (
    ActionItem,
    PlanStatus,
    ReflectionReport,
    StepStatus,
    TaskPlan,
)
from src.utils.config import ReflectionConfig
from src.utils.llm_client import LLMClient

# 默认审查清单维度
DEFAULT_CHECKLIST = [
    "功能完整性",
    "代码质量",
    "测试覆盖",
    "性能",
    "安全",
    "架构",
    "目标对齐",
]

REFLECTOR_SYSTEM_PROMPT = """你是 JavasAgent 的反思审查引擎。

你的职责是审查当前任务执行状态，从以下维度进行评估：
{checklist}

请输出严格的 JSON 格式：
{{
    "checklist_results": {{
        "维度名称": "pass|warn|fail"
    }},
    "overall_score": 0.0到1.0的分数,
    "action_items": [
        {{
            "category": "维度名称",
            "description": "问题描述",
            "severity": "low|medium|high",
            "suggestion": "改进建议"
        }}
    ],
    "should_continue": true或false,
    "summary": "总体评价摘要"
}}

评估要点：
- 功能完整性：已完成的步骤是否真正达成了目标
- 代码质量：代码是否清晰、可维护
- 测试覆盖：是否有足够的测试保障
- 性能：是否存在性能瓶颈
- 安全：是否存在安全隐患
- 架构：是否符合架构设计
- 目标对齐：执行方向是否与原始意图一致
"""


class Reflector:
    """反思审查引擎。

    支持规则模式（快速）和 LLM 模式（深度）两种审查方式。
    """

    def __init__(
        self,
        config: ReflectionConfig | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self._config = config or ReflectionConfig()
        self._llm = llm
        self._checklist = self._config.checklist or DEFAULT_CHECKLIST
        self._last_reflection: ReflectionReport | None = None

    @property
    def last_reflection(self) -> ReflectionReport | None:
        """最近一次审查报告。"""
        return self._last_reflection

    @property
    def checklist(self) -> list[str]:
        """当前使用的审查清单。"""
        return list(self._checklist)

    async def reflect(self, plan: TaskPlan) -> ReflectionReport:
        """对任务计划执行反思审查。

        优先使用 LLM 进行智能审查，若 LLM 不可用则回退到规则审查。

        Args:
            plan: 当前执行中的任务计划

        Returns:
            ReflectionReport 审查报告
        """
        logger.info(f"开始反思审查: 计划 {plan.id}, 进度 {plan.progress:.0%}")

        if self._llm is not None:
            try:
                report = await self._llm_reflect(plan)
                self._last_reflection = report
                return report
            except Exception as e:
                logger.warning(f"LLM 审查失败，回退到规则审查: {e}")

        report = self._rule_based_reflect(plan)
        self._last_reflection = report
        return report

    def _rule_based_reflect(self, plan: TaskPlan) -> ReflectionReport:
        """基于规则的快速审查。

        根据计划状态、步骤完成率、失败率等指标进行评估。
        """
        checklist_results: dict[str, str] = {}
        action_items: list[ActionItem] = []
        total_steps = len(plan.steps)

        # 1. 功能完整性 — 检查步骤完成情况
        done_count = sum(1 for s in plan.steps if s.status == StepStatus.DONE)
        failed_count = sum(1 for s in plan.steps if s.status == StepStatus.FAILED)

        if total_steps == 0:
            checklist_results["功能完整性"] = "fail"
            action_items.append(ActionItem(
                category="功能完整性",
                description="计划没有任何步骤",
                severity="high",
                suggestion="需要重新规划，添加具体执行步骤",
            ))
        elif failed_count == 0 and done_count == total_steps:
            checklist_results["功能完整性"] = "pass"
        elif failed_count > total_steps * 0.5:
            checklist_results["功能完整性"] = "fail"
            action_items.append(ActionItem(
                category="功能完整性",
                description=f"失败率过高: {failed_count}/{total_steps} 步骤失败",
                severity="high",
                suggestion="检查失败原因，考虑重新规划",
            ))
        elif failed_count > 0:
            checklist_results["功能完整性"] = "warn"
            action_items.append(ActionItem(
                category="功能完整性",
                description=f"存在失败步骤: {failed_count}/{total_steps}",
                severity="medium",
                suggestion="检查失败步骤的错误信息并修复",
            ))
        else:
            checklist_results["功能完整性"] = "pass"

        # 2. 代码质量 — 规则模式下基于重试次数推断
        total_retries = sum(s.retry_count for s in plan.steps)
        if total_retries > total_steps * 2:
            checklist_results["代码质量"] = "warn"
            action_items.append(ActionItem(
                category="代码质量",
                description=f"重试次数过多: {total_retries} 次",
                severity="medium",
                suggestion="频繁重试可能意味着工具或参数配置不当",
            ))
        else:
            checklist_results["代码质量"] = "pass"

        # 3. 测试覆盖 — 规则模式下无法直接评估
        checklist_results["测试覆盖"] = "warn"
        action_items.append(ActionItem(
            category="测试覆盖",
            description="规则模式无法评估测试覆盖率",
            severity="low",
            suggestion="使用 LLM 模式进行深度审查",
        ))

        # 4. 性能 — 基于跳过的步骤数评估
        skipped_count = sum(1 for s in plan.steps if s.status == StepStatus.SKIPPED)
        if skipped_count > total_steps * 0.3:
            checklist_results["性能"] = "warn"
            action_items.append(ActionItem(
                category="性能",
                description=f"过多步骤被跳过: {skipped_count}/{total_steps}",
                severity="medium",
                suggestion="依赖链断裂导致步骤跳过，检查步骤编排",
            ))
        else:
            checklist_results["性能"] = "pass"

        # 5. 安全 — 检查是否有破坏性操作的步骤
        risky_keywords = ["删除", "格式化", "drop", "delete", "rm", "清空", "format"]
        risky_steps = [
            s for s in plan.steps
            if any(kw in s.action.lower() for kw in risky_keywords)
            and s.status != StepStatus.DONE
        ]
        if risky_steps:
            checklist_results["安全"] = "warn"
            action_items.append(ActionItem(
                category="安全",
                description=f"存在 {len(risky_steps)} 个高风险操作步骤待执行",
                severity="high",
                suggestion="确保高风险操作经过人工确认",
            ))
        else:
            checklist_results["安全"] = "pass"

        # 6. 架构 — 基于步骤依赖复杂度
        max_deps = max((len(s.depends_on) for s in plan.steps), default=0)
        if max_deps > 3:
            checklist_results["架构"] = "warn"
            action_items.append(ActionItem(
                category="架构",
                description=f"步骤依赖过深: 最大依赖数 {max_deps}",
                severity="low",
                suggestion="考虑拆分复杂依赖，提高并行度",
            ))
        else:
            checklist_results["架构"] = "pass"

        # 7. 目标对齐 — 基于计划状态
        if plan.status == PlanStatus.FAILED:
            checklist_results["目标对齐"] = "fail"
            action_items.append(ActionItem(
                category="目标对齐",
                description="计划已失败，目标未达成",
                severity="high",
                suggestion="需要重新规划或调整目标",
            ))
        elif plan.progress < 0.3 and plan.status == PlanStatus.RUNNING:
            checklist_results["目标对齐"] = "warn"
            action_items.append(ActionItem(
                category="目标对齐",
                description=f"进度较低: {plan.progress:.0%}，可能需要调整策略",
                severity="medium",
                suggestion="评估当前方案是否有效，考虑替代路径",
            ))
        else:
            checklist_results["目标对齐"] = "pass"

        # 计算总分
        score_map = {"pass": 1.0, "warn": 0.5, "fail": 0.0}
        scores = [score_map.get(v, 0.0) for v in checklist_results.values()]
        overall_score = sum(scores) / len(scores) if scores else 0.0

        # 判断是否继续
        has_high_severity = any(item.severity == "high" for item in action_items)
        should_continue = overall_score >= 0.3 and not has_high_severity

        summary = self._generate_summary(checklist_results, overall_score, plan)

        report = ReflectionReport(
            timestamp=datetime.now(),
            checklist_results=checklist_results,
            overall_score=overall_score,
            action_items=action_items,
            should_continue=should_continue,
            summary=summary,
        )

        logger.info(
            f"反思完成: 得分 {overall_score:.2f}, "
            f"行动项 {len(action_items)}, 继续={should_continue}"
        )
        return report

    async def _llm_reflect(self, plan: TaskPlan) -> ReflectionReport:
        """通过 LLM 进行深度智能审查。"""
        checklist_str = "\n".join(f"- {item}" for item in self._checklist)

        system_prompt = REFLECTOR_SYSTEM_PROMPT.format(checklist=checklist_str)

        # 构建计划状态描述
        steps_info = []
        for s in plan.steps:
            steps_info.append({
                "id": s.id,
                "action": s.action,
                "tool": s.tool,
                "status": s.status.value,
                "retry_count": s.retry_count,
                "depends_on": s.depends_on,
            })

        user_message = (
            f"计划 ID: {plan.id}\n"
            f"意图: {plan.intent}\n"
            f"状态: {plan.status.value}\n"
            f"进度: {plan.progress:.0%}\n"
            f"步骤:\n{self._format_steps_json(steps_info)}\n\n"
            f"请进行反思审查。"
        )

        response = await self._llm.chat_with_system(
            system_prompt=system_prompt,
            user_message=user_message,
        )

        return self._parse_llm_response(response)

    def _parse_llm_response(self, response: str) -> ReflectionReport:
        """解析 LLM 返回的 JSON 为 ReflectionReport。"""
        import json

        try:
            text = response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data: dict[str, Any] = json.loads(text)
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"LLM 返回非 JSON 格式，使用默认报告: {e}")
            return ReflectionReport(
                checklist_results={item: "warn" for item in self._checklist},
                overall_score=0.5,
                action_items=[],
                should_continue=True,
                summary="LLM 审查结果解析失败，使用默认评估",
            )

        action_items = [
            ActionItem(
                category=item.get("category", "未知"),
                description=item.get("description", ""),
                severity=item.get("severity", "medium"),
                suggestion=item.get("suggestion", ""),
            )
            for item in data.get("action_items", [])
        ]

        return ReflectionReport(
            timestamp=datetime.now(),
            checklist_results=data.get("checklist_results", {}),
            overall_score=float(data.get("overall_score", 0.5)),
            action_items=action_items,
            should_continue=bool(data.get("should_continue", True)),
            summary=data.get("summary", ""),
        )

    @staticmethod
    def _format_steps_json(steps_info: list[dict[str, Any]]) -> str:
        """格式化步骤信息为 JSON 字符串。"""
        import json

        return json.dumps(steps_info, ensure_ascii=False, indent=2)

    @staticmethod
    def _generate_summary(
        checklist_results: dict[str, str],
        overall_score: float,
        plan: TaskPlan,
    ) -> str:
        """生成审查摘要。"""
        pass_count = sum(1 for v in checklist_results.values() if v == "pass")
        warn_count = sum(1 for v in checklist_results.values() if v == "warn")
        fail_count = sum(1 for v in checklist_results.values() if v == "fail")

        parts = [f"计划 '{plan.intent[:30]}' 审查完成。"]
        parts.append(f"得分: {overall_score:.1%}，通过 {pass_count} / 警告 {warn_count} / 失败 {fail_count}。")

        if fail_count > 0:
            failed_dims = [k for k, v in checklist_results.items() if v == "fail"]
            parts.append(f"失败维度: {', '.join(failed_dims)}。")

        return " ".join(parts)
