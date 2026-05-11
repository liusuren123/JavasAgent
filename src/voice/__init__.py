"""音频流管理与语音活动检测包。

提供麦克风音频流录制、语音端点检测和唤醒词检测能力，
为语音助手提供底层音频基础设施。

Usage::

    from src.voice import AudioStream, VoiceActivityDetector, WakeWordDetector

    vad = VoiceActivityDetector(threshold=0.5)
    stream = AudioStream(sample_rate=16000)
    detector = WakeWordDetector(keywords=["jarvis"])

    wav_data = await stream.record_until_silence(vad)
"""

from src.voice.audio_stream import AudioStream
from src.voice.vad import VoiceActivityDetector
from src.voice.wake_word import WakeWordDetector

__all__ = ["AudioStream", "VoiceActivityDetector", "WakeWordDetector"]
