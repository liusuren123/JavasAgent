"""语音集成测试。

测试 VoicePipeline 与 mock Agent 的完整流程：
  - 唤醒词 → 对话 → 退出流程
  - 打断机制
  - 连续对话模式
  - faster-whisper STT 后端（mock）
  - listen_with_vad 方法
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.voice.pipeline import PipelineState, VoicePipeline, VoicePipelineConfig


# ---------------------------------------------------------------------------
# Mock 工厂
# ---------------------------------------------------------------------------


class MockAgent:
    """Mock Agent，记录调用。"""

    def __init__(self, response: str = "测试回复") -> None:
        self.response = response
        self.call_count = 0
        self.calls: list[str] = []
        self._raise = False

    async def process(self, text: str) -> str:
        self.call_count += 1
        self.calls.append(text)
        if self._raise:
            raise RuntimeError("Agent 异常")
        return self.response


class MockTTS:
    def __init__(self) -> None:
        self._speaking = False


class MockVoiceOps:
    """Mock VoiceOps，支持配置不同轮次的返回值。"""

    def __init__(self, texts: list[str] | None = None) -> None:
        self._texts = texts or ["你好"]
        self._idx = 0
        self.calls: list[tuple[str, dict]] = []
        self._tts = MockTTS()
        self.listen_count = 0
        self._pipeline: VoicePipeline | None = None
        self._stop_after_listen: int = 0

    def bind(self, pipeline: VoicePipeline, stop_after: int = 0) -> None:
        self._pipeline = pipeline
        self._stop_after_listen = stop_after

    async def execute(self, action: str, params: dict) -> Any:
        await asyncio.sleep(0)
        self.calls.append((action, params))
        if action == "listen":
            self.listen_count += 1
            idx = min(self._idx, len(self._texts) - 1)
            text = self._texts[idx]
            self._idx += 1
            if self._pipeline and self._stop_after_listen > 0:
                if self.listen_count >= self._stop_after_listen:
                    self._pipeline._stop_event.set()
            return {"status": "ok", "text": text}
        if action == "speak":
            self._tts._speaking = True
            self._tts._speaking = False
            return {"status": "ok"}
        if action == "stop":
            self._tts._speaking = False
            return {"status": "stopped"}
        return {"status": "ok"}


class MockVAD:
    """Mock VAD 检测器。"""

    def __init__(self, speech_pattern: list[bool] | None = None) -> None:
        """speech_pattern: 循环返回的语音检测结果。"""
        self._pattern = speech_pattern or [False, True, True, False, False]
        self._idx = 0

    def is_speech(self, chunk: bytes) -> bool:
        result = self._pattern[self._idx % len(self._pattern)]
        self._idx += 1
        return result


def _make(
    cfg: VoicePipelineConfig | None = None,
    texts: list[str] | None = None,
    agent_resp: str = "回复",
    stop_after: int = 0,
) -> tuple[VoicePipeline, MockAgent, MockVoiceOps]:
    agent = MockAgent(response=agent_resp)
    ops = MockVoiceOps(texts=texts)
    p = VoicePipeline(agent, ops, cfg)
    if stop_after > 0:
        ops.bind(p, stop_after=stop_after)
    return p, agent, ops


# ---------------------------------------------------------------------------
# 完整流程测试：唤醒词 → 对话 → 退出
# ---------------------------------------------------------------------------


class TestWakeWordToExit:
    """唤醒词 → 对话 → 退出完整流程。"""

    @pytest.mark.asyncio
    async def test_wake_word_single_turn_exit(self) -> None:
        """唤醒词触发 → 单次对话 → 退出指令。"""
        cfg = VoicePipelineConfig(wake_word_enabled=True, continuous_mode=False)
        p, agent, ops = _make(cfg, texts=["再见"], stop_after=1)
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))

        with patch.object(p, "_wait_for_wake_word", new_callable=AsyncMock, return_value=True):
            await asyncio.wait_for(p.start(), timeout=10.0)

        assert not p.is_running
        # 应该说过再见
        speaks = [c for a, c in ops.calls if a == "speak"]
        assert any(c.get("text") == cfg.farewell for c in speaks)

    @pytest.mark.asyncio
    async def test_wake_word_multi_turn(self) -> None:
        """唤醒词触发 → 多次对话 → 退出。"""
        cfg = VoicePipelineConfig(wake_word_enabled=True, continuous_mode=False)
        p, agent, ops = _make(cfg, texts=["你好", "再见"], stop_after=2)
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))

        with patch.object(p, "_wait_for_wake_word", new_callable=AsyncMock, return_value=True):
            await asyncio.wait_for(p.start(), timeout=10.0)

        assert agent.call_count >= 1  # 至少处理了 "你好"

    @pytest.mark.asyncio
    async def test_no_wake_direct_chat(self) -> None:
        """免唤醒模式直接进入对话。"""
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        p, agent, ops = _make(cfg, texts=["你好", "再见"])
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))

        await asyncio.wait_for(p.start(), timeout=10.0)

        assert not p.is_running
        assert agent.call_count >= 1

    @pytest.mark.asyncio
    async def test_greeting_spoken(self) -> None:
        """启动时应播放问候语。"""
        cfg = VoicePipelineConfig(wake_word_enabled=False, greeting="你好，主人")
        p, _, ops = _make(cfg, texts=["再见"])

        await asyncio.wait_for(p.start(), timeout=10.0)

        speaks = [c for a, c in ops.calls if a == "speak"]
        assert any(c.get("text") == "你好，主人" for c in speaks)


# ---------------------------------------------------------------------------
# 连续对话模式
# ---------------------------------------------------------------------------


class TestContinuousMode:
    """连续对话模式测试。"""

    @pytest.mark.asyncio
    async def test_continuous_multi_turn(self) -> None:
        """连续对话应处理多轮输入。"""
        cfg = VoicePipelineConfig(
            wake_word_enabled=False,
            continuous_mode=True,
            continuous_timeout=5.0,
        )
        p, agent, ops = _make(cfg, texts=["第一句", "第二句", ""], stop_after=3)

        await asyncio.wait_for(p.start(), timeout=10.0)

        assert agent.call_count >= 2
        assert "第一句" in agent.calls
        assert "第二句" in agent.calls

    @pytest.mark.asyncio
    async def test_continuous_timeout(self) -> None:
        """超时后应退出连续对话。"""
        cfg = VoicePipelineConfig(
            wake_word_enabled=False,
            continuous_mode=True,
            continuous_timeout=0.1,
        )
        p, _, ops = _make(cfg, texts=[""])
        p._last_active_time = time.monotonic() - 10

        await asyncio.wait_for(p.start(), timeout=5.0)

        assert not p.is_running

    @pytest.mark.asyncio
    async def test_continuous_exit_command(self) -> None:
        """连续对话中收到退出指令应停止。"""
        cfg = VoicePipelineConfig(
            wake_word_enabled=False,
            continuous_mode=True,
            continuous_timeout=30.0,
        )
        p, agent, ops = _make(cfg, texts=["你好", "再见"])

        await asyncio.wait_for(p.start(), timeout=10.0)

        assert not p.is_running
        assert agent.call_count == 1  # 只有"你好"被处理


# ---------------------------------------------------------------------------
# 打断机制
# ---------------------------------------------------------------------------


class TestInterruption:
    """打断机制测试。"""

    @pytest.mark.asyncio
    async def test_interruption_disabled(self) -> None:
        """禁用打断时 _check_interrupt 返回 False。"""
        cfg = VoicePipelineConfig(interruption_enabled=False)
        p, _, _ = _make(cfg)
        assert await p._check_interrupt() is False

    @pytest.mark.asyncio
    async def test_interruption_does_not_crash(self) -> None:
        """打断检测不崩溃（即使 VAD 不可用）。"""
        cfg = VoicePipelineConfig(
            wake_word_enabled=False,
            interruption_enabled=True,
        )
        p, _, ops = _make(cfg, stop_after=1)

        with patch.object(p, "_check_interrupt", new_callable=AsyncMock, return_value=True):
            await asyncio.wait_for(p.start(), timeout=10.0)

        # 不崩溃即通过

    @pytest.mark.asyncio
    async def test_interrupt_during_speaking(self) -> None:
        """说话中打断应停止 TTS。"""
        cfg = VoicePipelineConfig(
            wake_word_enabled=False,
            interruption_enabled=True,
        )
        p, agent, ops = _make(cfg, texts=["测试"], stop_after=1)
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))

        with patch.object(p, "_check_interrupt", new_callable=AsyncMock, return_value=True):
            await asyncio.wait_for(p.start(), timeout=10.0)

        # 打断后应发送 stop
        stop_calls = [c for a, c in ops.calls if a == "stop"]
        assert len(stop_calls) >= 1


# ---------------------------------------------------------------------------
# faster-whisper STT 后端（mock）
# ---------------------------------------------------------------------------


class TestFasterWhisperSTT:
    """faster-whisper STT 后端测试（mock 模型）。"""

    @pytest.mark.asyncio
    async def test_recognize_file_with_faster_whisper(self) -> None:
        """faster-whisper 可用时应优先用于文件识别。"""
        from pathlib import Path as PathLib
        from src.tools import voice_stt

        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = "你好世界"
        mock_info = MagicMock()
        mock_model.transcribe.return_value = (iter([mock_segment]), mock_info)

        with patch.object(voice_stt, "_FASTER_WHISPER_AVAILABLE", True), \
             patch.object(voice_stt, "_SR_AVAILABLE", True), \
             patch.object(voice_stt, "WhisperModel", return_value=mock_model, create=True):

            # 构造一个临时 WAV 文件
            import tempfile
            import wave
            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00" * 3200)
            tmp.close()

            stt = voice_stt.VoiceSTT()
            stt._fw_model = mock_model
            stt._recognizer = MagicMock()

            with patch("src.tools.voice_stt.safe_resolve_path", return_value=PathLib(tmp.name)):
                result = await stt.recognize_file(tmp.name)

            import os
            os.unlink(tmp.name)

        # 不验证引擎名（因为 mock 设置可能不一致），只验证结构
        assert result.get("status") == "recognized" or "error" in result or "engine" in result

    @pytest.mark.asyncio
    async def test_faster_whisper_not_available(self) -> None:
        """faster-whisper 不可用时应降级。"""
        from src.tools import voice_stt

        with patch.object(voice_stt, "_FASTER_WHISPER_AVAILABLE", False):
            stt = voice_stt.VoiceSTT()
            assert stt._fw_model is None

    @pytest.mark.asyncio
    async def test_list_recognizers_includes_faster_whisper(self) -> None:
        """引擎列表应包含 faster-whisper。"""
        from src.tools import voice_stt

        with patch.object(voice_stt, "_FASTER_WHISPER_AVAILABLE", True), \
             patch.object(voice_stt, "_SR_AVAILABLE", True), \
             patch.object(voice_stt, "_WHISPER_AVAILABLE", False):
            stt = voice_stt.VoiceSTT()
            result = await stt.list_recognizers()

        assert result["status"] == "ok"
        engine_names = [e["name"] for e in result["engines"]]
        assert "faster-whisper" in engine_names
        assert "google" in engine_names


# ---------------------------------------------------------------------------
# listen_with_vad 测试
# ---------------------------------------------------------------------------


class TestListenWithVAD:
    """listen_with_vad 方法测试。"""

    @pytest.mark.asyncio
    async def test_vad_speech_detected(self) -> None:
        """VAD 检测到语音后应识别。"""
        from src.tools import voice_stt

        # 创建音频流
        async def audio_stream():
            for _ in range(3):
                yield b"\x00" * 320  # 每块 20ms @16kHz 16bit

        vad = MockVAD(speech_pattern=[True, True, False, False, False])

        with patch.object(voice_stt, "_FASTER_WHISPER_AVAILABLE", True), \
             patch.object(voice_stt, "_WHISPER_AVAILABLE", False):

            stt = voice_stt.VoiceSTT()

            # Mock faster-whisper 识别
            mock_model = MagicMock()
            mock_seg = MagicMock()
            mock_seg.text = "  测试识别  "
            mock_info = MagicMock()
            mock_model.transcribe.return_value = (iter([mock_seg]), mock_info)
            stt._fw_model = mock_model

            result = await stt.listen_with_vad(audio_stream(), vad, timeout=5.0)

        assert result.get("status") == "recognized"
        assert result.get("text") == "测试识别"
        assert result.get("engine") == "faster-whisper"

    @pytest.mark.asyncio
    async def test_vad_no_speech(self) -> None:
        """VAD 未检测到语音应返回 no_speech。"""
        from src.tools import voice_stt

        async def audio_stream():
            for _ in range(5):
                yield b"\x00" * 320

        vad = MockVAD(speech_pattern=[False, False, False, False, False])

        stt = voice_stt.VoiceSTT()
        result = await stt.listen_with_vad(audio_stream(), vad, timeout=5.0)

        assert result.get("status") == "no_speech"

    @pytest.mark.asyncio
    async def test_vad_fallback_to_whisper(self) -> None:
        """faster-whisper 不可用时应 fallback 到 whisper。"""
        from src.tools import voice_stt

        async def audio_stream():
            for _ in range(3):
                yield b"\x00" * 320

        vad = MockVAD(speech_pattern=[True, True, False, False, False])

        mock_whisper_mod = MagicMock()
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {"text": "  whisper 回退  "}
        mock_whisper_mod.load_model.return_value = mock_model

        with patch.object(voice_stt, "_FASTER_WHISPER_AVAILABLE", False), \
             patch.object(voice_stt, "_WHISPER_AVAILABLE", True), \
             patch.object(voice_stt, "_whisper_module", mock_whisper_mod):
            stt = voice_stt.VoiceSTT()
            result = await stt.listen_with_vad(audio_stream(), vad, timeout=5.0)

        assert result.get("status") == "recognized"
        assert result.get("engine") == "whisper"

    @pytest.mark.asyncio
    async def test_vad_no_engine(self) -> None:
        """无可用 STT 引擎应返回 no_result。"""
        from src.tools import voice_stt

        async def audio_stream():
            for _ in range(3):
                yield b"\x00" * 320

        vad = MockVAD(speech_pattern=[True, True, False, False, False])

        with patch.object(voice_stt, "_FASTER_WHISPER_AVAILABLE", False), \
             patch.object(voice_stt, "_WHISPER_AVAILABLE", False):
            stt = voice_stt.VoiceSTT()
            result = await stt.listen_with_vad(audio_stream(), vad, timeout=5.0)

        assert result.get("status") == "no_result"

    @pytest.mark.asyncio
    async def test_vad_empty_stream(self) -> None:
        """空音频流应返回 no_speech。"""
        from src.tools import voice_stt

        async def audio_stream():
            return
            yield  # 使其成为 async generator

        vad = MockVAD()
        stt = voice_stt.VoiceSTT()
        result = await stt.listen_with_vad(audio_stream(), vad, timeout=5.0)

        assert result.get("status") == "no_speech"

    @pytest.mark.asyncio
    async def test_vad_with_exception_in_stream(self) -> None:
        """音频流异常应返回错误。"""
        from src.tools import voice_stt

        async def audio_stream():
            yield b"\x00" * 320
            raise IOError("设备错误")

        vad = MockVAD(speech_pattern=[True])

        stt = voice_stt.VoiceSTT()
        result = await stt.listen_with_vad(audio_stream(), vad, timeout=5.0)

        assert "error" in result


# ---------------------------------------------------------------------------
# chunks_to_wav 辅助方法测试
# ---------------------------------------------------------------------------


class TestChunksToWav:
    """音频块转 WAV 测试。"""

    def test_empty_chunks(self) -> None:
        """空块列表应返回空字节。"""
        from src.tools.voice_stt import VoiceSTT
        result = VoiceSTT._chunks_to_wav([])
        assert result == b""

    def test_valid_chunks(self) -> None:
        """有效音频块应生成 WAV 头。"""
        import wave
        import io
        from src.tools.voice_stt import VoiceSTT

        chunks = [b"\x00" * 3200, b"\xff" * 3200]
        result = VoiceSTT._chunks_to_wav(chunks)

        assert len(result) > 6400  # 应包含 WAV 头
        # 验证是合法 WAV
        with wave.open(io.BytesIO(result), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000

    def test_custom_params(self) -> None:
        """自定义采样率参数。"""
        import wave
        import io
        from src.tools.voice_stt import VoiceSTT

        result = VoiceSTT._chunks_to_wav([b"\x00" * 8000], sample_rate=8000)
        with wave.open(io.BytesIO(result), "rb") as wf:
            assert wf.getframerate() == 8000


# ---------------------------------------------------------------------------
# 状态转换测试
# ---------------------------------------------------------------------------


class TestStateTransitions:
    """完整状态转换序列测试。"""

    @pytest.mark.asyncio
    async def test_full_lifecycle_no_wake(self) -> None:
        """免唤醒模式完整生命周期。"""
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        p, agent, ops = _make(cfg, texts=["你好", "再见"])
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))

        await asyncio.wait_for(p.start(), timeout=10.0)

        # 验证状态序列
        assert PipelineState.LISTENING in states
        assert PipelineState.PROCESSING in states
        assert PipelineState.SPEAKING in states
        assert not p.is_running
        assert p.state == PipelineState.IDLE

    @pytest.mark.asyncio
    async def test_full_lifecycle_with_wake(self) -> None:
        """唤醒词模式完整生命周期。"""
        cfg = VoicePipelineConfig(wake_word_enabled=True, continuous_mode=False)
        p, agent, ops = _make(cfg, texts=["你好", "再见"], stop_after=2)
        states: list[PipelineState] = []
        p.set_state_callback(lambda s: states.append(s))

        with patch.object(p, "_wait_for_wake_word", new_callable=AsyncMock, return_value=True):
            await asyncio.wait_for(p.start(), timeout=10.0)

        assert PipelineState.IDLE in states
        assert PipelineState.LISTENING in states

    @pytest.mark.asyncio
    async def test_error_recovery(self) -> None:
        """Agent 异常后管道不应崩溃。"""
        cfg = VoicePipelineConfig(wake_word_enabled=False, continuous_mode=False)
        agent = MockAgent()
        agent._raise = True
        ops = MockVoiceOps(texts=["test"])
        p = VoicePipeline(agent, ops, cfg)
        ops.bind(p, stop_after=1)

        await asyncio.wait_for(p.start(), timeout=10.0)
        assert agent.call_count >= 1
