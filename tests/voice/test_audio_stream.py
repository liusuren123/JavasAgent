"""AudioStream 单元测试。

所有测试使用 mock 替代真实音频设备，不依赖硬件。
"""

from __future__ import annotations

import asyncio
import struct
import wave
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.voice.audio_stream import AudioStream, _get_backend


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_silent_pcm(num_frames: int = 512) -> bytes:
    """生成静音 PCM 数据（16-bit 全零）。"""
    return struct.pack(f"<{num_frames}h", *[0] * num_frames)


def _make_loud_pcm(num_frames: int = 512, amplitude: int = 16000) -> bytes:
    """生成有声音的 PCM 数据（正弦波近似）。"""
    import math

    samples = [
        int(amplitude * math.sin(2 * math.pi * 440 * i / 16000))
        for i in range(num_frames)
    ]
    return struct.pack(f"<{num_frames}h", *samples)


class _MockVAD:
    """用于 record_until_silence 测试的 mock VAD。"""

    def __init__(self, speech_chunks: int = 5, then_silence: bool = True):
        self._speech_chunks = speech_chunks
        self._then_silence = then_silence
        self._count = 0

    def is_speech(self, chunk: bytes) -> bool:
        self._count += 1
        if self._count <= self._speech_chunks:
            return True
        return not self._then_silence


# ---------------------------------------------------------------------------
# 初始化测试
# ---------------------------------------------------------------------------

class TestAudioStreamInit:
    """AudioStream 初始化参数测试。"""

    def test_default_params(self) -> None:
        stream = AudioStream()
        assert stream.sample_rate == 16000
        assert stream.channels == 1
        assert stream.chunk_size == 512

    def test_custom_params(self) -> None:
        stream = AudioStream(sample_rate=48000, channels=2, chunk_size=1024)
        assert stream.sample_rate == 48000
        assert stream.channels == 2
        assert stream.chunk_size == 1024

    def test_not_running_initially(self) -> None:
        stream = AudioStream()
        assert stream._running is False


# ---------------------------------------------------------------------------
# 后端探测测试
# ---------------------------------------------------------------------------

class TestBackendDetection:
    """音频后端 fallback 逻辑测试。"""

    def test_backend_is_string_or_none(self) -> None:
        backend = _get_backend()
        assert backend is None or isinstance(backend, str)

    def test_no_backend_raises_runtime_error(self) -> None:
        """当两个后端都不可用时，start() 应抛出 RuntimeError。"""
        with patch("src.voice.audio_stream._backend", None):
            stream = AudioStream()
            with pytest.raises(RuntimeError, match="无可用的音频后端"):
                asyncio.run(stream.start(lambda b: None))


# ---------------------------------------------------------------------------
# WAV 生成测试
# ---------------------------------------------------------------------------

class TestWavGeneration:
    """WAV 数据生成正确性测试。"""

    def test_chunks_to_wav_produces_valid_wav(self) -> None:
        stream = AudioStream(sample_rate=16000, channels=1, chunk_size=512)
        pcm_data = _make_loud_pcm(512)
        wav_bytes = stream._chunks_to_wav([pcm_data, pcm_data])

        # 验证能被 wave 模块解析
        buf = BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 1024

    def test_chunks_to_wav_stereo(self) -> None:
        stream = AudioStream(sample_rate=44100, channels=2, chunk_size=1024)
        pcm_data = _make_loud_pcm(1024)
        wav_bytes = stream._chunks_to_wav([pcm_data])

        buf = BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 2
            assert wf.getframerate() == 44100

    def test_empty_chunks_produce_valid_wav(self) -> None:
        stream = AudioStream()
        wav_bytes = stream._chunks_to_wav([])
        buf = BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() == 0

    def test_silent_pcm_roundtrip(self) -> None:
        stream = AudioStream()
        pcm = _make_silent_pcm(512)
        wav_bytes = stream._chunks_to_wav([pcm])
        buf = BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            frames = wf.readframes(512)
            # 静音数据应全为 0
            samples = struct.unpack(f"<{512}h", frames)
            assert all(s == 0 for s in samples)


# ---------------------------------------------------------------------------
# record_until_silence 测试
# ---------------------------------------------------------------------------

class TestRecordUntilSilence:
    """record_until_silence 在 mock VAD 下的行为测试。"""

    @pytest.mark.asyncio
    async def test_stops_on_silence(self) -> None:
        """录音应在检测到静音后停止。"""
        stream = AudioStream()
        vad = _MockVAD(speech_chunks=3, then_silence=True)

        # mock start/stop 来模拟音频流
        recorded_chunks: list[bytes] = []

        original_start = stream.start
        original_stop = stream.stop

        async def fake_start(callback: Any) -> None:
            stream._running = True
            # 模拟发送几个 chunk
            for _ in range(3):
                callback(_make_loud_pcm(512))
            # 然后发送静音
            for _ in range(50):  # 足够多的静音 chunk 触发 silence_threshold
                callback(_make_silent_pcm(512))

        async def fake_stop() -> None:
            stream._running = False

        stream.start = fake_start  # type: ignore[assignment]
        stream.stop = fake_stop  # type: ignore[assignment]

        wav_data = await stream.record_until_silence(
            vad, max_duration=60.0, silence_threshold=0.3
        )
        assert len(wav_data) > 0
        # 验证是有效的 WAV
        buf = BytesIO(wav_data)
        with wave.open(buf, "rb") as wf:
            assert wf.getnframes() > 0

    @pytest.mark.asyncio
    async def test_max_duration_limit(self) -> None:
        """录音应在 max_duration 到期后停止。"""
        stream = AudioStream()
        vad = _MockVAD(speech_chunks=9999, then_silence=False)

        async def fake_start(callback: Any) -> None:
            stream._running = True
            # 不断发送语音数据
            for _ in range(200):
                callback(_make_loud_pcm(512))

        async def fake_stop() -> None:
            stream._running = False

        stream.start = fake_start  # type: ignore[assignment]
        stream.stop = fake_stop  # type: ignore[assignment]

        # max_duration 设很小值，让秒数累积触发
        wav_data = await stream.record_until_silence(
            vad, max_duration=0.001, silence_threshold=999.0
        )
        # 应该因为超时停止
        assert isinstance(wav_data, bytes)


# ---------------------------------------------------------------------------
# stop / 资源清理测试
# ---------------------------------------------------------------------------

class TestStop:
    """停止音频流和资源清理测试。"""

    @pytest.mark.asyncio
    async def test_stop_resets_state(self) -> None:
        stream = AudioStream()
        stream._running = True
        stream._stream = MagicMock()
        stream._pyaudio_instance = MagicMock()

        await stream.stop()
        assert stream._running is False
        assert stream._stream is None
        assert stream._pyaudio_instance is None

    @pytest.mark.asyncio
    async def test_stop_is_safe_when_not_started(self) -> None:
        stream = AudioStream()
        # 没有启动就 stop 不应抛异常
        await stream.stop()
        assert stream._running is False
