"""语音管道：唤醒词 → VAD → STT → Agent → TTS 完整流程。

状态机: IDLE → LISTENING → PROCESSING → SPEAKING → IDLE
支持免唤醒、连续对话、打断机制。
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger("javas.voice.pipeline")


class PipelineState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"


@dataclass
class VoicePipelineConfig:
    """语音管道配置。"""
    wake_words: list[str] = field(default_factory=lambda: ["porcupine"])
    wake_word_enabled: bool = True
    vad_threshold: float = 0.5
    silence_timeout: float = 1.5
    max_listening_duration: float = 30.0
    continuous_mode: bool = False
    continuous_timeout: float = 30.0
    interruption_enabled: bool = True
    stt_engine: str = "auto"
    tts_engine: str = "auto"
    greeting: str = "我在，请说。"
    farewell: str = "再见。"


_EXIT_COMMANDS = frozenset({"退出", "再见", "quit", "exit", "goodbye", "拜拜"})


class VoicePipeline:
    """完整语音管道：唤醒词 → VAD → STT → Agent → TTS。"""

    def __init__(
        self,
        agent: Any,
        voice_ops: Any,
        config: VoicePipelineConfig | None = None,
    ) -> None:
        self._agent = agent
        self._voice_ops = voice_ops
        self._config = config or VoicePipelineConfig()
        self._state = PipelineState.IDLE
        self._running = False
        self._stop_event = asyncio.Event()
        self._last_active_time: float = 0.0
        self._interrupted = False
        self._on_state_change: Callable[[PipelineState], None] | None = None

    @property
    def state(self) -> PipelineState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def config(self) -> VoicePipelineConfig:
        return self._config

    def set_state_callback(self, cb: Callable[[PipelineState], None]) -> None:
        self._on_state_change = cb

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动管道，阻塞运行直到 stop()。"""
        if self._running:
            logger.warning("管道已在运行")
            return
        self._running = True
        self._stop_event.clear()
        logger.info("语音管道启动")
        try:
            if self._config.wake_word_enabled:
                await self._idle_loop()
            else:
                await self._speak_text(self._config.greeting)
                self._touch_active()
                if self._config.continuous_mode:
                    await self._continuous_loop()
                else:
                    await self._no_wake_loop()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("管道异常: %s", e)
        finally:
            self._running = False
            self._set_state(PipelineState.IDLE)

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        try:
            await self._safe_execute("stop", {})
        except Exception:
            pass

    # ------------------------------------------------------------------
    # IDLE 循环（等待唤醒词）
    # ------------------------------------------------------------------

    async def _idle_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            self._set_state(PipelineState.IDLE)
            try:
                detected = await self._wait_for_wake_word()
                if not self._running:
                    break
                if detected:
                    await self._speak_text(self._config.greeting)
                    self._touch_active()
                    if self._config.continuous_mode:
                        await self._continuous_loop()
                    else:
                        await self._single_interaction()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("IDLE 异常: %s", e)
                await asyncio.sleep(0.5)

    # ------------------------------------------------------------------
    # 交互循环
    # ------------------------------------------------------------------

    async def _single_interaction(self) -> None:
        text = await self._listen_for_speech()
        if not text:
            return
        if self._is_exit(text):
            await self._speak_text(self._config.farewell)
            await self.stop()
            return
        response = await self._process_query(text)
        if self._running:
            await self._speak_response(response)

    async def _continuous_loop(self) -> None:
        while self._running and not self._stop_event.is_set():
            self._touch_active()
            text = await self._listen_for_speech()
            if not self._running:
                break
            if not text:
                if self._is_timeout():
                    break
                continue
            if self._is_exit(text):
                await self._speak_text(self._config.farewell)
                await self.stop()
                return
            response = await self._process_query(text)
            if not self._running:
                break
            await self._speak_response(response)
            if self._is_timeout():
                break

    async def _no_wake_loop(self) -> None:
        """免唤醒 + 非连续模式：循环等待输入直到 stop 或退出。"""
        while self._running and not self._stop_event.is_set():
            await self._single_interaction()

    # ------------------------------------------------------------------
    # LISTENING
    # ------------------------------------------------------------------

    async def _listen_for_speech(self) -> str:
        self._set_state(PipelineState.LISTENING)
        try:
            result = await self._safe_execute(
                "listen", {"timeout": self._config.max_listening_duration}
            )
            return self._extract_text(result)
        except Exception as e:
            logger.error("STT 失败: %s", e)
            return ""

    # ------------------------------------------------------------------
    # PROCESSING
    # ------------------------------------------------------------------

    async def _process_query(self, text: str) -> str:
        self._set_state(PipelineState.PROCESSING)
        try:
            if hasattr(self._agent, "process"):
                r = await self._agent.process(text)
            elif hasattr(self._agent, "chat"):
                r = await self._agent.chat(text)
            else:
                return "系统配置错误。"
            return str(r) if r else ""
        except Exception as e:
            logger.error("Agent 异常: %s", e)
            return "抱歉，处理时出了点问题。"

    # ------------------------------------------------------------------
    # SPEAKING
    # ------------------------------------------------------------------

    async def _speak_response(self, text: str) -> bool:
        if not text or not text.strip():
            return True
        self._set_state(PipelineState.SPEAKING)
        self._interrupted = False
        try:
            await self._speak_text(text)
        except Exception as e:
            logger.error("TTS 异常: %s", e)
        return not self._interrupted

    async def _speak_text(self, text: str) -> None:
        if not text or not text.strip():
            return
        try:
            await self._safe_execute("stop", {})
            await self._safe_execute("speak", {"text": text})
            await self._wait_speech_done()
        except Exception as e:
            logger.error("TTS 失败: %s", e)

    async def _wait_speech_done(self) -> None:
        """等 TTS 完成，最多 5 秒。"""
        for _ in range(50):  # 50 * 0.1s = 5s
            if not self._running:
                return
            # 打断检测
            if self._config.interruption_enabled and await self._check_interrupt():
                self._interrupted = True
                try:
                    await self._safe_execute("stop", {})
                except Exception:
                    pass
                return
            # 检查 TTS 内部状态
            tts = getattr(self._voice_ops, "_tts", None)
            if tts and hasattr(tts, "_speaking") and not tts._speaking:
                return
            await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # 唤醒词
    # ------------------------------------------------------------------

    async def _wait_for_wake_word(self) -> bool:
        try:
            from src.voice.wake_word import WakeWordDetector
            detector = WakeWordDetector(keywords=self._config.wake_words)
            while self._running and not self._stop_event.is_set():
                if hasattr(detector, "detect"):
                    if await detector.detect():
                        return True
                elif hasattr(detector, "check"):
                    if await detector.check():
                        return True
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.warning("唤醒词检测不可用 (%s)，VAD fallback", e)
            while self._running and not self._stop_event.is_set():
                await asyncio.sleep(0.5)
        return False

    # ------------------------------------------------------------------
    # 打断
    # ------------------------------------------------------------------

    async def _check_interrupt(self) -> bool:
        try:
            from src.voice.vad import VoiceActivityDetector
            vad = VoiceActivityDetector(threshold=self._config.vad_threshold)
            return False  # 实际场景读音频流，这里仅占位
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    async def _safe_execute(self, action: str, params: dict) -> Any:
        try:
            return await self._voice_ops.execute(action, params)
        except Exception as e:
            logger.error("VoiceOps(%s) 异常: %s", action, e)
            return {"error": str(e)}

    def _extract_text(self, result: Any) -> str:
        if not result:
            return ""
        if isinstance(result, dict):
            if result.get("error"):
                return ""
            t = result.get("text", "")
            return t.strip() if isinstance(t, str) else ""
        if isinstance(result, str):
            return result.strip()
        return ""

    def _is_exit(self, text: str) -> bool:
        return text.lower().strip() in _EXIT_COMMANDS

    def _touch_active(self) -> None:
        self._last_active_time = time.monotonic()

    def _is_timeout(self) -> bool:
        if self._last_active_time <= 0:
            return False
        return (time.monotonic() - self._last_active_time) > self._config.continuous_timeout

    def _set_state(self, state: PipelineState) -> None:
        old = self._state
        self._state = state
        if old != state:
            logger.debug("状态: %s → %s", old.value, state.value)
            if self._on_state_change is not None:
                try:
                    self._on_state_change(state)
                except Exception:
                    pass
