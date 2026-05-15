"""基础 Agent 类。

实现感知→规划→执行→反馈的核心循环。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.agents.feedback_handler import (
    CONFIRM_KEYWORDS,
    CANCEL_KEYWORDS,
    SCREEN_KEYWORDS,
    PendingAction,
    PendingDecision,
    classify_feedback,
    handle_pending_feedback,
)
from src.agents.learning_integration import LearningIntegration
from src.agents.team_integration import TeamIntegrationMixin
from src.core.decider import Decider
from src.core.executor import Executor
from src.core.models import ExecutionResult, PlanStatus, StepStatus, TaskPlan
from src.core.planner import Planner
from src.core.scheduler import Scheduler
from src.core.workflow_engine import WorkflowEngine
from src.memory.long_term import LongTermMemory
from src.memory.short_term import ShortTermMemory
from src.perception.screen_analyzer import ScreenAnalyzer
from src.perception.hybrid_detector import HybridDetector
from src.perception.ui_operator import UIAOperator
from src.platforms.base import PlatformAdapter
from src.tools.image_ops import ImageOps
from src.utils.config import AppConfig
from src.utils.llm_client import LLMClient


class BaseAgent(TeamIntegrationMixin):
    """JavasAgent 基础 Agent。

    核心循环：
    1. 感知：接收用户输入
    2. 规划：将意图拆解为步骤
    3. 决策：判断是否需要询问人类
    4. 执行：按步骤执行
    5. 反馈：报告执行结果

    支持反馈循环：当需要人类确认或执行失败时，通过 ``feedback()`` 继续。
    """

    # 向后兼容：保留类属性作为模块级常量的引用
    _CONFIRM_KEYWORDS: frozenset[str] = CONFIRM_KEYWORDS
    _CANCEL_KEYWORDS: frozenset[str] = CANCEL_KEYWORDS
    _SCREEN_KEYWORDS: tuple[str, ...] = SCREEN_KEYWORDS

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
        self._workflow_engine = WorkflowEngine()
        self._memory = ShortTermMemory(config.memory.short_term_max_messages)
        self._long_term_memory = LongTermMemory(config.memory)
        self._screen_analyzer = ScreenAnalyzer(self._llm, config.perception)
        self._ui_detector = HybridDetector()
        self._ui_operator = UIAOperator()
        self._platform = platform

        self._running = False

        # 反馈循环状态
        self._pending: PendingDecision | None = None
        self._last_failed_plan: TaskPlan | None = None

        # 技能学习集成
        self._learning = LearningIntegration(
            storage_dir=config.memory.long_term_db_path.replace("chroma", "learning"),
        )

        # 多 Agent 团队集成（通过 Mixin）
        self._init_team_integration(config)

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
            response = await handle_pending_feedback(self, user_input)
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

        # 2.5 技能学习：检查可复用技能
        try:
            skill_suggestions = await self._learning.on_planning_start(context)
            if skill_suggestions:
                names = [s.suggested_name for s in skill_suggestions]
                logger.info(f"发现可复用技能建议: {names}")
        except Exception as e:
            logger.warning(f"技能学习查询失败: {e}")

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

        # 3.5 多 Agent 委派检查：如果步骤数超过阈值且有可用团队成员，自动委派
        if await self.should_delegate(plan):
            logger.info(
                f"任务步骤数 ({len(plan.steps)}) 超过委派阈值，"
                f"建议将部分子任务委派给团队成员"
            )
            # 当前仍然执行主计划，委派逻辑通过 delegate_task 手动触发
            # 未来可以扩展为自动拆分并委派

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
        """处理用户对上次待确认决策的反馈（委托给 feedback_handler 模块）。"""
        return await handle_pending_feedback(self, user_input)

    async def _execute_plan(self, plan: TaskPlan) -> str:
        """提交并执行任务计划，返回结果回复。"""
        task_id = await self._scheduler.submit(plan)
        self._scheduler.mark_running(plan)
        self._running = True

        try:
            result = await self._executor.execute(plan)
        except Exception as e:
            logger.error(f"执行异常: {e}")
            result = None
        finally:
            self._scheduler.mark_done(plan, result.success if result else False)
            self._running = False

        # 技能学习：记录执行历史
        if result is not None:
            try:
                await self._learning.on_execution_complete(plan, result)
            except Exception as e:
                logger.warning(f"技能学习记录失败: {e}")

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
        """将用户输入分类为反馈动作（委托给 feedback_handler 模块）。"""
        return classify_feedback(user_input, self._CONFIRM_KEYWORDS, self._CANCEL_KEYWORDS)

    # 工具描述映射：注册名 → 默认描述
    _TOOL_DESCRIPTIONS: dict[str, str] = {
        "system_control": "文件操作、进程管理、窗口控制",
        "shell": "执行终端命令",
        "code_dev": "代码生成、调试、测试、Git 操作、依赖管理",
        "office_ops": "Word/Excel/PPT/PDF 文档操作",
        "browser_control": "浏览器自动化（打开网页、截图、填表）",
        "creative_tools": "创意工具（占位符）",
        "email_ops": "邮件收发、搜索、文件夹管理",
        "image_ops": "图片处理：裁剪、缩放、格式转换、水印、亮度对比度调整",
    }

    def register_tool(self, name: str, tool: Any, description: str | None = None) -> None:
        """注册工具到执行引擎和规划器。

        Args:
            name: 工具名称
            tool: 工具实例（必须实现 ``execute(action, params)`` 接口）
            description: 工具功能描述，供规划器参考。
                为 None 时使用内置描述表中的默认值。
        """
        self._executor.register_tool(name, tool)
        # 同步注册到规划器，使 LLM 只规划可用工具
        desc = description or self._TOOL_DESCRIPTIONS.get(name, "")
        if desc:
            self._planner.register_tool(name, desc)

        # 同步注册到工作流引擎，使工作流可调用该工具
        self._workflow_engine.register_tool(name, tool)

    async def run_workflow(
        self,
        workflow_name_or_id: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """执行已定义的工作流。

        Agent 可通过 LLM 决策调用此方法来执行多步骤工作流。

        Args:
            workflow_name_or_id: 工作流名称或 ID
            context: 模板变量上下文

        Returns:
            执行结果描述
        """
        result = await self._workflow_engine.run_workflow(workflow_name_or_id, context)

        if result.status.value == "success":
            return (
                f"✅ 工作流执行完成: {result.workflow_id}\n"
                f"状态: {result.status.value}, 耗时 {result.total_time:.2f}s"
            )
        elif result.status.value == "partial":
            skipped = sum(1 for r in result.step_results if r.skipped)
            return (
                f"⚠️ 工作流部分完成: {result.workflow_id}\n"
                f"跳过步骤: {skipped}, 耗时 {result.total_time:.2f}s"
            )
        else:
            return (
                f"❌ 工作流执行失败: {result.workflow_id}\n"
                f"错误: {result.error_summary}"
            )

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
        """初始化长期记忆（ChromaDB）和技能学习模块。

        需要在 Agent 首次使用前调用，初始化持久化存储。
        如果 ChromaDB 不可用，会优雅降级。
        """
        await self._long_term_memory.initialize()
        logger.info(f"长期记忆初始化完成: {self._long_term_memory.count} 条已有记录")
        await self._learning.initialize()
        logger.info(f"技能学习模块初始化完成: {self._learning.pattern_count} 个已有模式")

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
        if self._long_term_memory and self._long_term_memory.is_available and user_input.strip():
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

    async def close(self) -> None:
        """释放 Agent 持有的所有资源。

        关闭 LLM 连接池，清理工具资源，清理长期记忆引用。
        调用后 Agent 不再可用。
        """
        # 持久化技能学习数据
        try:
            await self._learning.save()
        except Exception as e:
            logger.warning(f"技能学习数据保存失败: {e}")

        if self._llm is not None:
            await self._llm.close()
            logger.info("LLM 连接池已关闭")

        # 清理可关闭的工具资源（如 BrowserControl）
        for tool_name, tool in self._executor._tool_registry.items():
            if hasattr(tool, "close") and callable(tool.close):
                try:
                    await tool.close()
                    logger.debug(f"工具资源已释放: {tool_name}")
                except Exception as e:
                    logger.warning(f"工具资源释放失败 ({tool_name}): {e}")

        # 清理长期记忆引用（ChromaDB 使用 PersistentClient，无需显式关闭）
        self._long_term_memory = None  # type: ignore[assignment]
        logger.info("Agent 资源已释放")

    async def __aenter__(self) -> BaseAgent:
        """异步上下文管理器入口。"""
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """异步上下文管理器出口，自动释放资源。"""
        await self.close()

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
            "workflow_engine": len(self._workflow_engine.list_workflows()),
            "memory_size": self._memory.size,
            "long_term_memory_count": (
                self._long_term_memory.count if self._long_term_memory else 0
            ),
            "pending_decision": self._pending is not None,
            "learning_patterns": self._learning.pattern_count,
            "learning_suggestions": self._learning.suggestion_count,
            "registered_skills": self._learning.registered_count,
        }
