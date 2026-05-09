"""反馈循环处理模块。

将 BaseAgent 中的反馈分类、待确认决策管理抽取为独立函数，
降低 base_agent.py 的文件体积。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

from src.core.models import PlanStatus, StepStatus

if TYPE_CHECKING:
    from src.agents.base_agent import BaseAgent


class PendingAction(str, Enum):
    """待处理的用户反馈动作类型。"""

    CONFIRM = "confirm"       # 用户确认执行之前被暂停的计划
    CANCEL = "cancel"         # 用户取消执行
    REPLAN = "replan"         # 用户要求重新规划
    RETRY = "retry"           # 用户要求重试失败的任务
    NONE = "none"             # 无待处理动作


@dataclass
class PendingDecision:
    """等待用户反馈的决策上下文。

    当 Decider 判定需要询问人类时，保存完整上下文以便后续处理反馈。
    """

    plan: "TaskPlan"  # noqa: F821
    question: str
    confidence: float
    screen_context: str = ""


# 用户确认的关键词映射
CONFIRM_KEYWORDS: frozenset[str] = frozenset({
    "确认", "确定", "是的", "好的", "可以", "执行吧",
    "yes", "ok", "sure", "go", "do it", "y",
})

# 用户取消的关键词映射
CANCEL_KEYWORDS: frozenset[str] = frozenset({
    "取消", "算了", "不要了", "停", "放弃",
    "cancel", "no", "stop", "abort", "n",
})

# 屏幕操作相关的关键词
SCREEN_KEYWORDS: tuple[str, ...] = (
    "屏幕", "截图", "截屏", "画面", "桌面", "窗口",
    "点击", "按钮", "输入", "图标", "菜单",
    "界面", "UI", "打开", "关闭",
)


def classify_feedback(
    user_input: str,
    confirm_keywords: frozenset[str] | None = None,
    cancel_keywords: frozenset[str] | None = None,
) -> PendingAction:
    """将用户输入分类为反馈动作。

    Args:
        user_input: 用户输入文本
        confirm_keywords: 确认关键词集合，默认使用 CONFIRM_KEYWORDS
        cancel_keywords: 取消关键词集合，默认使用 CANCEL_KEYWORDS

    Returns:
        对应的 PendingAction 枚举值
    """
    if confirm_keywords is None:
        confirm_keywords = CONFIRM_KEYWORDS
    if cancel_keywords is None:
        cancel_keywords = CANCEL_KEYWORDS

    text = user_input.strip().lower()

    if text in confirm_keywords:
        return PendingAction.CONFIRM

    if text in cancel_keywords:
        return PendingAction.CANCEL

    # 重试关键词（优先于 replan，因为"重试"是更明确的意图）
    retry_keywords = {"重试", "retry", "again", "redo"}
    if any(kw in text for kw in retry_keywords):
        return PendingAction.RETRY

    # 包含重试/重新规划意图的关键词
    replan_keywords = {"重新", "换", "调整", "replan", "change", "adjust"}
    if any(kw in text for kw in replan_keywords):
        return PendingAction.REPLAN

    return PendingAction.NONE


async def handle_pending_feedback(agent: BaseAgent, user_input: str) -> str | None:
    """处理用户对上次待确认决策的反馈。

    同时处理对失败任务的重试请求。

    Args:
        agent: BaseAgent 实例（用于访问状态和调用方法）
        user_input: 用户输入

    Returns:
        回复字符串（如果匹配反馈模式），否则返回 None 表示走正常流程
    """
    action = classify_feedback(user_input)

    # 优先处理失败任务的重试
    if action == PendingAction.RETRY and agent._last_failed_plan is not None:
        failed = agent._last_failed_plan
        agent._last_failed_plan = None
        logger.info(f"用户要求重试失败任务: {failed.intent}")
        # 重置所有步骤状态，以便重新执行
        for step in failed.steps:
            step.status = StepStatus.PENDING
            step.retry_count = 0
            step.result = None
            step.error = None
        failed.status = PlanStatus.PENDING
        return await agent._execute_plan(failed)

    if agent._pending is not None:
        pending = agent._pending
        agent._pending = None  # 清除待处理状态

        if action == PendingAction.CONFIRM:
            logger.info("用户确认执行计划")
            return await agent._execute_plan(pending.plan)

        if action == PendingAction.CANCEL:
            response = "🚫 已取消任务。"
            agent._memory.add("assistant", response)
            return response

        if action == PendingAction.REPLAN:
            logger.info("用户要求重新规划")
            reason = f"用户反馈：{user_input}"
            try:
                new_plan = await agent._planner.replan(pending.plan, reason)
                response = (
                    f"📋 已重新规划（{len(new_plan.steps)} 步）：{new_plan.intent}\n"
                    f"回复「确认」执行新计划。"
                )
                agent._pending = PendingDecision(
                    plan=new_plan,
                    question=new_plan.intent,
                    confidence=pending.confidence,
                    screen_context=pending.screen_context,
                )
            except Exception as e:
                logger.error(f"重新规划失败: {e}")
                response = f"❌ 重新规划失败: {e}"
            agent._memory.add("assistant", response)
            return response

        # 未匹配任何反馈模式，说明用户开始了新对话
        return None

    return None
