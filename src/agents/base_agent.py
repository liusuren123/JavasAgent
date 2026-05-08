"""基础 Agent 类。

实现感知→规划→执行→反思的核心循环。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.core.decider import Decider
from src.core.executor import Executor
from src.core.models import TaskPlan
from src.core.planner import Planner
from src.core.scheduler import Scheduler
from src.memory.short_term import ShortTermMemory
from src.utils.config import AppConfig
from src.utils.llm_client import LLMClient


class BaseAgent:
    """JavasAgent 基础 Agent。

    核心循环：
    1. 感知：接收用户输入
    2. 规划：将意图拆解为步骤
    3. 决策：判断是否需要询问人类
    4. 执行：按步骤执行
    5. 反馈：报告执行结果
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._llm = LLMClient(config.llm)
        self._planner = Planner(self._llm)
        self._executor = Executor()
        self._decider = Decider(config.agent)
        self._scheduler = Scheduler()
        self._memory = ShortTermMemory(config.memory.short_term_max_messages)

        self._running = False

    async def process(self, user_input: str) -> str:
        """处理用户输入（核心入口）。

        Args:
            user_input: 用户的自然语言指令

        Returns:
            处理结果或回复
        """
        logger.info(f"收到用户输入: {user_input[:100]}...")
        self._memory.add("user", user_input)

        # 1. 规划
        context = self._build_context()
        plan = await self._planner.plan(user_input, context)

        # 2. 决策检查（基于计划复杂度估算 confidence）
        confidence = self._estimate_confidence(plan, user_input)
        decision = self._decider.evaluate(
            context=user_input,
            question=plan.intent,
            confidence=confidence,
        )

        if not decision.auto_decided:
            response = f"我需要确认一下：{decision.question}"
            self._memory.add("assistant", response)
            return response

        # 3. 提交并执行
        task_id = await self._scheduler.submit(plan)
        self._scheduler.mark_running(plan)
        result = await self._executor.execute(plan)
        self._scheduler.mark_done(plan, result.success)

        # 4. 构建回复
        if result.success:
            response = (
                f"✅ 任务完成 ({result.completed_steps}/{result.total_steps} 步)\n"
                f"目标: {plan.intent}"
            )
        else:
            errors_str = "; ".join(result.errors)
            response = f"❌ 任务执行出现问题:\n{errors_str}"

        self._memory.add("assistant", response)
        return response

    def register_tool(self, name: str, tool: Any) -> None:
        """注册工具到执行引擎。"""
        self._executor.register_tool(name, tool)

    @staticmethod
    def _estimate_confidence(plan: TaskPlan, user_input: str) -> float:
        """根据计划复杂度估算 confidence。

        规则：
        - 基础 confidence 0.85
        - 步骤越多 confidence 越低（每步 -0.05，最低 -0.3）
        - 使用高风险工具（shell）额外 -0.15
        - 结果 clamp 到 [0.1, 1.0]
        """
        base = 0.85
        step_penalty = min(0.30, len(plan.steps) * 0.05)
        has_shell = any(s.tool == "shell" for s in plan.steps)
        shell_penalty = 0.15 if has_shell else 0.0
        confidence = base - step_penalty - shell_penalty
        return max(0.1, min(1.0, confidence))

    def _build_context(self) -> str:
        """构建当前上下文信息。"""
        parts: list[str] = []

        if self._memory.size > 0:
            recent = self._memory.get_messages(last_n=5)
            parts.append("最近的对话:")
            for msg in recent:
                role_label = {"user": "用户", "assistant": "助手", "system": "系统"}.get(
                    msg.role, msg.role
                )
                parts.append(f"  [{role_label}] {msg.content[:200]}")

        if self._scheduler.has_running_task:
            status = self._scheduler.get_status()
            parts.append(f"\n当前运行中的任务: {status['running']} 个")

        return "\n".join(parts)

    @property
    def is_running(self) -> bool:
        """Agent 是否正在运行。"""
        return self._running

    @property
    def status(self) -> dict[str, Any]:
        """获取 Agent 状态。"""
        return {
            "running": self._running,
            "scheduler": self._scheduler.get_status(),
            "memory_size": self._memory.size,
        }
