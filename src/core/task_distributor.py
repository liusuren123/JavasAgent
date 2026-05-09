"""智能任务分发器。

根据任务描述分析所需能力，自动匹配最合适的 agent 执行。
支持任务拆分和结果合并。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from src.core.agent_team import AgentTeam

# 关键词 -> 推荐能力映射
_KEYWORD_CAPABILITY_MAP: dict[str, list[str]] = {
    "代码": ["code", "programming"],
    "编程": ["code", "programming"],
    "搜索": ["search", "web"],
    "查询": ["search", "web"],
    "文件": ["file", "system"],
    "系统": ["system", "os"],
    "浏览器": ["browser", "web"],
    "分析": ["analysis", "data"],
    "数据": ["data", "analysis"],
    "邮件": ["email"],
    "图片": ["image", "media"],
    "视频": ["video", "media"],
    "文档": ["document", "office"],
    "测试": ["code", "testing"],
}


class TaskDistributor:
    """智能任务分发器。

    根据任务描述分析所需能力，自动匹配最合适的 agent 执行。
    支持任务拆分（将大任务按关键词拆分为子任务）和结果合并。
    """

    def __init__(self, llm_client: Any | None = None) -> None:
        """初始化分发器。

        Args:
            llm_client: 可选的 LLM 客户端，用于复杂任务分析
        """
        self._llm_client = llm_client
        self._keyword_map = _KEYWORD_CAPABILITY_MAP.copy()

    def _infer_required_capabilities(self, task: str) -> list[str]:
        """从任务描述推断所需能力。

        Args:
            task: 任务描述

        Returns:
            推断出的能力列表
        """
        capabilities: set[str] = set()
        for keyword, caps in self._keyword_map.items():
            if keyword in task:
                capabilities.update(caps)
        # 如果没有匹配到任何能力，返回通用能力
        return list(capabilities) if capabilities else ["general"]

    def _split_task(self, task: str) -> list[str]:
        """尝试拆分复合任务。

        简单策略：按句号/分号拆分，过滤过短的子句。
        如果拆分后只有一条或零条，则不拆分。

        Args:
            task: 原始任务描述

        Returns:
            子任务列表
        """
        import re

        parts = re.split(r"[。；;\n]", task)
        parts = [p.strip() for p in parts if len(p.strip()) > 2]

        return parts if len(parts) > 1 else [task]

    async def distribute(self, task: str, team: AgentTeam) -> list[dict[str, Any]]:
        """分析任务并分发给团队成员。

        工作流程:
        1. 推断任务所需能力
        2. 尝试拆分复合任务
        3. 为每个子任务匹配最合适的 agent
        4. 并行分发并收集结果

        Args:
            task: 任务描述
            team: 目标团队

        Returns:
            分发结果列表，每项包含 agent_id、subtask、status 等
        """
        required_caps = self._infer_required_capabilities(task)
        subtasks = self._split_task(task)

        logger.info(
            f"任务分发: {len(subtasks)} 个子任务, 所需能力: {required_caps}"
        )

        results: list[dict[str, Any]] = []
        members = team.list_members()

        if not members:
            logger.warning("团队中没有成员，无法分发任务")
            return [{"success": False, "error": "团队中没有成员", "subtask": task}]

        for idx, subtask in enumerate(subtasks):
            # 匹配最佳 agent
            best_agent = self._find_best_agent(
                members, self._infer_required_capabilities(subtask)
            )

            if best_agent is None:
                results.append({
                    "success": False,
                    "error": "没有匹配的 agent",
                    "subtask": subtask,
                    "subtask_index": idx,
                })
                continue

            # 分配任务
            assign_result = await team.assign_task(subtask, preferred_agent=best_agent)

            results.append({
                "success": assign_result.get("success", False),
                "assignment_id": assign_result.get("assignment_id"),
                "agent_id": assign_result.get("agent_id", best_agent),
                "subtask": subtask,
                "subtask_index": idx,
                "status": "assigned",
            })

            logger.info(
                f"子任务 {idx} 已分配给 agent {best_agent}: {subtask[:50]}"
            )

        return results

    def _find_best_agent(
        self, members: list[dict[str, Any]], required_caps: list[str]
    ) -> str | None:
        """根据能力需求找到最佳 agent。

        优先选择能力匹配度最高且空闲的 agent。

        Args:
            members: 成员信息列表
            required_caps: 所需能力列表

        Returns:
            最佳 agent ID 或 None
        """
        best_id: str | None = None
        best_score = -1.0

        for m in members:
            caps = m.get("capabilities", [])
            if not required_caps:
                score = 1.0
            else:
                matched = sum(
                    1 for r in required_caps
                    if any(r.lower() in c.lower() for c in caps)
                )
                score = matched / len(required_caps)

            # 空闲 agent 加权
            if m.get("status") == "idle":
                score += 0.1

            if score > best_score:
                best_score = score
                best_id = m.get("agent_id")

        return best_id

    async def merge_results(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """合并多个 agent 的执行结果。

        Args:
            results: 各 agent 的执行结果列表

        Returns:
            合并后的结果，包含总体状态、汇总信息等
        """
        if not results:
            return {"success": False, "error": "没有结果可合并", "summary": ""}

        total = len(results)
        successful = sum(1 for r in results if r.get("success"))
        failed = total - successful

        # 收集各 agent 的输出
        outputs: list[str] = []
        errors: list[str] = []

        for r in results:
            if r.get("success"):
                agent_id = r.get("agent_id", "unknown")
                subtask = r.get("subtask", "")
                result_data = r.get("result", {})
                outputs.append(f"[{agent_id}] {subtask}: {result_data}")
            else:
                errors.append(r.get("error", "未知错误"))

        summary = "\n".join(outputs) if outputs else "所有子任务均失败"

        merged = {
            "success": failed == 0,
            "total_subtasks": total,
            "successful": successful,
            "failed": failed,
            "summary": summary,
            "outputs": outputs,
            "errors": errors,
        }

        logger.info(f"结果合并: {successful}/{total} 成功")
        return merged
