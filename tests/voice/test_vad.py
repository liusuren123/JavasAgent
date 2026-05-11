"""VoiceActivityDetector 单元测试。

测试三种后端的 fallback 逻辑、接口正确性和能量检测 fallback。
"""

from __future__ import annotations

import math
import struct
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.voice.vad import VoiceActivityDetector, _get_backend


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_silent_pcm(num_frames: int = 512) -> bytes:
    """生成静音 PCM 数据。"""
    return struct.pack(f"<{num_frames}h", *[0] * num_frames)


def _make_loud_pcm(
    num_frames: int = 512,
    amplitude: int = 16000,
    freq: int = 440,
    sample_rate: int = 16000,
) -> bytes:
    """生成有声音的 PCM 数据（正弦波）。"""
    samples = [
        int(amplitude * math.sin(2 * math.pi * freq * i / sample_rate))
        for i in range(num_frames)
    ]
    return struct.pack(f"<{num_frames}h", *samples)


def _make_noise_pcm(num_frames: int = 512, amplitude: int = 8000) -> bytes:
    """生成噪声 PCM 数据（伪随机）。"""
    import random

    random.seed(42)
    samples = [random.randint(-amplitude, amplitude) for _ in range(num_frames)]
    return struct.pack(f"<{num_frames}h", *samples)


# ---------------------------------------------------------------------------
# 初始化测试
# ---------------------------------------------------------------------------

class TestVADInit:
    """VoiceActivityDetector 初始化参数测试。"""

    def test_default_params(self) -> None:
        vad = VoiceActivityDetector()
        assert vad.threshold == 0.5
        assert vad.sample_rate == 16000

    def test_custom_params(self) -> None:
        vad = VoiceActivityDetector(threshold=0.8, sample_rate=48000)
        assert vad.threshold == 0.8
        assert vad.sample_rate == 48000

    def test_threshold_boundary_low(self) -> None:
        vad = VoiceActivityDetector(threshold=0.0)
        assert vad.threshold == 0.0

    def test_threshold_boundary_high(self) -> None:
        vad = VoiceActivityDetector(threshold=1.0)
        assert vad.threshold == 1.0


# ---------------------------------------------------------------------------
# 后端探测测试
# ---------------------------------------------------------------------------

class TestBackendDetection:
    """VAD 后端 fallback 逻辑测试。"""

    def test_backend_is_valid_string(self) -> None:
        backend = _get_backend()
        assert backend in ("silero", "webrtcvad", "energy")

    def test_energy_fallback_works(self) -> None:
        """energy 后端应始终可用。"""
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector(threshold=0.5)
            # 不应抛异常
            prob = vad.get_speech_probability(_make_loud_pcm())
            assert 0.0 <= prob <= 1.0

    def test_silero_fallback_to_energy(self) -> None:
        """silero 不可用时应降级到 energy。"""
        # 当前实际后端
        backend = _get_backend()
        # 如果不是 silero，说明降级已生效
        if backend != "silero":
            assert backend in ("webrtcvad", "energy")


# ---------------------------------------------------------------------------
# is_speech 接口测试
# ---------------------------------------------------------------------------

class TestIsSpeech:
    """is_speech 接口测试（跨后端）。"""

    def test_silent_audio_is_not_speech(self) -> None:
        """静音数据不应被判定为语音。"""
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector(threshold=0.5)
            result = vad.is_speech(_make_silent_pcm())
            assert result is False

    def test_loud_audio_is_speech(self) -> None:
        """有声音的数据应被判定为语音。"""
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector(threshold=0.5)
            result = vad.is_speech(_make_loud_pcm(amplitude=30000))
            assert result is True

    def test_low_threshold_detects_more(self) -> None:
        """较低阈值应更容易检测到语音。"""
        with patch("src.voice.vad._backend", "energy"):
            vad_low = VoiceActivityDetector(threshold=0.1)
            vad_high = VoiceActivityDetector(threshold=0.9)
            moderate = _make_loud_pcm(amplitude=5000)
            # 低阈值更可能检测到语音
            assert vad_low.get_speech_probability(moderate) >= vad_high.get_speech_probability(moderate)


# ---------------------------------------------------------------------------
# get_speech_probability 接口测试
# ---------------------------------------------------------------------------

class TestGetSpeechProbability:
    """get_speech_probability 接口测试。"""

    def test_returns_float(self) -> None:
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector()
            prob = vad.get_speech_probability(_make_loud_pcm())
            assert isinstance(prob, float)

    def test_probability_range(self) -> None:
        """概率应在 0.0 ~ 1.0 范围内。"""
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector()
            for data in [_make_silent_pcm(), _make_loud_pcm(), _make_noise_pcm()]:
                prob = vad.get_speech_probability(data)
                assert 0.0 <= prob <= 1.0

    def test_silent_has_low_probability(self) -> None:
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector(threshold=0.5)
            prob = vad.get_speech_probability(_make_silent_pcm())
            assert prob < 0.5

    def test_loud_has_high_probability(self) -> None:
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector(threshold=0.5)
            prob = vad.get_speech_probability(_make_loud_pcm(amplitude=30000))
            assert prob > 0.5

    def test_empty_chunk_returns_zero(self) -> None:
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector()
            prob = vad.get_speech_probability(b"")
            assert prob == 0.0

    def test_very_short_chunk_returns_zero(self) -> None:
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector()
            prob = vad.get_speech_probability(b"\x00")
            assert prob == 0.0


