"""基础 Agent 类。

实现感知→规划→执行→反馈的核心循环。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

from src.core.decider import Decider
from src.core.executor import Executor
from src.core.models import TaskPlan
from src.core.planner import Planner
from src.core.scheduler import Scheduler
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from src.perception.screen_analyzer import ScreenAnalyzer
from src.platforms.base import PlatformAdapter
from src.utils.config import AppConfig
from src.utils.llm_client import LLMClient


class PendingAction(str, Enum):
    """待处理的用户反馈动作类型。"""

    CONFIRM = "confirm"       # 用户确认执行之前被暂停的计划
    CANCEL = "cancel"         # 用户取消执行
    REPLAN = "replan"         # 用户要求重新规划
    NONE = "none"             # 无待处理动作


@dataclass
class PendingDecision:
    """等待用户反馈的决策上下文。

    当 Decider 判定需要询问人类时，保存完整上下文以便后续处理反馈。
    """

    plan: TaskPlan
    question: str
    confidence: float
    screen_context: str = ""


class BaseAgent:
    """JavasAgent 基础 Agent。

    核心循环：
    1. 感知：接收用户输入
    2. 规划：将意图拆解为步骤
    3. 决策：判断是否需要询问人类
    4. 执行：按步骤执行
    5. 反馈：报告执行结果

    支持反馈循环：当需要人类确认或执行失败时，通过 ``feedback()`` 继续。
    """

    # 用户确认的关键词映射
    _CONFIRM_KEYWORDS: frozenset[str] = frozenset({
        "确认", "确定", "是的", "好的", "可以", "执行吧",
        "yes", "ok", "sure", "go", "do it", "y",
    })
    _CANCEL_KEYWORDS: frozenset[str] = frozenset({
        "取消", "算了", "不要了", "停", "放弃",
        "cancel", "no", "stop", "abort", "n",
    })

    def __init__(
        self,
        config: AppConfig,
        platform: PlatformAdapter | None = None,
    ) -> None:
        self._config = config
        self._llm = LLMClient(config.llm)
        self._planner = Planner(self._llm)
        self._executor = Executor()
        self._decider = Decider(config.agent)
        self._scheduler = Scheduler()
        self._memory = ShortTermMemory(config.memory.short_term_max_messages)
        self._long_term_memory = LongTermMemory(config.memory)
        self._screen_analyzer = ScreenAnalyzer(self._llm, config.perception)
        self._platform = platform

        self._running = False

        # 反馈循环状态
        self._pending: PendingDecision | None = None
        self._last_failed_plan: TaskPlan | None = None

    # 屏幕操作相关的关键词
    _SCREEN_KEYWORDS: tuple[str, ...] = (
        "屏幕", "截图", "截屏", "画面", "桌面", "窗口",
        "点击", "按钮", "输入", "图标", "菜单",
        "界面", "UI", "打开", "关闭",
    )

    async def process(self, user_input: str) -> str:
        """处理用户输入（核心入口）。

        如果存在待确认的决策，会优先检查用户输入是否为对上次询问的回复。
        否则按正常流程：感知→规划→决策→执行→反馈。

        Args:
            user_input: 用户的自然语言指令

        Returns:
            处理结果或回复
        """
        logger.info(f"收到用户输入: {user_input[:100]}...")
        self._memory.add("user", user_input)

        # 0. 反馈循环：如果有待确认的决策，优先处理
        if self._pending is not None:
            response = await self._handle_pending_feedback(user_input)
            if response is not None:
                return response
            # 用户输入不是反馈，继续走正常流程

        # 1. 屏幕感知：如果任务涉及屏幕操作，先截屏分析上下文
        screen_context = ""
        if self._is_screen_related(user_input):
            screen_context = await self._analyze_screen_if_available()

        # 2. 规划（使用包含长期记忆检索的上下文）
        context = await self._build_context_with_recall(user_input)
        if screen_context:
            context += f"\n\n屏幕感知:\n{screen_context}"
        plan = await self._planner.plan(user_input, context)

        # 3. 决策检查（基于计划复杂度估算 confidence）
        confidence = self._estimate_confidence(plan, user_input)
        decision = self._decider.evaluate(
            context=user_input,
            question=plan.intent,
            confidence=confidence,
        )

        if not decision.auto_decided:
            # 保存待确认的决策上下文，等用户反馈
            self._pending = PendingDecision(
                plan=plan,
                question=decision.question,
                confidence=confidence,
                screen_context=screen_context,
            )
            response = (
                f"⚠️ 需要确认：{decision.question}\n"
                f"计划包含 {len(plan.steps)} 个步骤。回复「确认」执行，回复「取消」放弃，"
                f"或描述你想要的调整。"
            )
            self._memory.add("assistant", response)
            return response

        # 4. 提交并执行
        return await self._execute_plan(plan)

    async def feedback(self, user_response: str) -> str:
        """对上一次需要确认或执行失败的决策提供反馈。

        这是对 ``process()`` 的补充入口，专为交互式场景设计。
        如果当前没有待处理的状态，会回退到普通 ``process()``。

        Args:
            user_response: 用户的反馈内容

        Returns:
            处理结果或回复
        """
        return await self.process(user_response)

    async def _handle_pending_feedback(self, user_input: str) -> str | None:
        """处理用户对上次待确认决策的反馈。

        Args:
            user_input: 用户输入

        Returns:
            回复字符串（如果匹配反馈模式），否则返回 None 表示走正常流程
        """
        pending = self._pending
        self._pending = None  # 清除待处理状态

        action = self._classify_feedback(user_input)

        if action == PendingAction.CONFIRM:
            logger.info("用户确认执行计划")
            return await self._execute_plan(pending.plan)

        if action == PendingAction.CANCEL:
            response = "🚫 已取消任务。"
            self._memory.add("assistant", response)
            return response

        if action == PendingAction.REPLAN:
            logger.info("用户要求重新规划")
            reason = f"用户反馈：{user_input}"
            try:
                new_plan = await self._planner.replan(pending.plan, reason)
                response = (
                    f"📋 已重新规划（{len(new_plan.steps)} 步）：{new_plan.intent}\n"
                    f"回复「确认」执行新计划。"
                )
                self._pending = PendingDecision(
                    plan=new_plan,
                    question=new_plan.intent,
                    confidence=pending.confidence,
                    screen_context=pending.screen_context,
                )
            except Exception as e:
                logger.error(f"重新规划失败: {e}")
                response = f"❌ 重新规划失败: {e}"
            self._memory.add("assistant", response)
            return response

        # 未匹配任何反馈模式，说明用户开始了新对话
        # 恢复 pending 状态... 其实不需要，用户已经转向了
        return None

    async def _execute_plan(self, plan: TaskPlan) -> str:
        """提交并执行任务计划，返回结果回复。"""
        task_id = await self._scheduler.submit(plan)
        self._scheduler.mark_running(plan)

        try:
            result = await self._executor.execute(plan)
        except Exception as e:
            logger.error(f"执行异常: {e}")
            result = None
        finally:
            self._scheduler.mark_done(plan, result.success if result else False)

        if result is None:
            response = f"❌ 执行发生异常，请重试。目标: {plan.intent}"
            self._last_failed_plan = plan
        elif result.success:
            response = (
                f"✅ 任务完成 ({result.completed_steps}/{result.total_steps} 步)\n"
                f"目标: {plan.intent}"
            )
            self._last_failed_plan = None
        else:
            errors_str = "; ".join(result.errors)
            self._last_failed_plan = plan
            response = (
                f"❌ 任务执行出现问题:\n{errors_str}\n\n"
                f"回复「重试」重新执行，或描述如何调整。"
            )

        self._memory.add("assistant", response)
        return response

    def _classify_feedback(self, user_input: str) -> PendingAction:
        """将用户输入分类为反馈动作。

        Args:
            user_input: 用户输入文本

        Returns:
            对应的 PendingAction 枚举值
        """
        text = user_input.strip().lower()

        if text in self._CONFIRM_KEYWORDS:
            return PendingAction.CONFIRM

        if text in self._CANCEL_KEYWORDS:
            return PendingAction.CANCEL

        # 包含重试/重新规划意图的关键词
        replan_keywords = {"重试", "重新", "换", "调整", "retry", "replan", "redo", "change", "adjust"}
        if any(kw in text for kw in replan_keywords):
            return PendingAction.REPLAN

        return PendingAction.NONE

    def register_tool(self, name: str, tool: Any) -> None:
        """注册工具到执行引擎。"""
        self._executor.register_tool(name, tool)

    async def analyze_screen(self, screenshot: bytes) -> str:
        """分析屏幕截图。

        公开方法，供外部直接调用进行屏幕分析。

        Args:
            screenshot: PNG 格式的截图 bytes

        Returns:
            屏幕内容描述文本
        """
        return await self._screen_analyzer.describe(screenshot)

    async def initialize_memory(self) -> None:
        """初始化长期记忆（ChromaDB）。

        需要在 Agent 首次使用前调用，初始化持久化存储。
        如果 ChromaDB 不可用，会优雅降级。
        """
        await self._long_term_memory.initialize()
        logger.info(f"长期记忆初始化完成: {self._long_term_memory.count} 条已有记录")

    async def remember(self, content: str, category: str = "experience", **metadata: Any) -> str | None:
        """将信息存入长期记忆。

        Args:
            content: 要记忆的内容
            category: 分类（experience / knowledge / preference / skill）
            **metadata: 附加元数据

        Returns:
            记忆条目 ID，失败返回 None
        """
        return await self._long_term_memory.store(content, category=category, metadata=metadata)

    async def recall(self, query: str, top_k: int = 5, category: str | None = None) -> list:
        """从长期记忆中检索相关信息。

        Args:
            query: 查询文本
            top_k: 返回最多 K 条结果
            category: 限定分类

        Returns:
            记忆条目列表
        """
        return await self._long_term_memory.recall(query, top_k=top_k, category=category)

    def _is_screen_related(self, user_input: str) -> bool:
        """判断用户输入是否涉及屏幕操作。"""
        return any(kw in user_input for kw in self._SCREEN_KEYWORDS)

    async def _analyze_screen_if_available(self) -> str:
        """尝试截屏并分析，失败则返回空字符串。

        需要平台适配器提供截屏能力。当前仅在有平台适配器时生效。
        """
        if self._platform is None:
            logger.debug("屏幕分析跳过: 无平台适配器")
            return ""

        try:
            screenshot_bytes = await self._platform.screenshot()
            description = await self._screen_analyzer.describe(screenshot_bytes)
            logger.info("屏幕分析完成")
            return description
        except Exception as e:
            logger.warning(f"屏幕分析失败: {e}")
            return ""

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
        """构建当前上下文信息。

        注意：此方法是同步的，不包含长期记忆语义检索。
        长期记忆的语义检索应在 ``process()`` 中异步调用后注入 context。
        """
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

        # 添加长期记忆统计信息
        ltm_count = self._long_term_memory.count
        if ltm_count > 0:
            parts.append(f"\n长期记忆: {ltm_count} 条记录")

        return "\n".join(parts)

    async def _build_context_with_recall(self, user_input: str) -> str:
        """构建包含长期记忆语义检索的上下文。

        基于 ``_build_context()`` 的基础上，额外从长期记忆中检索
        与当前用户输入相关的历史经验，丰富上下文信息。

        Args:
            user_input: 当前用户输入

        Returns:
            包含长期记忆检索结果的完整上下文
        """
        context = self._build_context()

        # 从长期记忆检索相关经验
        if self._long_term_memory.is_available and user_input.strip():
            try:
                memories = await self._long_term_memory.recall(
                    user_input, top_k=3, category=None
                )
                if memories:
                    memory_parts = []
                    for mem in memories:
                        memory_parts.append(
                            f"  [{mem.category}] {mem.content[:150]}"
                        )
                    context += "\n\n相关历史记忆:\n" + "\n".join(memory_parts)
            except Exception as e:
                logger.debug(f"长期记忆检索跳过: {e}")

        return context

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
            "long_term_memory_count": self._long_term_memory.count,
            "pending_decision": self._pending is not None,
        }
