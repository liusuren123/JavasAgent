"""TTS 语音合成工具。

使用 Windows SAPI (COM 接口) 进行本地语音合成，无需外部 API。
在非 Windows 平台上提供 graceful 降级（返回 unsupported 错误）。

Usage::

    tts = VoiceTTS()
    result = await tts.speak("你好，世界")
    voices = await tts.list_voices()
    result = await tts.save_to_file("测试", "output.wav")
"""

from __future__ import annotations

import asyncio
import platform
import threading
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# 平台检测：仅 Windows 支持SAPI COM
# ---------------------------------------------------------------------------
_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    try:
        import win32com.client  # type: ignore[import-untyped]
        import pythoncom  # type: ignore[import-untyped]

        _SAPI_AVAILABLE = True
    except ImportError:
        _SAPI_AVAILABLE = False
        logger.warning("win32com 未安装，TTS 功能不可用。请安装 pywin32。")
else:
    _SAPI_AVAILABLE = False


def _unsupported() -> dict[str, Any]:
    """返回平台不支持的结果。"""
    return {
        "error": "TTS 仅支持 Windows 平台（SAPI COM 接口）",
        "platform": platform.system(),
    }


class VoiceTTS:
    """TTS 语音合成工具（Windows SAPI）。

    使用 Windows SAPI SpVoice COM 对象实现文本朗读、语音引擎列表、
    保存到 WAV 文件等功能。speak 方法异步执行，不阻塞主循环。

    Attributes:
        _voice: SAPI SpVoice COM 对象（仅 Windows 可用）
        _speaking: 当前是否正在朗读
        _speak_thread: 当前朗读线程
    """

    def __init__(self) -> None:
        """初始化 TTS 引擎。"""
        self._voice: Any = None
        self._speaking: bool = False
        self._speak_thread: threading.Thread | None = None
        self._stop_flag: threading.Event = threading.Event()

        if _SAPI_AVAILABLE:
            try:
                self._voice = win32com.client.Dispatch("SAPI.SpVoice")
                logger.debug("SAPI SpVoice 初始化成功")
            except Exception as e:
                logger.error(f"SAPI SpVoice 初始化失败: {e}")
                self._voice = None

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    async def speak(
        self,
        text: str,
        voice_name: str | None = None,
        rate: int = 0,
        volume: int = 100,
    ) -> dict[str, Any]:
        """朗读文本（异步，不阻塞调用者）。

        Args:
            text: 要朗读的文本内容
            voice_name: 语音引擎名称（可选，默认使用系统默认语音）
            rate: 语速，范围 -10 到 10，默认 0（正常语速）
            volume: 音量，范围 0 到 100，默认 100

        Returns:
            操作结果字典::

                {
                    "status": "speaking",
                    "text": "朗读的文本",
                    "voice": "语音名称",
                    "rate": 0,
                    "volume": 100
                }
        """
        if not _SAPI_AVAILABLE or self._voice is None:
            return _unsupported()

        if not text or not text.strip():
            return {"error": "文本内容不能为空"}

        # 校验参数范围
        rate = max(-10, min(10, rate))
        volume = max(0, min(100, volume))

        # 如果正在朗读，先停止（注意：不能在 async 方法中 await 调用自己，
        # 因为 _speaking 在这里设为 True 后 stop 会重置它）
        if self._speaking:
            self._stop_flag.set()
            try:
                self._voice.Speak("", 2)
            except Exception:
                pass
            self._speaking = False

        self._stop_flag.clear()

        def _speak_sync() -> None:
            """在子线程中同步执行 SAPI Speak。"""
            try:
                pythoncom.CoInitialize()
                voice = win32com.client.Dispatch("SAPI.SpVoice")

                # 设置语音引擎
                if voice_name:
                    self._set_voice(voice, voice_name)

                voice.Rate = rate
                voice.Volume = volume

                # SVSFlagsAsync = 1, SVSFPurgeBeforeSpeak = 2
                voice.Speak(text, 1 | 2)

                # 等待朗读完成或被停止
                voice.WaitUntilDone(-1)
            except Exception as e:
                logger.error(f"TTS 朗读失败: {e}")
            finally:
                self._speaking = False
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

        self._speaking = True
        self._speak_thread = threading.Thread(target=_speak_sync, daemon=True)
        self._speak_thread.start()

        current_voice = voice_name or "default"
        return {
            "status": "speaking",
            "text": text[:200],  # 截断长文本
            "voice": current_voice,
            "rate": rate,
            "volume": volume,
        }

    async def list_voices(self) -> list[dict[str, Any]]:
        """列出系统可用的语音引擎。

        Returns:
            语音引擎列表，每项包含::

                {
                    "name": "Microsoft Huihui Desktop",
                    "language": "zh-CN",
                    "gender": "Female",
                    "description": "Microsoft Huihui Desktop - Chinese ..."
                }
        """
        if not _SAPI_AVAILABLE or self._voice is None:
            return [{"error": "TTS 仅支持 Windows 平台（SAPI COM 接口）"}]

        voices: list[dict[str, Any]] = []
        try:
            voice_tokens = self._voice.GetVoices()
            for i in range(voice_tokens.Count):
                token = voice_tokens.Item(i)
                desc = token.GetDescription()
                # 尝试提取语言和性别信息
                lang = self._extract_voice_attr(token, "Language")
                gender = self._extract_voice_attr(token, "Gender")
                name = self._extract_voice_attr(token, "Name") or desc

                voices.append({
                    "name": name,
                    "language": lang,
                    "gender": gender,
                    "description": desc,
                })
        except Exception as e:
            logger.error(f"获取语音列表失败: {e}")
            return [{"error": f"获取语音列表失败: {e}"}]

        return voices

    async def save_to_file(
        self,
        text: str,
        output_path: str,
        voice_name: str | None = None,
    ) -> dict[str, Any]:
        """将语音保存到 WAV 文件。

        Args:
            text: 要合成的文本内容
            output_path: 输出 WAV 文件路径
            voice_name: 语音引擎名称（可选）

        Returns:
            操作结果字典::

                {
                    "status": "saved",
                    "path": "output.wav",
                    "text_length": 42
                }
        """
        if not _SAPI_AVAILABLE or self._voice is None:
            return _unsupported()

        if not text or not text.strip():
            return {"error": "文本内容不能为空"}

        # 确保输出目录存在
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            # 创建文件输出流
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            # SSFCreateForWrite = 2
            stream.Open(str(out.resolve()), 2)

            # 创建独立的 voice 用于文件输出
            file_voice = win32com.client.Dispatch("SAPI.SpVoice")
            file_voice.AudioOutputStream = stream

            if voice_name:
                self._set_voice(file_voice, voice_name)

            # 同步执行（在子线程中避免阻塞事件循环）
            def _save_sync() -> None:
                try:
                    pythoncom.CoInitialize()
                    v = win32com.client.Dispatch("SAPI.SpVoice")
                    s = win32com.client.Dispatch("SAPI.SpFileStream")
                    s.Open(str(out.resolve()), 2)
                    v.AudioOutputStream = s
                    if voice_name:
                        self._set_voice(v, voice_name)
                    v.Speak(text, 0)  # 同步朗读
                    s.Close()
                except Exception as exc:
                    logger.error(f"保存语音文件失败: {exc}")
                finally:
                    try:
                        pythoncom.CoUninitialize()
                    except Exception:
                        pass

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, _save_sync)

            # 验证文件存在
            if out.exists():
                size = out.stat().st_size
                return {
                    "status": "saved",
                    "path": str(out),
                    "text_length": len(text),
                    "file_size": size,
                }
            else:
                return {"error": "文件保存失败，输出文件不存在"}

        except Exception as e:
            logger.error(f"保存语音文件失败: {e}")
            return {"error": f"保存语音文件失败: {e}"}

    async def stop(self) -> dict[str, Any]:
        """停止当前朗读。

        Returns:
            操作结果字典::

                {"status": "stopped"}
        """
        if not _SAPI_AVAILABLE or self._voice is None:
            return _unsupported()

        self._stop_flag.set()

        # 在主 COM 对象上停止
        try:
            # SVSFPurgeBeforeSpeak = 2 — 清空缓冲区并停止
            self._voice.Speak("", 2)
        except Exception as e:
            logger.debug(f"停止朗读时出现异常（可能未在朗读）: {e}")

        self._speaking = False
        return {"status": "stopped"}

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _set_voice(voice: Any, voice_name: str) -> bool:
        """为 SpVoice 对象设置指定语音引擎。

        Args:
            voice: SAPI SpVoice COM 对象
            voice_name: 语音引擎名称（支持模糊匹配）

        Returns:
            是否成功设置
        """
        try:
            voice_tokens = voice.GetVoices()
            for i in range(voice_tokens.Count):
                token = voice_tokens.Item(i)
                desc = token.GetDescription()
                if voice_name.lower() in desc.lower():
                    voice.Voice = token
                    return True
            logger.warning(f"未找到匹配的语音引擎: {voice_name}")
            return False
        except Exception as e:
            logger.error(f"设置语音引擎失败: {e}")
            return False

    @staticmethod
    def _extract_voice_attr(token: Any, attr_name: str) -> str:
        """从语音令牌中提取属性值。

        Args:
            token: SAPI 语音令牌对象
            attr_name: 属性名称（如 Language, Gender, Name）

        Returns:
            属性值字符串，获取失败时返回 "unknown"
        """
        try:
            # 尝试通过 Registry 获取属性
            value = token.GetAttribute(attr_name) or ""
            if value and attr_name == "Language":
                # Language 返回的是 LANGID 数字，映射为常见代码
                lang_map = {
                    "0804": "zh-CN",
                    "0409": "en-US",
                    "0411": "ja-JP",
                    "0412": "ko-KR",
                    "040C": "fr-FR",
                    "0407": "de-DE",
                    "040A": "es-ES",
                }
                hex_str = hex(int(value))[2:].upper().zfill(4)
                return lang_map.get(hex_str, value)
            return value if value else "unknown"
        except Exception:
            return "unknown"
