"""VoiceTTS 测试。

验证 TTS 语音合成工具的正常路径和错误处理。
使用 Mock 替代 edge-tts 和 pyttsx3，不依赖外部服务。

覆盖：
  - 正常朗读流程（edge-tts / pyttsx3）
  - 引擎不可用 fallback
  - 参数错误（空文本、越界参数）
  - 保存文件
  - 停止朗读
  - 列出语音引擎
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_edge_tts():
    """创建 mock edge_tts 模块。"""
    m = MagicMock()
    m.Communicate.return_value = MagicMock()
    m.list_voices = AsyncMock(return_value=[
        {
            "ShortName": "zh-CN-XiaoxiaoNeural",
            "Locale": "zh-CN",
            "Gender": "Female",
            "Name": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)",
        },
        {
            "ShortName": "en-US-JennyNeural",
            "Locale": "en-US",
            "Gender": "Female",
            "Name": "Microsoft Server Speech Text to Speech Voice (en-US, JennyNeural)",
        },
    ])
    return m


@pytest.fixture
def mock_pyttsx3():
    """创建 mock pyttsx3 模块。"""
    m = MagicMock()
    engine = MagicMock()
    engine.getProperty.return_value = [
        MagicMock(name="Microsoft Huihui", languages=["zh-CN"], id="huihui"),
    ]
    m.init.return_value = engine
    return m


@pytest.fixture
def tts_with_edge(mock_edge_tts):
    """创建使用 mock edge-tts 的 VoiceTTS 实例。"""
    with patch.dict("sys.modules", {"edge_tts": mock_edge_tts}):
        from src.tools import voice_tts
        import importlib
        importlib.reload(voice_tts)

        with patch.object(voice_tts, "_EDGE_TTS_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            yield tts, voice_tts, mock_edge_tts


@pytest.fixture
def tts_with_pyttsx3_only(mock_pyttsx3):
    """创建仅有 pyttsx3 的 VoiceTTS 实例（无 edge-tts）。"""
    with patch.dict("sys.modules", {"pyttsx3": mock_pyttsx3}):
        from src.tools import voice_tts
        import importlib
        importlib.reload(voice_tts)

        with patch.object(voice_tts, "_EDGE_TTS_AVAILABLE", False), \
             patch.object(voice_tts, "_PYTTSX3_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            yield tts, voice_tts, mock_pyttsx3


# ---------------------------------------------------------------------------
# speak 测试
# ---------------------------------------------------------------------------


class TestVoiceTTSSpeak:
    """speak 方法测试。"""

    @pytest.mark.asyncio
    async def test_speak_with_edge_tts(self, tts_with_edge) -> None:
        """edge-tts 可用时使用 edge-tts。"""
        tts, module, mock_edge = tts_with_edge
        result = await tts.speak("你好世界")

        assert result["status"] == "speaking"
        assert result["engine"] == "edge-tts"
        assert result["text"] == "你好世界"

    @pytest.mark.asyncio
    async def test_speak_with_pyttsx3_fallback(self, tts_with_pyttsx3_only) -> None:
        """edge-tts 不可用时 fallback 到 pyttsx3。"""
        tts, module, mock_pyttsx3 = tts_with_pyttsx3_only
        result = await tts.speak("测试")

        assert result["status"] == "speaking"
        assert result["engine"] == "pyttsx3"

    @pytest.mark.asyncio
    async def test_speak_explicit_engine(self, tts_with_edge) -> None:
        """显式指定引擎。"""
        tts, module, mock_edge = tts_with_edge
        result = await tts.speak("测试", engine="edge-tts")

        assert result["engine"] == "edge-tts"

    @pytest.mark.asyncio
    async def test_speak_empty_text(self) -> None:
        """空文本应返回错误。"""
        from src.tools import voice_tts
        tts = voice_tts.VoiceTTS()
        result = await tts.speak("")

        assert "error" in result
        assert "空" in result["error"]

    @pytest.mark.asyncio
    async def test_speak_whitespace(self) -> None:
        """纯空白应返回错误。"""
        from src.tools import voice_tts
        tts = voice_tts.VoiceTTS()
        result = await tts.speak("   ")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_speak_no_engine_available(self) -> None:
        """无可用引擎应返回错误。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_EDGE_TTS_AVAILABLE", False), \
             patch.object(voice_tts, "_PYTTSX3_AVAILABLE", False):
            tts = voice_tts.VoiceTTS()
            result = await tts.speak("测试")

        assert "error" in result
        assert "没有" in result["error"] or "不可用" in result["error"]

    @pytest.mark.asyncio
    async def test_speak_volume_clamped(self) -> None:
        """音量应被 clamp 到 0.0~1.0。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_EDGE_TTS_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            # 需要让 _pick_engine 返回有效引擎
            with patch.object(voice_tts, "_pick_engine", return_value="edge-tts"):
                with patch.object(tts, "_speak_edge", new_callable=AsyncMock) as mock:
                    mock.return_value = {"status": "speaking"}
                    await tts.speak("测试", volume=2.0)
                    # 检查传给 _speak_edge 的 volume 参数
                    mock.assert_called_once()
                    assert mock.call_args[0][2] == 1.0  # volume clamped

    @pytest.mark.asyncio
    async def test_speak_stops_previous(self) -> None:
        """新朗读应先停止之前的。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_EDGE_TTS_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._speaking = True

            with patch.object(tts, "stop", new_callable=AsyncMock) as mock_stop:
                mock_stop.return_value = {"status": "stopped"}
                with patch.object(voice_tts, "_pick_engine", return_value="edge-tts"):
                    with patch.object(tts, "_speak_edge", new_callable=AsyncMock) as mock_speak:
                        mock_speak.return_value = {"status": "speaking"}
                        await tts.speak("新文本")

            mock_stop.assert_called_once()


