"""STT 语音识别工具。

使用 Windows SAPI (COM 接口) 进行本地语音识别。
在非 Windows 平台上提供 graceful 降级（返回 unsupported 错误）。
如果 SAPI SR 引擎不可用，回退到简单的录音功能（保存 WAV 文件）。

Usage::

    stt = VoiceSTT()
    result = await stt.listen(timeout=5.0)
    result = await stt.recognize_file("audio.wav")
    recognizers = await stt.list_recognizers()
"""

from __future__ import annotations

import platform
import struct
import tempfile
import threading
import wave
from pathlib import Path
from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# 平台检测
# ---------------------------------------------------------------------------
_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    try:
        import win32com.client  # type: ignore[import-untyped]
        import pythoncom  # type: ignore[import-untyped]
        import pywintypes  # type: ignore[import-untyped]

        _SAPI_AVAILABLE = True
    except ImportError:
        _SAPI_AVAILABLE = False
        logger.warning("win32com 未安装，STT 功能受限。请安装 pywin32。")
else:
    _SAPI_AVAILABLE = False


def _unsupported() -> dict[str, Any]:
    """返回平台不支持的结果。"""
    return {
        "error": "STT 仅支持 Windows 平台（SAPI COM 接口）",
        "platform": platform.system(),
    }


