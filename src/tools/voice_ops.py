"""语音交互门面模块。

提供 TTS 语音合成 + STT 语音识别的统一入口。
实际实现委托给 voice_tts / voice_stt 子模块。

Usage::

    voice = VoiceOps()
    result = await voice.execute("speak", {"text": "你好世界"})
    result = await voice.execute("listen", {"timeout": 5.0})
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.tools.voice_stt import VoiceSTT
from src.tools.voice_tts import VoiceTTS


class VoiceOps:
    """语音交互工具集（门面）。

    支持 TTS 语音合成和 STT 语音识别操作。

    Usage::

        voice = VoiceOps()
        result = await voice.execute("speak", {"text": "你好世界"})
    """

    def __init__(self) -> None:
        """初始化语音交互模块。"""
        self._tts = VoiceTTS()
        self._stt = VoiceSTT()

    async def execute(self, action: str, params: dict[str, Any]) -> Any:
        """执行语音交互操作。

        Args:
            action: 操作类型
            params: 操作参数

        Returns:
            操作结果

        支持的 action:
            - speak: TTS 朗读文本
            - list_voices: 列出可用 TTS 语音引擎
            - save_to_file: TTS 保存到 WAV
            - stop: 停止当前朗读
            - listen: STT 从麦克风识别
            - recognize_file: STT 识别音频文件
            - list_recognizers: 列出可用 STT 识别引擎
        """
        tts_actions = {
            "speak": self._tts.speak,
            "list_voices": self._tts.list_voices,
            "save_to_file": self._tts.save_to_file,
            "stop": self._tts.stop,
        }
        stt_actions = {
            "listen": self._stt.listen,
            "recognize_file": self._stt.recognize_file,
            "list_recognizers": self._stt.list_recognizers,
        }

        all_actions = {**tts_actions, **stt_actions}

        handler = all_actions.get(action)
        if handler is None:
            logger.error(f"未知语音操作: {action}")
            return {
                "error": f"未知操作: {action}",
                "available_actions": sorted(all_actions.keys()),
            }

        try:
            return await handler(**params)
        except TypeError as e:
            logger.error(f"参数错误: {e}")
            return {"error": f"参数错误: {e}"}
