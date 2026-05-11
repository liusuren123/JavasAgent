"""唤醒词检测器测试。

所有测试 mock 音频设备，不依赖真实硬件。
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helper: mock 音频流
# ---------------------------------------------------------------------------


class MockAudioStream:
    """模拟 AudioStream，收集 callback 而非真实录音。"""

    def __init__(self) -> None:
        self.sample_rate = 16000
        self.channels = 1
        self.chunk_size = 512
        self._callback = None
        self._started = False

    async def start(self, callback):
        self._callback = callback
        self._started = True

    async def stop(self):
        self._started = False

    def feed_chunk(self, data: bytes) -> None:
        """手动注入音频帧（同步调用 callback）。"""
        if self._callback:
            self._callback(data)


# ---------------------------------------------------------------------------
# Helper: 生成静音/有声音频帧
# ---------------------------------------------------------------------------


def _silence_chunk(size: int = 1024) -> bytes:
    """生成静音 PCM 16-bit 数据。"""
    return b"\x00\x00" * (size // 2)


def _speech_chunk(size: int = 1024) -> bytes:
    """生成模拟有声音频帧（随机噪音）。"""
    import struct
    import random

    samples = [random.randint(5000, 20000) for _ in range(size // 2)]
    return struct.pack(f"<{len(samples)}h", *samples)


# ---------------------------------------------------------------------------
# 测试 WakeWordDetector 初始化
# ---------------------------------------------------------------------------


class TestWakeWordDetectorInit:
    """测试初始化参数。"""

    def test_default_params(self):
        """默认参数初始化。"""
        # VAD fallback 模式（无 access_key、无 pvporcupine）
        with patch.dict(sys.modules, {}):
            from src.voice.wake_word import WakeWordDetector

            det = WakeWordDetector()
            assert det.keywords == ["porcupine"]
            assert det.access_key is None
            assert 0.0 <= det.sensitivity <= 1.0
            assert det.backend_name in ("vad", "porcupine", "openwakeword")

    def test_custom_params(self):
        """自定义参数初始化。"""
        with patch.dict(sys.modules, {}):
            from src.voice.wake_word import WakeWordDetector

            det = WakeWordDetector(
                keywords=["jarvis", "alexa"],
                access_key=None,
                sensitivity=0.8,
            )
            assert det.keywords == ["jarvis", "alexa"]
            assert det.sensitivity == 0.8

    def test_sensitivity_clamped(self):
        """灵敏度超出范围时被 clamp 到 0.0~1.0。"""
        from src.voice.wake_word import WakeWordDetector

        det_high = WakeWordDetector(sensitivity=2.0)
        assert det_high.sensitivity == 1.0

        det_low = WakeWordDetector(sensitivity=-1.0)
        assert det_low.sensitivity == 0.0


# ---------------------------------------------------------------------------
# 测试 list_builtin_keywords
# ---------------------------------------------------------------------------


class TestListBuiltinKeywords:
    """测试内置唤醒词列表。"""

    def test_returns_non_empty(self):
        """返回非空列表。"""
        from src.voice.wake_word import WakeWordDetector

        keywords = WakeWordDetector.list_builtin_keywords()
        assert isinstance(keywords, list)
        assert len(keywords) > 0

    def test_vad_mode_returns_any_voice(self):
        """VAD 模式返回 ['any_voice']。"""
        from src.voice.wake_word import WakeWordDetector, _Backend, _active_backend

        # 强制 VAD 模式
        with patch("src.voice.wake_word._active_backend", _Backend.VAD):
            keywords = WakeWordDetector.list_builtin_keywords()
            assert "any_voice" in keywords


# ---------------------------------------------------------------------------
# 测试 Porcupine 后端（mock）
# ---------------------------------------------------------------------------


class TestPorcupineBackend:
    """测试 Porcupine 后端检测逻辑。"""

    def _make_porcupine_detector(self):
        """创建一个使用 mock Porcupine 的检测器。"""
        mock_engine = MagicMock()
        mock_engine.frame_length = 512
        mock_engine.sample_rate = 16000
        mock_engine.process.return_value = -1  # 默认未检测到
        mock_engine.delete = MagicMock()

        mock_pvp = MagicMock()
        mock_pvp.KEYWORD_PATHS = {"porcupine": "/path/to/porcupine.ppn"}
        mock_pvp.create.return_value = mock_engine

        with patch.dict(sys.modules, {"pvporcupine": mock_pvp}):
            with patch("src.voice.wake_word._pvporcupine", mock_pvp):
                with patch(
                    "src.voice.wake_word._detect_backend",
                    return_value=None,
                ):
                    from src.voice.wake_word import WakeWordDetector, _Backend

                    det = WakeWordDetector(
                        keywords=["porcupine"],
                        access_key="test-key-123",
                        sensitivity=0.5,
                    )
                    # 手动设置 Porcupine 后端
                    det._backend = _Backend.PORCUPINE
                    det._engine = mock_engine
                    return det, mock_engine

    @pytest.mark.asyncio
    async def test_porcupine_detect_wake_word(self):
        """Porcupine 检测到唤醒词时调用 callback。"""
        det, mock_engine = self._make_porcupine_detector()
        callback = MagicMock()

        # 设置 process 返回检测到
        mock_engine.process.return_value = 0
        det._running = True

        stream = MockAudioStream()
        listen_task = asyncio.create_task(
            det._listen_porcupine(callback, stream),
        )

        # 等待 task 开始并注册 callback
        for _ in range(50):
            if stream._callback is not None:
                break
            await asyncio.sleep(0.01)

        # 直接注入帧触发回调
        stream.feed_chunk(_speech_chunk())

        # 等待回调执行
        await asyncio.sleep(0.05)
        det._running = False
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

        callback.assert_called()

    @pytest.mark.asyncio
    async def test_porcupine_no_detection(self):
        """Porcupine 未检测到唤醒词时不调用 callback。"""
        det, mock_engine = self._make_porcupine_detector()
        callback = MagicMock()

        # process 返回 -1 表示未检测到
        mock_engine.process.return_value = -1
        det._running = True

        stream = MockAudioStream()
        listen_task = asyncio.create_task(
            det._listen_porcupine(callback, stream),
        )

        # 等待 callback 注册
        for _ in range(50):
            if stream._callback is not None:
                break
            await asyncio.sleep(0.01)

        stream.feed_chunk(_silence_chunk())

        await asyncio.sleep(0.05)
        det._running = False
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

        callback.assert_not_called()

    def test_no_access_key_skips_porcupine(self):
        """无 access_key 时跳过 Porcupine。"""
        from src.voice.wake_word import WakeWordDetector, _Backend

        # 无 access_key，即使 mock 了 pvporcupine 也应降级
        det = WakeWordDetector(access_key=None)
        assert det._backend == _Backend.VAD


# ---------------------------------------------------------------------------
# 测试 VAD fallback 模式
# ---------------------------------------------------------------------------


class TestVADFallback:
    """测试 VAD 模拟唤醒词。"""

    @pytest.mark.asyncio
    async def test_vad_triggers_on_sustained_speech(self):
        """持续语音超过阈值时触发。"""
        from src.voice.wake_word import WakeWordDetector, _Backend
        import time as time_mod

        det = WakeWordDetector(access_key=None)
        assert det._backend == _Backend.VAD
        det._vad_trigger_duration = 0.01  # 极低阈值加速测试
        det._running = True

        callback = MagicMock()
        stream = MockAudioStream()

        listen_task = asyncio.create_task(
            det._listen_vad(callback, stream),
        )

        # 等待 callback 注册
        for _ in range(50):
            if stream._callback is not None:
                break
            await asyncio.sleep(0.01)

        # mock time.monotonic 模拟时间流逝
        monotonic_time = 1000.0
        with patch.object(time_mod, "monotonic", side_effect=lambda: monotonic_time):
            # 注入第一帧（设置 _speech_start）
            stream.feed_chunk(_speech_chunk(1024))
            # 推进时间
            monotonic_time += 0.02
            # 注入第二帧（duration > trigger_duration）
            stream.feed_chunk(_speech_chunk(1024))

        # 等待回调执行
        await asyncio.sleep(0.05)
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

        callback.assert_called()

    @pytest.mark.asyncio
    async def test_vad_no_trigger_on_silence(self):
        """静音不触发。"""
        from src.voice.wake_word import WakeWordDetector, _Backend

        det = WakeWordDetector(access_key=None)
        assert det._backend == _Backend.VAD
        det._running = True

        callback = MagicMock()
        stream = MockAudioStream()

        listen_task = asyncio.create_task(
            det._listen_vad(callback, stream),
        )

        # 等待 callback 注册
        for _ in range(50):
            if stream._callback is not None:
                break
            await asyncio.sleep(0.01)

        for _ in range(20):
            stream.feed_chunk(_silence_chunk())

        await asyncio.sleep(0.1)
        det._running = False
        listen_task.cancel()
        try:
            await listen_task
        except asyncio.CancelledError:
            pass

        callback.assert_not_called()


# ---------------------------------------------------------------------------
# 测试 start/stop 生命周期
# ---------------------------------------------------------------------------


class TestLifecycle:
    """测试 start_listening / stop_listening。"""

    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        """启动后 is_listening 为 True，停止后为 False。"""
        from src.voice.wake_word import WakeWordDetector

        det = WakeWordDetector(access_key=None)
        assert not det.is_listening

        stream = MockAudioStream()
        callback = MagicMock()

        await det.start_listening(callback, stream)
        assert det.is_listening

        await det.stop_listening()
        assert not det.is_listening

    @pytest.mark.asyncio
    async def test_double_start_no_error(self):
        """重复 start 不报错。"""
        from src.voice.wake_word import WakeWordDetector

        det = WakeWordDetector(access_key=None)
        stream = MockAudioStream()
        callback = MagicMock()

        await det.start_listening(callback, stream)
        # 再次 start 应该只是 warning，不抛异常
        await det.start_listening(callback, stream)

        await det.stop_listening()

    @pytest.mark.asyncio
    async def test_stop_without_start(self):
        """未启动直接 stop 不报错。"""
        from src.voice.wake_word import WakeWordDetector

        det = WakeWordDetector(access_key=None)
        await det.stop_listening()  # 不应抛异常


# ---------------------------------------------------------------------------
# 测试 backend_name 属性
# ---------------------------------------------------------------------------


class TestProperties:
    """测试属性。"""

    def test_backend_name_vad(self):
        """VAD 模式 backend_name 为 'vad'。"""
        from src.voice.wake_word import WakeWordDetector

        det = WakeWordDetector(access_key=None)
        assert det.backend_name == "vad"

    def test_is_listening_initially_false(self):
        """初始 is_listening 为 False。"""
        from src.voice.wake_word import WakeWordDetector

        det = WakeWordDetector(access_key=None)
        assert not det.is_listening