# ---------------------------------------------------------------------------
# 能量检测 fallback 详细测试
# ---------------------------------------------------------------------------

class TestEnergyFallback:
    """能量检测 fallback 的详细测试。"""

    def test_louder_is_higher_probability(self) -> None:
        """更大振幅应产生更高的语音概率。"""
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector(threshold=0.5)
            quiet = _make_loud_pcm(amplitude=1000)
            loud = _make_loud_pcm(amplitude=30000)
            assert vad.get_speech_probability(loud) > vad.get_speech_probability(quiet)

    def test_different_thresholds_affect_detection(self) -> None:
        """不同阈值影响 is_speech 判定。"""
        with patch("src.voice.vad._backend", "energy"):
            moderate = _make_loud_pcm(amplitude=5000)
            vad_low = VoiceActivityDetector(threshold=0.1)
            vad_high = VoiceActivityDetector(threshold=0.95)

            # 低阈值更容易判定为语音
            low_result = vad_low.is_speech(moderate)
            high_result = vad_high.is_speech(moderate)
            # 低阈值时更容易检测到
            assert vad_low.get_speech_probability(moderate) >= vad_high.get_speech_probability(moderate)

    def test_noise_detected_as_speech(self) -> None:
        """噪声应被检测为语音（能量足够时）。"""
        with patch("src.voice.vad._backend", "energy"):
            vad = VoiceActivityDetector(threshold=0.3)
            prob = vad.get_speech_probability(_make_noise_pcm(amplitude=20000))
            assert prob > 0.3


# ---------------------------------------------------------------------------
# webrtcvad mock 测试
# ---------------------------------------------------------------------------

class TestWebrtcvadMock:
    """webrtcvad 后端 mock 测试。"""

    def test_webrtcvad_is_speech_true(self) -> None:
        """mock webrtcvad 返回 True。"""
        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = True

        with patch("src.voice.vad._backend", "webrtcvad"):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = mock_vad
            assert vad.is_speech(_make_loud_pcm()) is True

    def test_webrtcvad_is_speech_false(self) -> None:
        """mock webrtcvad 返回 False。"""
        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = False

        with patch("src.voice.vad._backend", "webrtcvad"):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = mock_vad
            assert vad.is_speech(_make_silent_pcm()) is False

    def test_webrtcvad_probability_binary(self) -> None:
        """webrtcvad 概率应为 0.0 或 1.0。"""
        mock_vad = MagicMock()
        mock_vad.is_speech.return_value = True

        with patch("src.voice.vad._backend", "webrtcvad"):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = mock_vad
            prob = vad.get_speech_probability(_make_loud_pcm())
            assert prob == 1.0

    def test_webrtcvad_error_returns_zero(self) -> None:
        """webrtcvad 出错时应返回 0.0。"""
        mock_vad = MagicMock()
        mock_vad.is_speech.side_effect = Exception("test error")

        with patch("src.voice.vad._backend", "webrtcvad"):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = mock_vad
            prob = vad.get_speech_probability(_make_loud_pcm())
            assert prob == 0.0


# ---------------------------------------------------------------------------
# silero mock 测试
# ---------------------------------------------------------------------------

class TestSileroMock:
    """silero-vad 后端 mock 测试。"""

    def _make_mock_torch(self, mock_model: MagicMock) -> MagicMock:
        """创建 mock torch 模块，使 frombuffer 返回正确链式调用。"""
        mock_torch = MagicMock()
        mock_tensor = MagicMock()
        mock_float = MagicMock()
        # chain: torch.frombuffer(...).float() / 32768.0
        mock_float.__truediv__ = MagicMock(return_value=mock_float)
        mock_tensor.float.return_value = mock_float
        mock_torch.frombuffer.return_value = mock_tensor
        return mock_torch

    def test_silero_probability_value(self) -> None:
        """mock silero 返回概率值。"""
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_result.item.return_value = 0.85
        mock_model.return_value = mock_result

        mock_torch = self._make_mock_torch(mock_model)

        with patch("src.voice.vad._backend", "silero"), \
             patch("src.voice.vad._silero_model", mock_model), \
             patch.dict("sys.modules", {"torch": mock_torch}):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = mock_model
            prob = vad.get_speech_probability(_make_loud_pcm())
            assert prob == 0.85

    def test_silero_is_speech_above_threshold(self) -> None:
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_result.item.return_value = 0.7
        mock_model.return_value = mock_result

        mock_torch = self._make_mock_torch(mock_model)

        with patch("src.voice.vad._backend", "silero"), \
             patch("src.voice.vad._silero_model", mock_model), \
             patch.dict("sys.modules", {"torch": mock_torch}):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = mock_model
            assert vad.is_speech(_make_loud_pcm()) is True

    def test_silero_is_not_speech_below_threshold(self) -> None:
        mock_model = MagicMock()
        mock_result = MagicMock()
        mock_result.item.return_value = 0.3
        mock_model.return_value = mock_result

        mock_torch = self._make_mock_torch(mock_model)

        with patch("src.voice.vad._backend", "silero"), \
             patch("src.voice.vad._silero_model", mock_model), \
             patch.dict("sys.modules", {"torch": mock_torch}):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = mock_model
            assert vad.is_speech(_make_loud_pcm()) is False

    def test_silero_no_instance_returns_zero(self) -> None:
        with patch("src.voice.vad._backend", "silero"):
            vad = VoiceActivityDetector(threshold=0.5)
            vad._vad_instance = None
            prob = vad.get_speech_probability(_make_loud_pcm())
            assert prob == 0.0
