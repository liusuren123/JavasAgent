"""STT 语音识别工具。

支持多后端引擎：
  - Google Speech Recognition（免费在线，通过 speech_recognition 库）
  - Whisper（如果安装了 openai-whisper）

Usage::

    stt = VoiceSTT()
    result = await stt.listen(timeout=5.0)
    result = await stt.recognize_file("audio.wav")
    recognizers = await stt.list_recognizers()
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import wave
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import safe_resolve_path

# ---------------------------------------------------------------------------
# 引擎可用性检测
# ---------------------------------------------------------------------------
_SR_AVAILABLE: bool = False
_WHISPER_AVAILABLE: bool = False

try:
    import speech_recognition as sr  # type: ignore[import-untyped]

    _SR_AVAILABLE = True
except ImportError:
    logger.warning("speech_recognition 未安装，STT 功能不可用。pip install SpeechRecognition")

try:
    import whisper as _whisper_module  # type: ignore[import-untyped]

    _WHISPER_AVAILABLE = True
except ImportError:
    _whisper_module = None  # type: ignore[assignment]

# 默认工作空间
_WORKSPACE = Path(os.environ.get("JAVASAGENT_WORKSPACE", ".")).resolve()


# ---------------------------------------------------------------------------
# VoiceSTT
# ---------------------------------------------------------------------------


class VoiceSTT:
    """STT 语音识别工具。

    使用 speech_recognition 库作为后端，支持 Google SR（免费在线）和
    Whisper（如果安装了 openai-whisper）。
    所有同步操作通过 asyncio.to_thread 执行，不阻塞事件循环。
    """

    def __init__(self) -> None:
        """初始化 STT。"""
        self._recognizer: Any = None
        if _SR_AVAILABLE:
            try:
                self._recognizer = sr.Recognizer()
                logger.debug("speech_recognition Recognizer 初始化成功")
            except Exception as e:
                logger.error(f"speech_recognition 初始化失败: {e}")

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    async def listen(
        self,
        timeout: float = 5.0,
        phrase_time_limit: float | None = None,
    ) -> dict[str, Any]:
        """从麦克风录音并识别文字。

        Args:
            timeout: 等待语音开始的超时秒数
            phrase_time_limit: 单次短语的最长录音秒数（None 表示不限）

        Returns:
            识别结果字典::

                {
                    "status": "recognized",
                    "text": "识别的文字",
                    "confidence": 0.92,
                    "engine": "google"
                }
        """
        if not _SR_AVAILABLE or self._recognizer is None:
            return {
                "error": "speech_recognition 未安装。请执行 pip install SpeechRecognition",
            }

        def _listen_sync() -> dict[str, Any]:
            with sr.Microphone() as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=0.5)
                try:
                    audio = self._recognizer.listen(
                        source,
                        timeout=timeout,
                        phrase_time_limit=phrase_time_limit,
                    )
                except sr.WaitTimeoutError:
                    return {
                        "status": "timeout",
                        "text": "",
                        "message": f"在 {timeout} 秒内未检测到语音",
                    }

            # 尝试 Google SR
            try:
                text = self._recognizer.recognize_google(audio, language="zh-CN")
                return {
                    "status": "recognized",
                    "text": text,
                    "confidence": None,
                    "engine": "google",
                }
            except sr.UnknownValueError:
                return {
                    "status": "no_result",
                    "text": "",
                    "message": "无法识别语音内容",
                    "engine": "google",
                }
            except sr.RequestError as e:
                logger.warning(f"Google SR 请求失败: {e}，尝试 Whisper fallback")
                # fallback 到 Whisper
                return self._recognize_with_whisper_from_audio(audio)
            except Exception as e:
                return {"error": f"识别失败: {e}"}

        return await asyncio.to_thread(_listen_sync)

    async def recognize_file(
        self, path: str, language: str = "zh-CN"
    ) -> dict[str, Any]:
        """识别音频文件内容。

        Args:
            path: 音频文件路径（相对工作空间），支持 WAV / MP3 等格式
            language: 语言代码（如 "zh-CN", "en-US"）

        Returns:
            识别结果字典
        """
        if not _SR_AVAILABLE or self._recognizer is None:
            return {
                "error": "speech_recognition 未安装。请执行 pip install SpeechRecognition",
            }

        # 安全解析路径
        try:
            safe_path = safe_resolve_path(_WORKSPACE, path)
        except Exception as e:
            return {"error": f"路径不安全: {e}"}

        if not safe_path.exists():
            return {"error": f"音频文件不存在: {safe_path}"}

        suffix = safe_path.suffix.lower()
        if suffix not in {".wav", ".mp3", ".flac", ".aiff", ".ogg"}:
            return {"error": f"不支持的音频格式: {suffix}"}

        def _recognize_sync() -> dict[str, Any]:
            try:
                if suffix == ".wav":
                    with sr.AudioFile(str(safe_path)) as source:
                        audio = self._recognizer.record(source)
                else:
                    # speech_recognition 仅原生支持 WAV，其他格式用 Whisper
                    if _WHISPER_AVAILABLE:
                        return self._recognize_with_whisper_from_file(str(safe_path), language)
                    return {
                        "error": f"非 WAV 格式 ({suffix}) 需要 openai-whisper 支持",
                    }

                # Google SR
                try:
                    text = self._recognizer.recognize_google(
                        audio, language=language
                    )
                    return {
                        "status": "recognized",
                        "text": text,
                        "confidence": None,
                        "engine": "google",
                        "path": str(safe_path),
                    }
                except sr.UnknownValueError:
                    # Google 识别失败，尝试 Whisper
                    if _WHISPER_AVAILABLE:
                        return self._recognize_with_whisper_from_file(
                            str(safe_path), language
                        )
                    return {
                        "status": "no_result",
                        "text": "",
                        "message": "无法识别音频内容",
                        "engine": "google",
                        "path": str(safe_path),
                    }
                except sr.RequestError as e:
                    logger.warning(f"Google SR 请求失败: {e}，尝试 Whisper")
                    if _WHISPER_AVAILABLE:
                        return self._recognize_with_whisper_from_file(
                            str(safe_path), language
                        )
                    return {"error": f"Google SR 不可用且 Whisper 未安装: {e}"}

            except Exception as e:
                logger.error(f"文件识别失败: {e}")
                return {"error": f"文件识别失败: {e}"}

        return await asyncio.to_thread(_recognize_sync)

    async def list_recognizers(self) -> dict[str, Any]:
        """列出可用识别引擎。

        Returns:
            结果字典::

                {
                    "status": "ok",
                    "engines": [
                        {"name": "google", "type": "online", "description": "..."},
                        ...
                    ]
                }
        """
        engines: list[dict[str, Any]] = []

        if _SR_AVAILABLE:
            engines.append({
                "name": "google",
                "type": "online",
                "description": "Google Speech Recognition（免费在线）",
            })

        if _WHISPER_AVAILABLE:
            engines.append({
                "name": "whisper",
                "type": "offline",
                "description": "OpenAI Whisper（本地离线模型）",
            })

        return {
            "status": "ok",
            "engines": engines,
            "speech_recognition_available": _SR_AVAILABLE,
            "whisper_available": _WHISPER_AVAILABLE,
        }

    # ------------------------------------------------------------------
    # Whisper 辅助方法
    # ------------------------------------------------------------------

    def _recognize_with_whisper_from_audio(
        self, audio_data: Any
    ) -> dict[str, Any]:
        """从 speech_recognition AudioData 使用 Whisper 识别。"""
        if not _WHISPER_AVAILABLE or _whisper_module is None:
            return {"error": "Whisper 不可用"}
        try:
            # 将 AudioData 转换为 WAV 字节
            wav_bytes = audio_data.get_wav_data()
            model = _whisper_module.load_model("base")

            # 写入临时文件
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav_bytes)
                tmp_path = f.name

            try:
                result = model.transcribe(tmp_path)
                text = result.get("text", "").strip()
                return {
                    "status": "recognized",
                    "text": text,
                    "engine": "whisper",
                    "confidence": None,
                }
            finally:
                os.unlink(tmp_path)
        except Exception as e:
            logger.error(f"Whisper 识别失败: {e}")
            return {"error": f"Whisper 识别失败: {e}"}

    def _recognize_with_whisper_from_file(
        self, file_path: str, language: str
    ) -> dict[str, Any]:
        """从文件使用 Whisper 识别。"""
        if not _WHISPER_AVAILABLE or _whisper_module is None:
            return {"error": "Whisper 不可用"}
        try:
            model = _whisper_module.load_model("base")
            # language 参数取前缀（zh-CN → zh）
            lang = language.split("-")[0] if language else None
            result = model.transcribe(file_path, language=lang)
            text = result.get("text", "").strip()
            return {
                "status": "recognized",
                "text": text,
                "engine": "whisper",
                "confidence": None,
                "path": file_path,
            }
        except Exception as e:
            logger.error(f"Whisper 文件识别失败: {e}")
            return {"error": f"Whisper 文件识别失败: {e}"}
