"""本地唤醒词检测器。

三级降级策略：
1. Porcupine (pvporcupine) — 精度最高，需 AccessKey
2. OpenWakeWord (openwakeword) — 开源方案，需 onnxruntime
3. VAD 模拟 — 使用 VoiceActivityDetector 检测持续语音，
   非真正唤醒词检测，但保证功能可用

缺少依赖时自动降级，不会崩溃。
"""

from __future__ import annotations

import asyncio
import time
from enum import Enum
from typing import TYPE_CHECKING, Callable

from loguru import logger

from src.voice.vad import VoiceActivityDetector

if TYPE_CHECKING:
    from src.voice.audio_stream import AudioStream

# ---------------------------------------------------------------------------
# 后端探测
# ---------------------------------------------------------------------------

class _Backend(str, Enum):
    """唤醒词检测后端枚举。"""
    PORCUPINE = "porcupine"
    OPENWAKEWORD = "openwakeword"
    VAD = "vad"


# Porcupine 内置唤醒词
_PORCUPINE_BUILTIN = [
    "porcupine",
    "hey barista",
    "grasshopper",
    "alexa",
    "computer",
    "jarvis",
    "picovoice",
    "terminator",
    "bumblebee",
]

# OpenWakeWord 内置唤醒词
_OWW_BUILTIN = [
    "hey jarvis",
    "alexa",
    "ok google",
    "hey mycroft",
    "navi",
    "sheila",
]

# 运行时探测结果
_active_backend: _Backend | None = None
_pvporcupine: object | None = None
_openwakeword: object | None = None


def _detect_backend(access_key: str | None = None) -> _Backend | None:
    """检测可用的唤醒词后端。

    Parameters
    ----------
    access_key : str | None
        Porcupine AccessKey。无 key 时跳过 Porcupine。

    Returns
    -------
    _Backend | None
        可用后端，全部不可用返回 None（后续使用 VAD fallback）。
    """
    global _active_backend, _pvporcupine, _openwakeword  # noqa: PLW0603

    # Level 1: Porcupine
    if access_key:
        try:
            import pvporcupine as _pvp  # type: ignore[import-untyped]

            _pvporcupine = _pvp
            _active_backend = _Backend.PORCUPINE
            logger.info("唤醒词后端: Porcupine")
            return _Backend.PORCUPINE
        except ImportError:
            logger.debug("pvporcupine 不可用，尝试下一级后端")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Porcupine 初始化失败: {}", exc)

    # Level 2: OpenWakeWord
    try:
        import openwakeword as _oww  # type: ignore[import-untyped]

        _openwakeword = _oww
        _active_backend = _Backend.OPENWAKEWORD
        logger.info("唤醒词后端: OpenWakeWord")
        return _Backend.OPENWAKEWORD
    except ImportError:
        logger.debug("openwakeword 不可用，使用 VAD fallback")
    except Exception as exc:  # noqa: BLE001
        logger.debug("OpenWakeWord 初始化失败: {}", exc)

    # Level 3: VAD fallback（始终可用）
    _active_backend = _Backend.VAD
    logger.warning("使用 VAD 模拟唤醒词检测（非真正唤醒词识别）")
    return _Backend.VAD


def _get_backend() -> _Backend | None:
    """返回当前激活的后端。"""
    return _active_backend


# ---------------------------------------------------------------------------
# WakeWordDetector
# ---------------------------------------------------------------------------

