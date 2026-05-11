"""任务规划器。

将用户意图解析为可执行的步骤链。
支持动态工具注册，使 LLM 只规划当前可用的工具。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from loguru import logger

from src.core.models import Priority, Step, TaskPlan
from src.utils.llm_client import LLMClient

# 默认工具描述（当没有注册自定义工具时使用）
_DEFAULT_TOOL_DESCRIPTIONS: dict[str, str] = {
    "system_control": "文件操作、进程管理、窗口控制",
    "code_dev": "代码生成、调试、测试",
    "office_ops": "Word/Excel/PPT 操作",
    "creative_tools": "PS/PR 等 Adobe 工具",
    "browser_control": "浏览器自动化",
    "shell": "执行终端命令",
}

_PLANNER_PROMPT_TEMPLATE = """你是 JavasAgent 的任务规划引擎。

你的职责是将用户的意图拆解为具体的、可执行的步骤列表。

输出格式要求（严格 JSON）：
{{
    "intent_summary": "对用户意图的简要描述",
    "steps": [
        {{
            "action": "动作描述",
            "tool": "使用的工具名称",
            "params": {{"key": "value"}},
            "depends_on": []
        }}
    ],
    "priority": 5,
    "need_clarification": false,
    "clarification_question": ""
}}

当前可用工具列表：
{tool_list}

注意：
1. 每个步骤应该是原子性的，只做一件事
2. depends_on 填写前置步骤的序号（从0开始）
3. 如果用户意图不明确，设置 need_clarification=true 并提问
4. priority 范围 0-20，默认 5
5. 只能使用上面列出的工具，不要使用未列出的工具
"""


class Planner:
    """任务规划器。

    支持动态注册工具描述，使生成的计划只使用已注册的工具。
    如果没有注册任何工具描述，则使用默认的完整工具列表。

    Usage::

        planner = Planner(llm_client)
        planner.register_tool("system_control", "文件操作、进程管理")
        planner.register_tool("code_dev", "代码生成、调试")
        plan = await planner.plan("帮我写个脚本")
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm
        self._tool_descriptions: dict[str, str] = {}

    def register_tool(self, name: str, description: str) -> None:
        """注册工具描述，供规划时参考。

        Args:
            name: 工具名称（与 Executor 中注册的名称一致）
            description: 工具功能简述
        """
        self._tool_descriptions[name] = description
        logger.debug(f"规划器注册工具描述: {name}")

    def unregister_tool(self, name: str) -> None:
        """移除工具描述。"""
        self._tool_descriptions.pop(name, None)

    @property
    def registered_tools(self) -> list[str]:
        """已注册的工具名称列表。"""
        return list(self._tool_descriptions.keys())

    def _build_system_prompt(self) -> str:
        """构建包含当前可用工具的系统提示。"""
        # 如果有注册的工具描述，使用它们；否则使用默认列表
        if self._tool_descriptions:
            tool_lines = [
                f"- {name}: {desc}"
                for name, desc in self._tool_descriptions.items()
            ]
        else:
            tool_lines = [
                f"- {name}: {desc}"
                for name, desc in _DEFAULT_TOOL_DESCRIPTIONS.items()
            ]

        tool_list = "\n".join(tool_lines)
        return _PLANNER_PROMPT_TEMPLATE.format(tool_list=tool_list)

    async def plan(self, user_intent: str, context: str = "") -> TaskPlan:
        """将用户意图拆解为任务计划。

        Args:
            user_intent: 用户的原始意图描述
            context: 上下文信息（记忆、历史等）

        Returns:
            解析后的任务计划
        """
        logger.info(f"规划任务: {user_intent[:100]}...")

        prompt = f"用户意图: {user_intent}\n"
        if context:
            prompt += f"\n上下文:\n{context}\n"
        prompt += "\n请输出任务计划的 JSON。"

        response = await self._llm.chat_with_system(
            system_prompt=self._build_system_prompt(),
            user_message=prompt,
        )

        plan = self._parse_plan(response, user_intent)
        logger.info(f"规划完成: {len(plan.steps)} 个步骤")
        return plan

    async def replan(self, original: TaskPlan, reason: str) -> TaskPlan:
        """根据反思结果重新规划。

        Args:
            original: 原始计划
            reason: 重新规划的原因

        Returns:
            调整后的新计划
        """
        logger.info(f"重新规划任务 {original.id}: {reason[:100]}...")

        prompt = (
            f"原始意图: {original.intent}\n"
            f"已完成步骤: {json.dumps([{'action': s.action, 'status': s.status.value} for s in original.steps], ensure_ascii=False)}\n"
            f"重新规划原因: {reason}\n"
            f"请输出调整后的任务计划 JSON。"
        )

        response = await self._llm.chat_with_system(
            system_prompt=self._build_system_prompt(),
            user_message=prompt,
        )

        new_plan = self._parse_plan(response, original.intent)
        new_plan.parent_id = original.id
        return new_plan

    @staticmethod
    def _detect_circular_dependency(steps: list[Step]) -> None:
        """检测步骤间的循环依赖，发现环时抛出 ValueError。

        使用 DFS 三色标记法，时间复杂度 O(V+E)。
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        step_ids = {s.id for s in steps}
        adj: dict[str, list[str]] = {s.id: [] for s in steps}
        for s in steps:
            for dep in s.depends_on:
                if dep in step_ids:
                    adj[dep].append(s.id)

        color: dict[str, int] = {sid: WHITE for sid in step_ids}
        path: list[str] = []

        def dfs(node: str) -> None:
            color[node] = GRAY
            path.append(node)
            for neighbor in adj[node]:
                if color[neighbor] == GRAY:
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    raise ValueError(
                        f"检测到循环依赖: {' -> '.join(cycle)}"
                    )
                if color[neighbor] == WHITE:
                    dfs(neighbor)
            path.pop()
            color[node] = BLACK

        for sid in step_ids:
            if color[sid] == WHITE:
                dfs(sid)

    def _parse_plan(self, llm_response: str, original_intent: str) -> TaskPlan:
        """解析 LLM 返回的 JSON 为 TaskPlan。"""
        try:
            # 尝试提取 JSON 块
            text = llm_response.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            data: dict[str, Any] = json.loads(text)
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning(f"LLM 返回非 JSON 格式，创建单步计划: {e}")
            # 回退到第一个可用工具或 shell
            fallback_tool = (
                self._tool_descriptions.keys().__iter__().__next__()
                if self._tool_descriptions
                else "shell"
            )
            data = {
                "steps": [{"action": original_intent, "tool": fallback_tool, "params": {}}],
                "priority": 5,
            }

        steps = []
        for i, s in enumerate(data.get("steps", [])):
            step = Step(
                id=f"step_{i}",
                action=s.get("action", ""),
                tool=s.get("tool", "shell"),
                params=s.get("params", {}),
                depends_on=[f"step_{d}" for d in s.get("depends_on", [])],
            )
            steps.append(step)

        priority_val = data.get("priority", 5)
        try:
            priority = Priority(priority_val)
        except ValueError:
            priority = Priority.NORMAL

        # 检测循环依赖
        if steps:
            self._detect_circular_dependency(steps)

        return TaskPlan(
            id=f"plan_{uuid.uuid4().hex[:8]}",
            intent=data.get("intent_summary", original_intent),
            steps=steps,
            priority=priority,
        )