# ---------------------------------------------------------------------------
# list_voices 测试
# ---------------------------------------------------------------------------


class TestVoiceTTSListVoices:
    """list_voices 方法测试。"""

    @pytest.mark.asyncio
    async def test_list_voices_with_edge(self, tts_with_edge) -> None:
        """edge-tts 可用时返回语音列表。"""
        tts, module, mock_edge = tts_with_edge
        result = await tts.list_voices()

        assert result["status"] == "ok"
        assert "edge-tts" in result["engines"]
        assert len(result["voices"]) >= 1
        assert result["voices"][0]["engine"] == "edge-tts"

    @pytest.mark.asyncio
    async def test_list_voices_fields(self, tts_with_edge) -> None:
        """每个语音应有必要字段。"""
        tts, module, mock_edge = tts_with_edge
        result = await tts.list_voices()

        for v in result["voices"]:
            assert "name" in v
            assert "engine" in v

    @pytest.mark.asyncio
    async def test_list_voices_no_engine(self) -> None:
        """无引擎时仍返回有效结果。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_EDGE_TTS_AVAILABLE", False), \
             patch.object(voice_tts, "_PYTTSX3_AVAILABLE", False):
            tts = voice_tts.VoiceTTS()
            result = await tts.list_voices()

        assert result["status"] == "ok"
        assert result["engines"] == []
        assert result["voices"] == []


# ---------------------------------------------------------------------------
# save_to_file 测试
# ---------------------------------------------------------------------------


class TestVoiceTTSSaveToFile:
    """save_to_file 方法测试。"""

    @pytest.mark.asyncio
    async def test_save_empty_text(self) -> None:
        """空文本应返回错误。"""
        from src.tools import voice_tts
        tts = voice_tts.VoiceTTS()
        result = await tts.save_to_file("", "out.mp3")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_save_with_edge(self, tts_with_edge, tmp_path) -> None:
        """edge-tts 保存文件。"""
        tts, module, mock_edge = tts_with_edge

        # mock safe_resolve_path 返回一个测试路径
        output = tmp_path / "test_output.mp3"
        output.write_bytes(b"fake audio data")

        with patch("src.tools.voice_tts.safe_resolve_path", return_value=output):
            # mock Communicate.save
            mock_comm = MagicMock()
            mock_comm.save = AsyncMock()
            mock_edge.Communicate.return_value = mock_comm

            result = await tts.save_to_file("测试文本", "test_output.mp3")

        assert result["status"] == "saved"
        assert result["engine"] == "edge-tts"

    @pytest.mark.asyncio
    async def test_save_unsafe_path(self) -> None:
        """不安全路径应返回错误。"""
        from src.tools import voice_tts
        from src.utils.path_safety import PathSafetyError

        tts = voice_tts.VoiceTTS()
        with patch(
            "src.tools.voice_tts.safe_resolve_path",
            side_effect=PathSafetyError("path traversal"),
        ):
            result = await tts.save_to_file("测试", "../../etc/passwd")

        assert "error" in result
        assert "路径" in result["error"]


# ---------------------------------------------------------------------------
# stop 测试
# ---------------------------------------------------------------------------


class TestVoiceTTSStop:
    """stop 方法测试。"""

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        """停止朗读。"""
        from src.tools import voice_tts
        tts = voice_tts.VoiceTTS()
        result = await tts.stop()

        assert result["status"] == "stopped"
        assert tts._speaking is False

    @pytest.mark.asyncio
    async def test_stop_with_pyttsx3(self, mock_pyttsx3) -> None:
        """停止时应调用 pyttsx3 engine.stop()。"""
        with patch.dict("sys.modules", {"pyttsx3": mock_pyttsx3}):
            from src.tools import voice_tts
            import importlib
            importlib.reload(voice_tts)

            with patch.object(voice_tts, "_PYTTSX3_AVAILABLE", True):
                tts = voice_tts.VoiceTTS()
                engine = mock_pyttsx3.init.return_value
                tts._ensure_pyttsx3()

                result = await tts.stop()

        assert result["status"] == "stopped"
        engine.stop.assert_called()


# ---------------------------------------------------------------------------
# VoiceOps 门面集成测试
# ---------------------------------------------------------------------------


class TestVoiceOpsExecute:
    """execute 路由测试。"""

    @pytest.mark.asyncio
    async def test_speak_routing(self) -> None:
        """speak 应委托给 TTS。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._tts, "speak", new_callable=AsyncMock) as mock_speak:
            mock_speak.return_value = {"status": "speaking", "text": "hello"}
            result = await ops.execute("speak", {"text": "hello"})

        assert result["status"] == "speaking"
        mock_speak.assert_called_once_with(text="hello")

    @pytest.mark.asyncio
    async def test_list_voices_routing(self) -> None:
        """list_voices 应委托给 TTS。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._tts, "list_voices", new_callable=AsyncMock) as mock_lv:
            mock_lv.return_value = {"status": "ok", "voices": []}
            result = await ops.execute("list_voices", {})

        assert result["status"] == "ok"
        mock_lv.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_save_to_file_routing(self) -> None:
        """save_to_file 应委托给 TTS。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._tts, "save_to_file", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = {"status": "saved"}
            result = await ops.execute("save_to_file", {"text": "test", "path": "out.wav"})

        assert result["status"] == "saved"
        mock_save.assert_called_once_with(text="test", path="out.wav")

    @pytest.mark.asyncio
    async def test_stop_routing(self) -> None:
        """stop 应委托给 TTS。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._tts, "stop", new_callable=AsyncMock) as mock_stop:
            mock_stop.return_value = {"status": "stopped"}
            result = await ops.execute("stop", {})

        assert result["status"] == "stopped"

    @pytest.mark.asyncio
    async def test_listen_routing(self) -> None:
        """listen 应委托给 STT。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._stt, "listen", new_callable=AsyncMock) as mock_listen:
            mock_listen.return_value = {"status": "recognized", "text": "hi"}
            result = await ops.execute("listen", {"timeout": 5.0})

        assert result["status"] == "recognized"
        mock_listen.assert_called_once_with(timeout=5.0)

    @pytest.mark.asyncio
    async def test_recognize_file_routing(self) -> None:
        """recognize_file 应委托给 STT。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._stt, "recognize_file", new_callable=AsyncMock) as mock_rf:
            mock_rf.return_value = {"status": "recognized", "text": "hi"}
            result = await ops.execute("recognize_file", {"path": "a.wav"})

        assert result["status"] == "recognized"
        mock_rf.assert_called_once_with(path="a.wav")

    @pytest.mark.asyncio
    async def test_list_recognizers_routing(self) -> None:
        """list_recognizers 应委托给 STT。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._stt, "list_recognizers", new_callable=AsyncMock) as mock_lr:
            mock_lr.return_value = {"status": "ok", "engines": []}
            result = await ops.execute("list_recognizers", {})

        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_unknown_action(self) -> None:
        """未知操作应返回错误和可用列表。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()
        result = await ops.execute("nonexistent", {})

        assert "error" in result
        assert "未知操作" in result["error"]
        assert "available_actions" in result
        assert "speak" in result["available_actions"]
        assert "listen" in result["available_actions"]

    @pytest.mark.asyncio
    async def test_bad_params(self) -> None:
        """参数错误应返回错误。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._tts, "speak", new_callable=AsyncMock, side_effect=TypeError("missing 'text'")):
            result = await ops.execute("speak", {"wrong_param": "test"})

        assert "error" in result
        assert "参数错误" in result["error"]
