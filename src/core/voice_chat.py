"""语音对话循环引擎。

整合 STT → Agent 处理 → TTS 的完整语音交互循环，
提供类似贾维斯的语音助手对话体验。

Usage::

    from src.core.voice_chat import VoiceChatLoop, VoiceChatConfig

    loop = VoiceChatLoop(agent, voice_ops, VoiceChatConfig(wake_word="贾维斯"))
    await loop.start()
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger

from src.agents.base_agent import BaseAgent
from src.tools.voice_ops import VoiceOps


@dataclass
class VoiceChatConfig:
    """语音对话配置。

    Attributes:
        wake_word: 唤醒词，空字符串表示无需唤醒词（直接对话）
        listen_timeout: STT 监听超时时间（秒）
        phrase_limit: 单次语音输入最长时长（秒）
        tts_rate: TTS 语速（SAPI 范围 -10 ~ 10，映射为实际值）
        exit_commands: 触发退出的关键词列表
        silence_threshold: 静音多少秒后认为用户说完
        greeting: 启动时的欢迎语
        farewell: 退出时的告别语
    """

    wake_word: str = ""
    listen_timeout: float = 10.0
    phrase_limit: float = 15.0
    tts_rate: int = 0
    exit_commands: list[str] = field(
        default_factory=lambda: ["退出", "再见", "quit", "exit", "goodbye"]
    )
    silence_threshold: float = 2.0
    greeting: str = "语音对话模式已启动，说点什么吧。"
    farewell: str = "再见，老板。"


class VoiceChatLoop:
    """语音对话循环引擎。

    持续监听麦克风输入 → Agent 处理 → TTS 朗读回复，
    构成完整的语音交互循环。

    特性：
    - 可选唤醒词：设置后需要先说唤醒词才会处理后续指令
    - 退出指令：说出指定关键词自动退出循环
    - 错误恢复：STT/TTS 出错后打印友好提示，不崩溃
    - 热键中断：朗读过程中收到新输入会自动停止当前朗读

    Usage::

        loop = VoiceChatLoop(agent, voice_ops)
        await loop.start()
    """

    def __init__(
        self,
        agent: BaseAgent,
        voice_ops: VoiceOps,
        config: VoiceChatConfig | None = None,
    ) -> None:
        """初始化语音对话循环。

        Args:
            agent: JavasAgent 实例，用于处理用户输入
            voice_ops: 语音交互门面，提供 STT/TTS 能力
            config: 对话配置，为 None 时使用默认值
        """
        self._agent = agent
        self._voice_ops = voice_ops
        self._config = config or VoiceChatConfig()
        self._running = False
        self._wake_word_activated = not bool(self._config.wake_word)
        self._on_state_change: Callable[[str], None] | None = None

    @property
    def is_running(self) -> bool:
        """对话循环是否正在运行。"""
        return self._running

    @property
    def config(self) -> VoiceChatConfig:
        """当前配置（只读）。"""
        return self._config

    def set_state_callback(self, callback: Callable[[str], None]) -> None:
        """设置状态变更回调。

        用于外部监听对话循环的状态变化（如更新 UI 提示）。

        Args:
            callback: 状态变更回调函数，接收状态字符串：
                - "listening": 正在听
                - "thinking": 思考中
                - "speaking": 正在回复
                - "idle": 空闲
                - "error": 出错
        """
        self._on_state_change = callback

    async def start(self) -> None:
        """启动语音对话循环。

        会持续运行直到收到退出指令或调用 stop()。
        启动时会朗读欢迎语。
        """
        if self._running:
            logger.warning("语音对话循环已在运行")
            return

        self._running = True
        logger.info("语音对话循环启动")

        # 朗读欢迎语
        await self._speak(self._config.greeting)

        try:
            while self._running:
                try:
                    await self._listen_cycle()
                except asyncio.CancelledError:
                    logger.info("语音对话循环被取消")
                    break
                except Exception as e:
                    logger.error(f"对话循环异常: {e}")
                    self._emit_state("error")
                    # 错误恢复：短暂等待后继续循环
                    await asyncio.sleep(1.0)
        finally:
            self._running = False
            logger.info("语音对话循环已停止")

    async def stop(self) -> None:
        """停止语音对话循环。

        会停止当前朗读，朗读告别语（如果仍在运行），然后退出循环。
        """
        if not self._running:
            return

        logger.info("正在停止语音对话循环...")
        self._running = False

        # 停止当前朗读
        try:
            await self._voice_ops.execute("stop", {})
        except Exception as e:
            logger.debug(f"停止朗读时出错（可忽略）: {e}")

    # ------------------------------------------------------------------
    # 核心循环
    # ------------------------------------------------------------------

    async def _listen_cycle(self) -> None:
        """单次听→处理→回复循环。"""
        # 1. 听取用户输入
        self._emit_state("listening")
        stt_result = await self._listen()

        if not self._running:
            return

        text = self._extract_text(stt_result)
        if not text:
            # 未识别到有效内容，继续下一轮
            return

        logger.info(f"语音输入: {text}")

        # 2. 检查退出指令
        if self._is_exit_command(text):
            logger.info("检测到退出指令")
            await self._speak(self._config.farewell)
            await self.stop()
            return

        # 3. 唤醒词检测
        if self._config.wake_word and not self._wake_word_activated:
            if self._contains_wake_word(text):
                self._wake_word_activated = True
                await self._speak("我在，请说。")
                return
            else:
                # 未激活，忽略输入
                logger.debug(f"唤醒词未激活，忽略输入: {text}")
                return

        # 如果有唤醒词且已激活，去掉句子中的唤醒词
        cleaned_text = self._strip_wake_word(text)
        if not cleaned_text.strip():
            # 只有唤醒词没有实际指令
            return

        # 4. Agent 处理
        self._emit_state("thinking")
        response = await self._process_with_agent(cleaned_text)

        if not self._running:
            return

        # 5. TTS 朗读回复
        self._emit_state("speaking")
        await self._speak(response)

        # 重置唤醒词状态（如果配置了唤醒词，每次指令后需要重新唤醒）
        if self._config.wake_word:
            self._wake_word_activated = False

        self._emit_state("idle")

    # ------------------------------------------------------------------
    # STT / TTS / Agent 调用（带错误恢复）
    # ------------------------------------------------------------------

    async def _listen(self) -> dict[str, Any]:
        """调用 STT 监听，出错时返回空结果而不崩溃。"""
        try:
            return await self._voice_ops.execute(
                "listen",
                {"timeout": self._config.listen_timeout},
            )
        except Exception as e:
            logger.error(f"语音识别失败: {e}")
            self._emit_state("error")
            return {"status": "error", "text": "", "error": str(e)}

    async def _speak(self, text: str) -> None:
        """调用 TTS 朗读文本，出错时静默跳过。"""
        if not text or not text.strip():
            return

        try:
            # 先停止之前的朗读（支持热键中断效果）
            await self._voice_ops.execute("stop", {})
            await self._voice_ops.execute(
                "speak",
                {"text": text, "rate": self._config.tts_rate},
            )
            # 等待朗读完成（简单轮询，避免阻塞事件循环）
            await self._wait_for_speech_complete()
        except Exception as e:
            logger.error(f"语音合成失败: {e}")
            self._emit_state("error")

    async def _wait_for_speech_complete(self) -> None:
        """等待 TTS 朗读完成或循环被停止。"""
        max_wait = 60  # 最多等 60 秒
        for _ in range(max_wait):
            if not self._running:
                return
            await asyncio.sleep(0.5)
            # 检查 TTS 是否仍在朗读
            # VoiceTTS 内部维护 _speaking 状态，但外部无法直接访问
            # 这里简单等待一段时间，让朗读自然结束
            tts = self._voice_ops._tts
            if hasattr(tts, "_speaking") and not tts._speaking:
                return

    async def _process_with_agent(self, text: str) -> str:
        """调用 Agent 处理用户输入，出错时返回友好提示。"""
        try:
            return await self._agent.process(text)
        except Exception as e:
            logger.error(f"Agent 处理失败: {e}")
            return "抱歉，处理时出了点问题，请再说一次。"

    # ------------------------------------------------------------------
    # 文本处理工具
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_text(stt_result: dict[str, Any]) -> str:
        """从 STT 返回结果中提取识别文本。

        Args:
            stt_result: STT execute() 的返回值

        Returns:
            识别到的文本，失败时返回空字符串
        """
        if not stt_result:
            return ""

        # 检查是否有错误
        if "error" in stt_result:
            logger.debug(f"STT 返回错误: {stt_result['error']}")
            return ""

        # 提取文本
        text = stt_result.get("text", "")
        if isinstance(text, str):
            return text.strip()
        return ""

    def _is_exit_command(self, text: str) -> bool:
        """检查文本是否为退出指令。

        Args:
            text: 用户输入的文本

        Returns:
            是否为退出指令
        """
        text_lower = text.lower().strip()
        return text_lower in [cmd.lower() for cmd in self._config.exit_commands]

    def _contains_wake_word(self, text: str) -> bool:
        """检查文本是否包含唤醒词。

        Args:
            text: 用户输入的文本

        Returns:
            是否包含唤醒词
        """
        if not self._config.wake_word:
            return True
        return self._config.wake_word.lower() in text.lower()

    def _strip_wake_word(self, text: str) -> str:
        """去除文本中的唤醒词。

        Args:
            text: 原始文本

        Returns:
            去除唤醒词后的文本
        """
        if not self._config.wake_word:
            return text
        # 不区分大小写替换
        pattern = re.compile(re.escape(self._config.wake_word), re.IGNORECASE)
        return pattern.sub("", text).strip()

    # ------------------------------------------------------------------
    # 状态管理
    # ------------------------------------------------------------------

    def _emit_state(self, state: str) -> None:
        """触发状态变更回调。

        Args:
            state: 新状态字符串
        """
        if self._on_state_change is not None:
            try:
                self._on_state_change(state)
            except Exception as e:
                logger.debug(f"状态回调异常（忽略）: {e}")
