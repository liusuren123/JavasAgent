"""音频流管理与语音活动检测包。

提供麦克风音频流录制和语音端点检测能力，
为语音助手提供底层音频基础设施。

Usage::

    from src.voice import AudioStream, VoiceActivityDetector

    vad = VoiceActivityDetector(threshold=0.5)
    stream = AudioStream(sample_rate=16000)

    wav_data = await stream.record_until_silence(vad)
"""

from src.voice.audio_stream import AudioStream
from src.voice.vad import VoiceActivityDetector

__all__ = ["AudioStream", "VoiceActivityDetector"]