class WakeWordDetector:
    """本地唤醒词检测器。

    支持 3 级降级策略：Porcupine → OpenWakeWord → VAD 模拟。

    Parameters
    ----------
    keywords : list[str] | None
        唤醒词列表。默认 ["porcupine"]（Porcupine 内置）。
        不同后端支持的关键词不同，见 list_builtin_keywords()。
    access_key : str | None
        Porcupine AccessKey（免费注册获取）。无 key 则跳过 Porcupine。
    sensitivity : float
        检测灵敏度 0.0 ~ 1.0，默认 0.5。值越大越灵敏。
    """

    def __init__(
        self,
        keywords: list[str] | None = None,
        access_key: str | None = None,
        sensitivity: float = 0.5,
    ) -> None:
        self.keywords = keywords or ["porcupine"]
        self.access_key = access_key
        self.sensitivity = max(0.0, min(1.0, sensitivity))

        self._backend: _Backend | None = None
        self._engine: object | None = None
        self._running = False
        self._listen_task: asyncio.Task | None = None  # type: ignore[type-arg]

        # VAD fallback 状态
        self._vad: VoiceActivityDetector | None = None
        self._speech_start: float | None = None
        self._vad_trigger_duration = 0.8  # 持续语音时长阈值（秒）

        # 初始化后端
        self._init_engine()

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _init_engine(self) -> None:
        """根据可用依赖初始化检测引擎。"""
        self._backend = _detect_backend(self.access_key)

        if self._backend == _Backend.PORCUPINE:
            self._init_porcupine()
        elif self._backend == _Backend.OPENWAKEWORD:
            self._init_openwakeword()
        else:
            self._init_vad_fallback()

    def _init_porcupine(self) -> None:
        """初始化 Porcupine 引擎。"""
        if _pvporcupine is None or not self.access_key:
            self._backend = _Backend.VAD
            self._init_vad_fallback()
            return

        try:
            keyword_paths = []
            for kw in self.keywords:
                path = _pvporcupine.KEYWORD_PATHS.get(kw)  # type: ignore[union-attr]
                if path is not None:
                    keyword_paths.append(path)
                else:
                    logger.warning("Porcupine 不支持唤醒词 '{}'", kw)

            if not keyword_paths:
                logger.warning("没有可用的 Porcupine 唤醒词，降级到 VAD")
                self._backend = _Backend.VAD
                self._init_vad_fallback()
                return

            sensitivities = [self.sensitivity] * len(keyword_paths)
            self._engine = _pvporcupine.create(  # type: ignore[union-attr]
                access_key=self.access_key,
                keyword_paths=keyword_paths,
                sensitivities=sensitivities,
            )
            logger.info(
                "Porcupine 引擎就绪，监听: {}",
                ", ".join(self.keywords),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Porcupine 创建失败: {}，降级到 VAD", exc)
            self._backend = _Backend.VAD
            self._init_vad_fallback()

    def _init_openwakeword(self) -> None:
        """初始化 OpenWakeWord 引擎。"""
        try:
            if _openwakeword is not None:
                self._engine = _openwakeword.OpenWakeWord(  # type: ignore[union-attr]
                    inference_threshold=self.sensitivity,
                )
                logger.info("OpenWakeWord 引擎就绪")
            else:
                self._backend = _Backend.VAD
                self._init_vad_fallback()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OpenWakeWord 初始化失败: {}，降级到 VAD", exc)
            self._backend = _Backend.VAD
            self._init_vad_fallback()

    def _init_vad_fallback(self) -> None:
        """初始化 VAD 模拟唤醒词。"""
        self._backend = _Backend.VAD
        self._vad = VoiceActivityDetector(threshold=self.sensitivity)
        self._speech_start = None
        logger.warning(
            "使用 VAD 模拟唤醒词检测 — "
            "检测到 {:.1f}s 持续语音即触发，非真正唤醒词识别",
            self._vad_trigger_duration,
        )

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def start_listening(
        self,
        callback: Callable[[], None],
        audio_stream: AudioStream,
    ) -> None:
        """开始后台监听唤醒词，检测到时调用 callback。

        Parameters
        ----------
        callback : Callable[[], None]
            唤醒词检测到时的回调函数。
        audio_stream : AudioStream
            音频流，从中读取音频帧。
        """
        if self._running:
            logger.warning("唤醒词检测已在运行")
            return

        self._running = True

        if self._backend == _Backend.PORCUPINE:
            self._listen_task = asyncio.create_task(
                self._listen_porcupine(callback, audio_stream),
            )
        elif self._backend == _Backend.OPENWAKEWORD:
            self._listen_task = asyncio.create_task(
                self._listen_openwakeword(callback, audio_stream),
            )
        else:
            self._listen_task = asyncio.create_task(
                self._listen_vad(callback, audio_stream),
            )

        backend_name = self._backend.value if self._backend else "unknown"
        logger.info("唤醒词检测已启动（后端: {}）", backend_name)

    async def stop_listening(self) -> None:
        """停止监听。"""
        self._running = False
        if self._listen_task is not None:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass
            self._listen_task = None

        # 清理 Porcupine 资源
        if self._backend == _Backend.PORCUPINE and self._engine is not None:
            try:
                self._engine.delete()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
            self._engine = None

        logger.info("唤醒词检测已停止")

    @staticmethod
    def list_builtin_keywords() -> list[str]:
        """列出内置可用唤醒词。

        Returns
        -------
        list[str]
            当前后端支持的唤醒词列表。
        """
        if _active_backend == _Backend.PORCUPINE:
            return list(_PORCUPINE_BUILTIN)
        elif _active_backend == _Backend.OPENWAKEWORD:
            return list(_OWW_BUILTIN)
        else:
            return ["any_voice"]  # VAD 模式无特定唤醒词

    # ------------------------------------------------------------------
    # 后端监听循环
    # ------------------------------------------------------------------

    async def _listen_porcupine(
        self,
        callback: Callable[[], None],
        audio_stream: AudioStream,
    ) -> None:
        """Porcupine 后端监听循环。"""
        if self._engine is None:
            logger.error("Porcupine 引擎未初始化")
            return

        frame_length = self._engine.frame_length  # type: ignore[union-attr]
        sample_rate = self._engine.sample_rate  # type: ignore[union-attr]

        # 调整音频流参数匹配 Porcupine 要求
        audio_stream.sample_rate = sample_rate
        audio_stream.chunk_size = frame_length

        def _on_frame(data: bytes) -> None:
            if not self._running:
                return
            try:
                index = self._engine.process(data)  # type: ignore[union-attr]
                if index >= 0:
                    logger.info("Porcupine 检测到唤醒词 (index={})", index)
                    callback()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Porcupine 处理出错: {}", exc)

        try:
            await audio_stream.start(_on_frame)
            while self._running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await audio_stream.stop()

    async def _listen_openwakeword(
        self,
        callback: Callable[[], None],
        audio_stream: AudioStream,
    ) -> None:
        """OpenWakeWord 后端监听循环。"""
        if self._engine is None:
            logger.error("OpenWakeWord 引擎未初始化")
            return

        def _on_frame(data: bytes) -> None:
            if not self._running:
                return
            try:
                # OpenWakeWord 需要 numpy 数组
                import numpy as np  # type: ignore[import-untyped]

                audio_np = np.frombuffer(data, dtype=np.int16)
                prediction = self._engine.predict(audio_np)  # type: ignore[union-attr]
                for model_name, scores in prediction.items():
                    if hasattr(scores, "detected") and scores.detected:
                        logger.info("OpenWakeWord 检测到: {}", model_name)
                        callback()
            except Exception as exc:  # noqa: BLE001
                logger.warning("OpenWakeWord 处理出错: {}", exc)

        try:
            await audio_stream.start(_on_frame)
            while self._running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await audio_stream.stop()

    async def _listen_vad(
        self,
        callback: Callable[[], None],
        audio_stream: AudioStream,
    ) -> None:
        """VAD 模拟唤醒词监听循环。"""
        if self._vad is None:
            self._vad = VoiceActivityDetector(threshold=self.sensitivity)

        def _on_frame(data: bytes) -> None:
            if not self._running:
                return
            now = time.monotonic()
            is_speech = self._vad.is_speech(data)

            if is_speech:
                if self._speech_start is None:
                    self._speech_start = now
                else:
                    duration = now - self._speech_start
                    if duration >= self._vad_trigger_duration:
                        logger.info(
                            "VAD 模拟唤醒词触发（持续语音 {:.1f}s）",
                            duration,
                        )
                        callback()
                        # 重置，避免连续触发
                        self._speech_start = None
                        self._running = False
            else:
                self._speech_start = None

        try:
            await audio_stream.start(_on_frame)
            while self._running:
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass
        finally:
            await audio_stream.stop()

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------

    @property
    def backend_name(self) -> str:
        """当前后端名称。"""
        return self._backend.value if self._backend else "none"

    @property
    def is_listening(self) -> bool:
        """是否正在监听。"""
        return self._running
