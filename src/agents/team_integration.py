"""AgentTeam 与 BaseAgent 的桥接层。

提供 TeamIntegrationMixin，封装多 Agent 协作的初始化、任务委派、
进度监控和结果聚合逻辑。通过 Mixin 方式注入 BaseAgent，
确保单 Agent 模式完全不受影响。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from src.core.agent_team import AgentTeam
from src.core.task_distributor import TaskDistributor
from src.utils.config import TeamConfig

if TYPE_CHECKING:
    from src.core.models import TaskPlan


class TeamIntegrationMixin:
    """AgentTeam 与 BaseAgent 的桥接层。

    通过 Mixin 注入 BaseAgent，提供多 Agent 协作能力。
    当配置中 team.enabled=False 时，所有方法均为空操作，
    不影响现有单 Agent 模式。

    使用方式::

        class BaseAgent(TeamIntegrationMixin):
            def __init__(self, config, ...):
                ...
                self._init_team_integration(config)
    """

    # ------------------------------------------------------------------
    # 内部状态（由 __init_team_integration 初始化）
    # ------------------------------------------------------------------

    _team: AgentTeam | None
    _task_distributor: TaskDistributor | None
    _team_enabled: bool
    _delegation_threshold: int
    _delegated_task_ids: list[str]

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _init_team_integration(self, config: Any) -> None:
        """初始化多 Agent 团队集成。

        根据配置决定是否启用团队模式。当 team.enabled=False 时，
        仅设置标志位，不创建任何团队实例。

        Args:
            config: AppConfig 实例，需包含 team 字段
        """
        team_cfg: TeamConfig = getattr(config, "team", None) or TeamConfig()

        self._team_enabled: bool = team_cfg.enabled
        self._delegation_threshold: int = team_cfg.delegation_threshold
        self._delegated_task_ids: list[str] = []

        if not self._team_enabled:
            self._team = None
            self._task_distributor = None
            logger.debug("多 Agent 模式未启用")
            return

        self._team = AgentTeam(
            name=team_cfg.name,
            coordinator_config={},
        )
        self._task_distributor = TaskDistributor()
        logger.info(
            f"多 Agent 团队已初始化: '{team_cfg.name}', "
            f"委派阈值={team_cfg.delegation_threshold} 步, "
            f"最大工作 Agent={team_cfg.max_workers}"
        )

    # ------------------------------------------------------------------
    # 判断与委派
    # ------------------------------------------------------------------

    async def should_delegate(self, plan: TaskPlan) -> bool:
        """判断任务计划是否需要委派给子 Agent。

        判断依据：
        1. 多 Agent 模式必须已启用
        2. 团队必须有可用成员
        3. 计划步骤数必须超过配置的委派阈值

        Args:
            plan: 已生成的任务计划

        Returns:
            True 表示应该委派子任务
        """
        if not self._team_enabled or self._team is None:
            return False

        if self._team.member_count == 0:
            logger.debug("团队中无成员，跳过委派")
            return False

        step_count = len(plan.steps)
        if step_count <= self._delegation_threshold:
            logger.debug(f"步骤数 ({step_count}) 未超过阈值 ({self._delegation_threshold})，跳过委派")
            return False

        logger.info(f"步骤数 ({step_count}) 超过阈值 ({self._delegation_threshold})，建议委派")
        return True

    async def delegate_subtask(
        self,
        description: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """将子任务委派给团队中最合适的 Agent。

        使用 TaskDistributor 分析任务描述，自动匹配最合适的 Agent。
        如果团队不可用或分配失败，返回错误描述字符串。

        Args:
            description: 子任务描述
            context: 可选的附加上下文信息（当前未使用，预留扩展）

        Returns:
            任务分配 ID，失败时返回空字符串
        """
        if not self._team_enabled or self._team is None:
            logger.warning("多 Agent 模式未启用，无法委派子任务")
            return ""

        if self._task_distributor is not None:
            results = await self._task_distributor.distribute(description, self._team)
            if results and results[0].get("success"):
                assignment_id = results[0].get("assignment_id", "")
                if assignment_id:
                    self._delegated_task_ids.append(assignment_id)
                    logger.info(f"子任务已委派: {assignment_id}")
                    return assignment_id
            logger.warning(f"子任务委派失败: {results}")
            return ""

        # 回退：直接使用 AgentTeam.assign_task
        result = await self._team.assign_task(description)
        if result.get("success"):
            assignment_id = result.get("assignment_id", "")
            if assignment_id:
                self._delegated_task_ids.append(assignment_id)
                logger.info(f"子任务已直接分配: {assignment_id}")
                return assignment_id
        return ""

    async def delegate_task(
        self,
        task_description: str,
        agent_role: str = "worker",
    ) -> str:
        """将子任务委派给指定角色的子 Agent（BaseAgent 公开接口）。

        在团队中查找具有指定角色的 Agent，将任务分配给它。
        如果没有匹配角色的 Agent，则自动选择空闲 Agent。

        Args:
            task_description: 任务描述
            agent_role: 目标 Agent 角色，默认 "worker"

        Returns:
            任务分配 ID，失败时返回空字符串
        """
        if not self._team_enabled or self._team is None:
            logger.warning("多 Agent 模式未启用，delegate_task 不可用")
            return ""

        # 查找匹配角色的 Agent
        preferred_agent: str | None = None
        members = self._team.list_members()
        for m in members:
            if m.get("role") == agent_role and m.get("status") == "idle":
                preferred_agent = m.get("agent_id")
                break

        result = await self._team.assign_task(task_description, preferred_agent=preferred_agent)
        if result.get("success"):
            assignment_id = result.get("assignment_id", "")
            if assignment_id:
                self._delegated_task_ids.append(assignment_id)
                logger.info(
                    f"任务已委派给角色 '{agent_role}': "
                    f"agent={result.get('agent_id')}, assignment={assignment_id}"
                )
                return assignment_id

        logger.warning(f"任务委派失败 (role={agent_role}): {result}")
        return ""

    # ------------------------------------------------------------------
    # 监控与聚合
    # ------------------------------------------------------------------

    async def monitor_progress(self) -> dict[str, Any]:
        """获取多 Agent 团队的当前执行进度。

        Returns:
            包含团队状态和各成员进度的字典。
            如果团队未启用，返回空字典。
        """
        if not self._team_enabled or self._team is None:
            return {}

        team_status = await self._team.get_team_status()
        delegated_count = len(self._delegated_task_ids)

        progress = {
            **team_status,
            "delegated_tasks": delegated_count,
        }

        logger.debug(f"团队进度: {team_status.get('busy_members', 0)} 忙碌, "
                      f"{team_status.get('idle_members', 0)} 空闲, "
                      f"{delegated_count} 已委派")
        return progress

    async def aggregate_results(self, task_ids: list[str]) -> dict[str, Any]:
        """聚合指定任务的执行结果。

        遍历任务 ID 列表，从团队分配记录中查找对应结果，
        合并为统一的汇总报告。

        Args:
            task_ids: 要聚合的任务分配 ID 列表

        Returns:
            包含总体状态、成功数、失败数和详细结果的字典
        """
        if not self._team_enabled or self._team is None:
            return {"success": False, "error": "团队未启用", "results": []}

        results: list[dict[str, Any]] = []
        for tid in task_ids:
            # 在团队分配记录中查找
            assignment = None
            for a in self._team._assignments:
                if a.id == tid:
                    assignment = a
                    break

            if assignment is None:
                results.append({"task_id": tid, "status": "not_found"})
                continue

            results.append({
                "task_id": tid,
                "agent_id": assignment.agent_id,
                "status": assignment.status,
                "result": assignment.result,
                "task": assignment.task,
            })

        successful = sum(1 for r in results if r.get("status") == "done")
        total = len(results)

        aggregated = {
            "success": successful == total,
            "total": total,
            "successful": successful,
            "failed": total - successful,
            "results": results,
        }

        logger.info(f"结果聚合: {successful}/{total} 成功")
        return aggregated

    async def collect_all_results(self) -> list[dict[str, Any]]:
        """收集所有已委派任务的执行结果。

        Returns:
            所有已委派任务的结果列表。
            如果团队未启用，返回空列表。
        """
        if not self._team_enabled or self._team is None:
            return []

        results: list[dict[str, Any]] = []
        for assignment in self._team._assignments:
            results.append({
                "assignment_id": assignment.id,
                "agent_id": assignment.agent_id,
                "task": assignment.task,
                "status": assignment.status,
                "result": assignment.result,
            })

        logger.info(f"收集全部结果: {len(results)} 条")
        return results

    def get_team_status(self) -> dict[str, Any]:
        """获取多 Agent 团队状态（同步方法）。

        Returns:
            团队状态字典。包含团队名称、成员数、已委派任务数等信息。
            如果团队未启用，返回 {"enabled": False}。
        """
        if not self._team_enabled or self._team is None:
            return {"enabled": False, "reason": "多 Agent 模式未启用"}

        members = self._team.list_members()
        return {
            "enabled": True,
            "team_name": self._team.name,
            "total_members": len(members),
            "members": members,
            "delegated_tasks": len(self._delegated_task_ids),
        }