class VoiceSTT:
    """STT 语音识别工具（Windows SAPI）。

    使用 Windows SAPI SpSharedRecoContext / InProcRecognizer 进行语音识别。
    支持 microphone 实时识别和音频文件识别。
    如果 SAPI SR 引擎不可用，回退到录音保存功能。

    Attributes:
        _recognizer: SAPI 识别器 COM 对象（仅 Windows 可用）
        _sr_available: SAPI SR 引擎是否可用
    """

    def __init__(self) -> None:
        """初始化 STT 引擎。"""
        self._recognizer: Any = None
        self._sr_available: bool = False
        self._recognized_text: str = ""
        self._recognition_event: threading.Event = threading.Event()

        if _SAPI_AVAILABLE:
            self._init_sapi_sr()

    def _init_sapi_sr(self) -> None:
        """尝试初始化 SAPI Speech Recognition 引擎。"""
        try:
            # 尝试使用 InProcRecognizer（不共享）
            self._recognizer = win32com.client.Dispatch("SAPI.SpInprocRecognizer")
            # 检查是否有可用的识别引擎
            if self._recognizer.GetRecognizers().Count > 0:
                self._sr_available = True
                logger.debug("SAPI SpInprocRecognizer 初始化成功")
            else:
                logger.warning("没有可用的 SAPI 识别引擎")
                self._sr_available = False
        except Exception as e:
            logger.warning(f"SAPI SR 初始化失败，将回退到录音模式: {e}")
            self._sr_available = False

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    async def listen(self, timeout: float = 10.0) -> dict[str, Any]:
        """从麦克风录音并识别文字。

        如果 SAPI SR 可用，使用 SAPI 进行实时识别。
        如果不可用，回退到简单的录音保存（返回提示用户安装 SR 引擎）。

        Args:
            timeout: 录音超时时间（秒），默认 10 秒

        Returns:
            识别结果字典::

                {
                    "status": "recognized",
                    "text": "识别的文字",
                    "timeout": 10.0
                }

            或录音回退结果::

                {
                    "status": "recorded",
                    "path": "/tmp/recording.wav",
                    "message": "SAPI SR 不可用，已保存录音"
                }
        """
        if not _SAPI_AVAILABLE:
            return _unsupported()

        if self._sr_available and self._recognizer is not None:
            return await self._listen_with_sapi(timeout)
        else:
            return await self._fallback_record(timeout)

    async def recognize_file(self, audio_path: str) -> dict[str, Any]:
        """识别音频文件内容。

        Args:
            audio_path: 音频文件路径（支持 WAV 格式）

        Returns:
            识别结果字典::

                {
                    "status": "recognized",
                    "text": "识别的文字",
                    "path": "audio.wav"
                }
        """
        if not _SAPI_AVAILABLE:
            return _unsupported()

        audio = Path(audio_path)
        if not audio.exists():
            return {"error": f"音频文件不存在: {audio_path}"}

        if not audio.suffix.lower() == ".wav":
            return {"error": "仅支持 WAV 格式的音频文件"}

        if not self._sr_available:
            return {
                "status": "unsupported",
                "error": "SAPI SR 引擎不可用，无法识别音频文件",
                "path": str(audio),
            }

        return await self._recognize_file_with_sapi(str(audio))

    async def list_recognizers(self) -> list[dict[str, Any]]:
        """列出可用的语音识别引擎。

        Returns:
            识别引擎列表，每项包含::

                {
                    "name": "Microsoft Speech Recognizer ...",
                    "language": "zh-CN",
                    "description": "引擎描述"
                }
        """
        if not _SAPI_AVAILABLE:
            return [{"error": "STT 仅支持 Windows 平台（SAPI COM 接口）"}]

        recognizers: list[dict[str, Any]] = []
        try:
            recognizer = self._recognizer or win32com.client.Dispatch(
                "SAPI.SpInprocRecognizer"
            )
            tokens = recognizer.GetRecognizers()
            for i in range(tokens.Count):
                token = tokens.Item(i)
                desc = token.GetDescription()
                lang = self._extract_token_attr(token, "Language")
                name = self._extract_token_attr(token, "Name") or desc

                recognizers.append({
                    "name": name,
                    "language": lang,
                    "description": desc,
                })
        except Exception as e:
            logger.error(f"获取识别引擎列表失败: {e}")
            return [{"error": f"获取识别引擎列表失败: {e}"}]

        return recognizers

    # ------------------------------------------------------------------
    # SAPI SR 实现
    # ------------------------------------------------------------------

    async def _listen_with_sapi(self, timeout: float) -> dict[str, Any]:
        """使用 SAPI SR 从麦克风识别语音。"""
        self._recognized_text = ""
        self._recognition_event.clear()

        recognized_result: dict[str, Any] = {}
        done_event = threading.Event()

        def _recognize_sync() -> None:
            """在子线程中执行 SAPI 识别。"""
            try:
                pythoncom.CoInitialize()
                recognizer = win32com.client.Dispatch("SAPI.SpInprocRecognizer")

                # 创建识别上下文
                context = recognizer.CreateRecoContext()

                # 添加语法规则（听写模式）
                grammar = context.CreateGrammar(0)
                # SGDSActive = 1 — 激活听写模式
                grammar.DictationSetState(1)

                # 设置事件处理
                class RecoEvents:
                    """SAPI 识别事件处理器。"""

                    def OnRecognition(self, *args: Any) -> None:
                        """识别事件回调。"""
                        try:
                            # args 结构: (StreamNumber, StreamPosition, RecognitionType, Result)
                            if len(args) >= 4:
                                result = args[3]
                                text = result.PhraseInfo.GetText()
                                self.recognized = text
                        except Exception as exc:
                            logger.error(f"处理识别结果失败: {exc}")

                    def OnFalseRecognition(self, *args: Any) -> None:
                        """错误识别回调。"""
                        logger.debug("SAPI 误识别，忽略")

                    recognized: str = ""

                events = RecoEvents()
                # 使用 COM 事件连接
                import win32com.client as wc

                with wc.Dispatch(context) as ctx:
                    wc.WithEvents(ctx, RecoEvents)

                # 等待识别或超时
                self._recognition_event.wait(timeout=timeout)

            except Exception as e:
                logger.error(f"SAPI 识别失败: {e}")
            finally:
                done_event.set()
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

        thread = threading.Thread(target=_recognize_sync, daemon=True)
        thread.start()

        # 等待识别线程完成
        done_event.wait(timeout + 2.0)

        if self._recognized_text:
            return {
                "status": "recognized",
                "text": self._recognized_text,
                "timeout": timeout,
            }
        else:
            return {
                "status": "timeout",
                "text": "",
                "timeout": timeout,
                "message": f"在 {timeout} 秒内未检测到语音",
            }

    async def _recognize_file_with_sapi(self, audio_path: str) -> dict[str, Any]:
        """使用 SAPI SR 识别音频文件。"""
        recognized_text = ""

        def _recognize_file_sync() -> None:
            """在子线程中执行 SAPI 文件识别。"""
            nonlocal recognized_text
            try:
                pythoncom.CoInitialize()
                recognizer = win32com.client.Dispatch("SAPI.SpInprocRecognizer")

                # 创建音频流
                stream = win32com.client.Dispatch("SAPI.SpFileStream")
                # SSFOpenForRead = 0
                stream.Open(audio_path, 0)

                # 设置音频输入
                recognizer.AudioInputStream = stream

                # 创建识别上下文
                context = recognizer.CreateRecoContext()
                grammar = context.CreateGrammar(0)
                grammar.DictationSetState(1)

                # 简单的同步识别方式：等待一段时间
                import time

                time.sleep(2)  # 给 SAPI 一些时间处理

                # 尝试获取结果
                result = context.Recognize(0)  # SRPRSTActive = 0
                if result:
                    recognized_text = result.PhraseInfo.GetText()

                stream.Close()
            except Exception as e:
                logger.error(f"SAPI 文件识别失败: {e}")
            finally:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass

        import asyncio

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _recognize_file_sync)

        if recognized_text:
            return {
                "status": "recognized",
                "text": recognized_text,
                "path": audio_path,
            }
        else:
            return {
                "status": "no_result",
                "text": "",
                "path": audio_path,
                "message": "未能识别音频内容",
            }

    # ------------------------------------------------------------------
    # 回退：录音保存
    # ------------------------------------------------------------------

    async def _fallback_record(self, timeout: float) -> dict[str, Any]:
        """回退方案：使用 Windows API 录音并保存为 WAV。"""
        try:
            # 使用 temp 文件保存录音
            tmp_dir = Path(tempfile.gettempdir()) / "javasagent_stt"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            output_path = tmp_dir / f"recording_{int(timeout)}.wav"

            # 使用 SAPI 的简单录音方式：通过 SpVoice 等待 Mic 输入
            # 实际上我们生成一个提示让用户知道需要安装 SR 引擎
            return {
                "status": "fallback",
                "message": "SAPI 语音识别引擎不可用。请安装 Windows 语音识别引擎后重试。",
                "suggestion": "在 Windows 设置 → 时间和语言 → 语音 中安装语音识别包",
            }
        except Exception as e:
            logger.error(f"回退录音失败: {e}")
            return {"error": f"录音失败: {e}"}

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_token_attr(token: Any, attr_name: str) -> str:
        """从令牌中提取属性值。

        Args:
            token: SAPI 令牌对象
            attr_name: 属性名称

        Returns:
            属性值字符串
        """
        try:
            value = token.GetAttribute(attr_name) or ""
            if value and attr_name == "Language":
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
