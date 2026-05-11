"""麦克风音频流管理。

提供音频录制和流式回调功能，优先使用 pyaudio，
不可用时自动降级到 sounddevice。两者均不可用则
实例化正常但 start() 抛出 RuntimeError。

WAV 数据生成使用标准库 struct/wave 模块，
确保输出格式兼容所有播放器。
"""

from __future__ import annotations

import asyncio
import io
import struct
import wave
from typing import Callable

from loguru import logger

# ---------------------------------------------------------------------------
# 后端探测：pyaudio > sounddevice > 不可用
# ---------------------------------------------------------------------------
_backend: str | None = None
_pyaudio = None
_sounddevice = None

try:
    import pyaudio as _pyaudio_mod  # type: ignore[import-untyped]

    _pyaudio = _pyaudio_mod
    _backend = "pyaudio"
except ImportError:
    try:
        import sounddevice as _sd_mod  # type: ignore[import-untyped]

        _sounddevice = _sd_mod
        _backend = "sounddevice"
    except ImportError:
        _backend = None


def _get_backend() -> str | None:
    """返回当前可用的音频后端名称。"""
    return _backend


class AudioStream:
    """麦克风音频流管理。

    Parameters
    ----------
    sample_rate : int
        采样率，默认 16000 Hz。
    channels : int
        声道数，默认 1（单声道）。
    chunk_size : int
        每次回调读取的帧数，默认 512。
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 512,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self._stream: object | None = None
        self._running = False
        self._pyaudio_instance: object | None = None

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    async def start(self, callback: Callable[[bytes], None]) -> None:
        """启动音频流，每个 chunk 调用 *callback*。

        Raises
        ------
        RuntimeError
            没有可用的音频后端时抛出。
        """
        if _backend is None:
            raise RuntimeError(
                "无可用的音频后端，请安装 pyaudio 或 sounddevice"
            )
        self._running = True

        if _backend == "pyaudio":
            await self._start_pyaudio(callback)
        else:
            await self._start_sounddevice(callback)

    async def stop(self) -> None:
        """停止音频流并释放资源。"""
        self._running = False
        if self._stream is not None:
            try:
                if _backend == "pyaudio":
                    self._stream.stop_stream()  # type: ignore[union-attr]
                    self._stream.close()  # type: ignore[union-attr]
                    if self._pyaudio_instance is not None:
                        self._pyaudio_instance.terminate()  # type: ignore[union-attr]
                else:
                    _sounddevice.stop()  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                logger.warning("停止音频流时出错: {}", exc)
            finally:
                self._stream = None
                self._pyaudio_instance = None

    async def record_until_silence(
        self,
        vad: object,
        max_duration: float = 30.0,
        silence_threshold: float = 1.5,
    ) -> bytes:
        """录音直到检测到静音，返回完整 WAV 数据。

        Parameters
        ----------
        vad :
            语音活动检测对象，需提供 ``is_speech(chunk) -> bool``。
        max_duration :
            最大录音时长（秒），超时自动停止。默认 30。
        silence_threshold :
            连续静音多少秒后认为录音结束。默认 1.5。

        Returns
        -------
        bytes
            标准 WAV 格式的完整音频数据。
        """
        chunks: list[bytes] = []
        silence_start: float | None = None
        total_duration = 0.0
        seconds_per_chunk = self.chunk_size / self.sample_rate
        loop = asyncio.get_running_loop()

        def _on_chunk(data: bytes) -> None:
            nonlocal silence_start, total_duration
            if not self._running:
                return
            chunks.append(data)
            total_duration += seconds_per_chunk

            is_speech = vad.is_speech(data)  # type: ignore[union-attr]
            if is_speech:
                silence_start = None
            else:
                if silence_start is None:
                    silence_start = total_duration - seconds_per_chunk

        await self.start(_on_chunk)
        try:
            while self._running:
                await asyncio.sleep(0.05)
                if total_duration >= max_duration:
                    logger.debug("录音达到最大时长 {:.1f}s", max_duration)
                    break
                if silence_start is not None:
                    silence_dur = total_duration - silence_start
                    if silence_dur >= silence_threshold:
                        logger.debug("检测到静音 {:.1f}s，停止录音", silence_dur)
                        break
        finally:
            await self.stop()

        return self._chunks_to_wav(chunks)

    # ------------------------------------------------------------------
    # WAV 生成
    # ------------------------------------------------------------------

    def _chunks_to_wav(self, chunks: list[bytes]) -> bytes:
        """将 PCM 数据块列表合并为标准 WAV 字节流。"""
        raw = b"".join(chunks)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(raw)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # 后端实现
    # ------------------------------------------------------------------

    async def _start_pyaudio(self, callback: Callable[[bytes], None]) -> None:
        """使用 PyAudio 后端启动录音。"""
        pa = _pyaudio.PyAudio()  # type: ignore[union-attr]
        self._pyaudio_instance = pa

        loop = asyncio.get_running_loop()

        def _pyaudio_cb(
            in_data: bytes, frame_count: int, time_info: object, status: int
        ) -> tuple[None, int]:
            if self._running:
                loop.call_soon_threadsafe(callback, in_data)
            return (None, _pyaudio.paContinue)  # type: ignore[union-attr]

        self._stream = pa.open(
            format=_pyaudio.paInt16,  # type: ignore[union-attr]
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
            stream_callback=_pyaudio_cb,
        )
        if self._stream is not None:
            self._stream.start_stream()  # type: ignore[union-attr]

    async def _start_sounddevice(
        self, callback: Callable[[bytes], None]
    ) -> None:
        """使用 sounddevice 后端启动录音。"""
        loop = asyncio.get_running_loop()

        def _sd_cb(
            indata: object, frames: int, time_info: object, status: int
        ) -> None:
            if self._running:
                import numpy as np  # type: ignore[import-untyped]

                data = (indata * 32767).astype(np.int16).tobytes()  # type: ignore[union-attr]
                loop.call_soon_threadsafe(callback, data)

        self._stream = _sounddevice.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.chunk_size,
            dtype="float32",
            callback=_sd_cb,
        )
        self._stream.start()  # type: ignore[union-attr]
