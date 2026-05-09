"""TTS 语音合成工具。

支持多后端引擎：
  - edge-tts（优先）：微软 Edge 在线 TTS，免费高质量
  - pyttsx3（离线 fallback）：本地 SAPI / NSSAPI / espeak

Usage::

    tts = VoiceTTS()
    result = await tts.speak("你好，世界")
    voices = await tts.list_voices()
    result = await tts.save_to_file("测试", "output.wav")
"""

from __future__ import annotations

import asyncio
import io
import os
import threading
from pathlib import Path
from typing import Any

from loguru import logger

from src.utils.path_safety import safe_resolve_path

# ---------------------------------------------------------------------------
# 引擎可用性检测
# ---------------------------------------------------------------------------
_EDGE_TTS_AVAILABLE: bool = False
_PYTTSX3_AVAILABLE: bool = False

try:
    import edge_tts  # type: ignore[import-untyped]

    _EDGE_TTS_AVAILABLE = True
except ImportError:
    pass

try:
    import pyttsx3  # type: ignore[import-untyped]

    _PYTTSX3_AVAILABLE = True
except ImportError:
    pass

if not _EDGE_TTS_AVAILABLE and not _PYTTSX3_AVAILABLE:
    logger.warning("edge-tts 和 pyttsx3 均未安装，TTS 功能不可用。")

# 默认工作空间
_WORKSPACE = Path(os.environ.get("JAVASAGENT_WORKSPACE", ".")).resolve()


def _pick_engine(engine: str) -> str:
    """选择实际使用的引擎。

    Args:
        engine: 用户请求的引擎名（"default" / "edge-tts" / "pyttsx3"）

    Returns:
        实际使用的引擎名
    """
    if engine == "default":
        if _EDGE_TTS_AVAILABLE:
            return "edge-tts"
        if _PYTTSX3_AVAILABLE:
            return "pyttsx3"
        return "none"
    if engine == "edge-tts" and _EDGE_TTS_AVAILABLE:
        return "edge-tts"
    if engine == "pyttsx3" and _PYTTSX3_AVAILABLE:
        return "pyttsx3"
    # 用户指定了不可用的引擎，尝试 fallback
    if _EDGE_TTS_AVAILABLE:
        logger.info(f"引擎 {engine} 不可用，回退到 edge-tts")
        return "edge-tts"
    if _PYTTSX3_AVAILABLE:
        logger.info(f"引擎 {engine} 不可用，回退到 pyttsx3")
        return "pyttsx3"
    return "none"


# ---------------------------------------------------------------------------
# VoiceTTS
# ---------------------------------------------------------------------------


