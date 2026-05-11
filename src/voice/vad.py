"""语音活动检测（VAD）。

提供三级降级策略：
1. silero-vad（基于 PyTorch，精度最高）
2. webrtcvad（轻量 C 库，精度适中）
3. 能量检测（纯 Python fallback，最基础）

缺少依赖时自动降级，不会崩溃。
"""

from __future__ import annotations

import math
import struct
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# 后端探测
# ---------------------------------------------------------------------------
_backend: str = "energy"
_silero_model: Any = None
_webrtcvad: Any = None

# 尝试 silero-vad（依赖 torch）
try:
    import torch as _torch  # type: ignore[import-untyped]

    _silero_model, _ = _torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        trust_repo=True,
    )
    _silero_model.eval()
    _backend = "silero"
    logger.info("VAD 后端: silero-vad")
except Exception:  # noqa: BLE001
    # 尝试 webrtcvad
    try:
        import webrtcvad as _wv_mod  # type: ignore[import-untyped]

        _webrtcvad = _wv_mod
        _backend = "webrtcvad"
        logger.info("VAD 后端: webrtcvad")
    except ImportError:
        logger.info("VAD 后端: energy（纯 Python fallback）")


def _get_backend() -> str:
    """返回当前 VAD 后端名称。"""
    return _backend


class VoiceActivityDetector:
    """语音活动检测。

    Parameters
    ----------
    threshold : float
        语音判定阈值（0.0 ~ 1.0）。默认 0.5。
        silero/webrtcvad 后端使用此阈值作为概率/判定门限；
        energy 后端使用此阈值映射为 RMS 能量门限。
    sample_rate : int
        音频采样率，默认 16000 Hz。
    """

    def __init__(
        self,
        threshold: float = 0.5,
        sample_rate: int = 16000,
    ) -> None:
        self.threshold = threshold
        self.sample_rate = sample_rate
        self._vad_instance: Any = None

        if _backend == "webrtcvad" and _webrtcvad is not None:
            # aggressiveness: 0~3，threshold 越高越激进
            agg = min(3, max(0, int(threshold * 3)))
            self._vad_instance = _webrtcvad.Vad(agg)
        elif _backend == "silero" and _silero_model is not None:
            self._vad_instance = _silero_model

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def is_speech(self, audio_chunk: bytes) -> bool:
        """判断音频帧是否包含语音。

        Parameters
        ----------
        audio_chunk : bytes
            PCM 16-bit 单声道音频数据。

        Returns
        -------
        bool
            True 表示检测到语音。
        """
        prob = self.get_speech_probability(audio_chunk)
        return prob >= self.threshold

    def get_speech_probability(self, audio_chunk: bytes) -> float:
        """返回语音概率 0.0 ~ 1.0。

        Parameters
        ----------
        audio_chunk : bytes
            PCM 16-bit 单声道音频数据。

        Returns
        -------
        float
            语音概率，0.0 表示无声，1.0 表示确定有语音。
        """
        if _backend == "silero":
            return self._probability_silero(audio_chunk)
        elif _backend == "webrtcvad":
            return self._probability_webrtcvad(audio_chunk)
        else:
            return self._probability_energy(audio_chunk)

    # ------------------------------------------------------------------
    # silero-vad
    # ------------------------------------------------------------------

    def _probability_silero(self, audio_chunk: bytes) -> float:
        """使用 silero-vad 计算语音概率。"""
        if self._vad_instance is None:
            return 0.0
        try:
            import torch  # type: ignore[import-untyped]

            audio_tensor = torch.frombuffer(audio_chunk, dtype=torch.int16)
            audio_float = audio_tensor.float() / 32768.0
            prob = self._vad_instance(audio_float, self.sample_rate).item()
            return float(prob)
        except Exception as exc:  # noqa: BLE001
            logger.warning("silero-vad 推理出错: {}", exc)
            return 0.0

    # ------------------------------------------------------------------
    # webrtcvad
    # ------------------------------------------------------------------

    def _probability_webrtcvad(self, audio_chunk: bytes) -> float:
        """使用 webrtcvad 判定，返回 0.0 或 1.0。"""
        if self._vad_instance is None:
            return 0.0
        try:
            is_speech = self._vad_instance.is_speech(audio_chunk, self.sample_rate)
            return 1.0 if is_speech else 0.0
        except Exception as exc:  # noqa: BLE101
            logger.warning("webrtcvad 检测出错: {}", exc)
            return 0.0

    # ------------------------------------------------------------------
    # 能量检测 fallback
    # ------------------------------------------------------------------

    def _probability_energy(self, audio_chunk: bytes) -> float:
        """基于 RMS 能量的语音概率估算。

        计算 16-bit PCM 数据的 RMS 值，映射到 0.0~1.0。
        使用 sigmoid 变换将能量值映射为概率。
        """
        if len(audio_chunk) < 2:
            return 0.0

        # 解析 16-bit PCM 样本
        num_samples = len(audio_chunk) // 2
        samples = struct.unpack(f"<{num_samples}h", audio_chunk[: num_samples * 2])

        if not samples:
            return 0.0

        # 计算 RMS
        sum_sq = sum(s * s for s in samples)
        rms = math.sqrt(sum_sq / len(samples))

        # 归一化到 0~1（16-bit 最大振幅 32768）
        normalized = rms / 32768.0

        # sigmoid 映射：使用 threshold 调整灵敏度
        # 基准能量门限 = threshold * 0.1（可调）
        energy_threshold = self.threshold * 0.1
        if energy_threshold <= 0:
            energy_threshold = 0.01

        # 使用 tanh 做平滑映射
        k = 10.0 / energy_threshold  # 斜率
        probability = 0.5 * (1.0 + math.tanh(k * (normalized - energy_threshold)))

        return max(0.0, min(1.0, probability))