class VoiceTTS:
    """TTS 语音合成工具。

    优先使用 edge-tts（微软 Edge 在线 TTS），不可用时回退到 pyttsx3（离线）。
    所有同步操作通过 asyncio.to_thread / run_in_executor 执行，不阻塞事件循环。

    Attributes:
        _pyttsx3_engine: pyttsx3 引擎实例（惰性初始化）
        _speaking: 当前是否正在朗读
        _speak_thread: 当前朗读线程
    """

    def __init__(self) -> None:
        """初始化 TTS。"""
        self._pyttsx3_engine: Any = None
        self._speaking: bool = False
        self._speak_thread: threading.Thread | None = None
        self._stop_flag: threading.Event = threading.Event()

    # ------------------------------------------------------------------
    # 惰性初始化 pyttsx3
    # ------------------------------------------------------------------

    def _ensure_pyttsx3(self) -> Any:
        """惰性创建 pyttsx3 引擎。"""
        if self._pyttsx3_engine is None and _PYTTSX3_AVAILABLE:
            try:
                self._pyttsx3_engine = pyttsx3.init()
                logger.debug("pyttsx3 引擎初始化成功")
            except Exception as e:
                logger.error(f"pyttsx3 初始化失败: {e}")
        return self._pyttsx3_engine

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    async def speak(
        self,
        text: str,
        engine: str = "default",
        rate: int = 200,
        volume: float = 1.0,
    ) -> dict[str, Any]:
        """朗读文本（异步，不阻塞调用者）。

        Args:
            text: 要朗读的文本内容
            engine: TTS 引擎（"default" / "edge-tts" / "pyttsx3"）
            rate: 语速（edge-tts: 拼接在 voice rate 中；pyttsx3: words per minute）
            volume: 音量 0.0~1.0

        Returns:
            操作结果字典，包含 status / message / engine 等字段
        """
        if not text or not text.strip():
            return {"error": "文本内容不能为空"}

        chosen = _pick_engine(engine)
        if chosen == "none":
            return {
                "error": "没有可用的 TTS 引擎。请安装 edge-tts 或 pyttsx3。",
            }

        volume = max(0.0, min(1.0, volume))

        # 如果正在朗读，先停止
        if self._speaking:
            await self.stop()

        self._stop_flag.clear()

        if chosen == "edge-tts":
            return await self._speak_edge(text, rate, volume)
        else:
            return await self._speak_pyttsx3(text, rate, volume)

    async def list_voices(self) -> dict[str, Any]:
        """列出可用语音引擎和语音。

        Returns:
            结果字典::

                {
                    "status": "ok",
                    "engines": ["edge-tts", "pyttsx3"],
                    "voices": [
                        {"name": "zh-CN-XiaoxiaoNeural", "language": "zh-CN", ...},
                        ...
                    ]
                }
        """
        engines: list[str] = []
        if _EDGE_TTS_AVAILABLE:
            engines.append("edge-tts")
        if _PYTTSX3_AVAILABLE:
            engines.append("pyttsx3")

        voices: list[dict[str, Any]] = []

        # 尝试获取 edge-tts 的语音列表
        if _EDGE_TTS_AVAILABLE:
            try:
                raw = await edge_tts.list_voices()
                for v in raw[:20]:  # 限制数量避免过大
                    voices.append({
                        "name": v.get("ShortName", v.get("Name", "unknown")),
                        "language": v.get("Locale", "unknown"),
                        "gender": v.get("Gender", "unknown"),
                        "engine": "edge-tts",
                    })
            except Exception as e:
                logger.warning(f"获取 edge-tts 语音列表失败: {e}")

        # 尝试获取 pyttsx3 的语音列表
        if _PYTTSX3_AVAILABLE and not voices:
            try:
                eng = self._ensure_pyttsx3()
                if eng:
                    for v in eng.getProperty("voices"):
                        voices.append({
                            "name": v.name,
                            "language": v.languages[0] if v.languages else "unknown",
                            "id": v.id,
                            "engine": "pyttsx3",
                        })
            except Exception as e:
                logger.warning(f"获取 pyttsx3 语音列表失败: {e}")

        return {
            "status": "ok",
            "engines": engines,
            "voices": voices,
        }

    async def save_to_file(
        self,
        text: str,
        path: str,
        engine: str = "default",
        rate: int = 200,
    ) -> dict[str, Any]:
        """将语音保存为音频文件。

        Args:
            text: 要合成的文本内容
            path: 输出文件路径（相对工作空间）
            engine: TTS 引擎
            rate: 语速

        Returns:
            操作结果字典，包含 status / path 等字段
        """
        if not text or not text.strip():
            return {"error": "文本内容不能为空"}

        chosen = _pick_engine(engine)
        if chosen == "none":
            return {"error": "没有可用的 TTS 引擎"}

        try:
            safe_path = safe_resolve_path(
                _WORKSPACE, path, allow_create_parents=True
            )
        except Exception as e:
            return {"error": f"路径不安全: {e}"}

        if chosen == "edge-tts":
            return await self._save_edge(text, safe_path, rate)
        else:
            return await self._save_pyttsx3(text, safe_path, rate)

    async def stop(self) -> dict[str, Any]:
        """停止当前朗读。

        Returns:
            操作结果字典
        """
        self._stop_flag.set()
        self._speaking = False

        # 尝试停止 pyttsx3
        if _PYTTSX3_AVAILABLE:
            try:
                eng = self._ensure_pyttsx3()
                if eng:
                    eng.stop()
            except Exception:
                pass

        return {"status": "stopped"}

    # ------------------------------------------------------------------
    # edge-tts 实现
    # ------------------------------------------------------------------

    async def _speak_edge(
        self, text: str, rate: int, volume: float
    ) -> dict[str, Any]:
        """使用 edge-tts 朗读。edge-tts 原生异步，直接 await。"""
        try:
            # rate: edge-tts 格式 "+0%", "+50%", "-20%"
            rate_pct = (rate - 200) // 2  # 近似映射
            rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"
            # volume: "+0%", "-50%" 等
            vol_pct = int((volume - 1.0) * 100)
            vol_str = f"+{vol_pct}%" if vol_pct >= 0 else f"{vol_pct}%"

            communicate = edge_tts.Communicate(
                text, rate=rate_str, volume=vol_str
            )

            # 使用后台任务播放音频
            self._speaking = True

            def _play_sync() -> None:
                """在子线程中收集音频并通过系统播放。"""
                try:
                    import subprocess
                    import tempfile

                    # 保存到临时文件然后播放
                    tmp = Path(tempfile.mktemp(suffix=".mp3"))
                    loop = asyncio.new_event_loop()
                    try:
                        # 同步收集音频数据
                        audio_data = io.BytesIO()

                        async def _collect() -> None:
                            async for chunk in communicate.stream():
                                if chunk["type"] == "audio":
                                    audio_data.write(chunk["data"])

                        loop.run_until_complete(_collect())
                    finally:
                        loop.close()

                    tmp.write_bytes(audio_data.getvalue())

                    if not self._stop_flag.is_set():
                        # Windows: 使用系统默认播放器
                        os.startfile(str(tmp))  # type: ignore[attr-defined]
                except Exception as exc:
                    logger.error(f"edge-tts 播放失败: {exc}")
                finally:
                    self._speaking = False
                    # 清理临时文件
                    try:
                        if tmp.exists():
                            tmp.unlink()
                    except Exception:
                        pass

            self._speak_thread = threading.Thread(
                target=_play_sync, daemon=True
            )
            self._speak_thread.start()

            return {
                "status": "speaking",
                "text": text[:200],
                "engine": "edge-tts",
                "rate": rate,
                "volume": volume,
            }
        except Exception as e:
            logger.error(f"edge-tts 朗读失败: {e}")
            self._speaking = False
            return {"error": f"edge-tts 朗读失败: {e}"}

    async def _save_edge(
        self, text: str, output_path: Path, rate: int
    ) -> dict[str, Any]:
        """使用 edge-tts 保存到文件。"""
        try:
            rate_pct = (rate - 200) // 2
            rate_str = f"+{rate_pct}%" if rate_pct >= 0 else f"{rate_pct}%"

            communicate = edge_tts.Communicate(text, rate=rate_str)
            await communicate.save(str(output_path))

            size = output_path.stat().st_size if output_path.exists() else 0
            return {
                "status": "saved",
                "path": str(output_path),
                "engine": "edge-tts",
                "text_length": len(text),
                "file_size": size,
            }
        except Exception as e:
            logger.error(f"edge-tts 保存失败: {e}")
            return {"error": f"edge-tts 保存失败: {e}"}

    # ------------------------------------------------------------------
    # pyttsx3 实现
    # ------------------------------------------------------------------

    async def _speak_pyttsx3(
        self, text: str, rate: int, volume: float
    ) -> dict[str, Any]:
        """使用 pyttsx3 朗读。"""
        eng = self._ensure_pyttsx3()
        if eng is None:
            return {"error": "pyttsx3 引擎不可用"}

        self._speaking = True

        def _speak_sync() -> None:
            try:
                eng.setProperty("rate", rate)
                eng.setProperty("volume", volume)
                eng.say(text)
                eng.runAndWait()
            except Exception as exc:
                logger.error(f"pyttsx3 朗读失败: {exc}")
            finally:
                self._speaking = False

        self._speak_thread = threading.Thread(target=_speak_sync, daemon=True)
        self._speak_thread.start()

        return {
            "status": "speaking",
            "text": text[:200],
            "engine": "pyttsx3",
            "rate": rate,
            "volume": volume,
        }

    async def _save_pyttsx3(
        self, text: str, output_path: Path, rate: int
    ) -> dict[str, Any]:
        """使用 pyttsx3 保存到文件。"""
        eng = self._ensure_pyttsx3()
        if eng is None:
            return {"error": "pyttsx3 引擎不可用"}

        def _save_sync() -> None:
            try:
                eng.setProperty("rate", rate)
                eng.save_to_file(str(output_path))
                eng.runAndWait()
            except Exception as exc:
                logger.error(f"pyttsx3 保存失败: {exc}")

        await asyncio.to_thread(_save_sync)

        if output_path.exists():
            size = output_path.stat().st_size
            return {
                "status": "saved",
                "path": str(output_path),
                "engine": "pyttsx3",
                "text_length": len(text),
                "file_size": size,
            }
        return {"error": "文件保存失败，输出文件不存在", "path": str(output_path)}
