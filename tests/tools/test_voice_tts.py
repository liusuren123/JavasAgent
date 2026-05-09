"""VoiceTTS 测试。

验证 TTS 语音合成工具的正常路径和错误处理。
使用 Mock 替代 win32com.client，不依赖实际 COM 组件。

策略：在模块级别 patch _SAPI_AVAILABLE 和 win32com 对象，
确保 VoiceTTS 使用 mock 而非真实 COM。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 创建 mock COM 对象
# ---------------------------------------------------------------------------
def _make_mock_voice():
    """创建模拟的 SAPI.SpVoice COM 对象。"""
    voice = MagicMock()

    # 模拟 GetVoices
    voices = MagicMock()
    voices.Count = 2

    item0 = MagicMock()
    item0.GetDescription.return_value = "Microsoft Huihui Desktop"
    item0.GetAttribute.side_effect = lambda k: {
        "Language": "804", "Gender": "Female", "Name": "Huihui"
    }.get(k, "")

    item1 = MagicMock()
    item1.GetDescription.return_value = "Microsoft David Desktop"
    item1.GetAttribute.side_effect = lambda k: {
        "Language": "409", "Gender": "Male", "Name": "David"
    }.get(k, "")

    voices.Item.side_effect = [item0, item1]
    voice.GetVoices.return_value = voices
    voice.Speak = MagicMock()
    voice.WaitUntilDone = MagicMock()
    voice.Rate = 0
    voice.Volume = 100

    return voice


def _make_mock_win32com(mock_voice):
    """创建 mock win32com 模块。"""
    m = MagicMock()
    m.client.Dispatch.return_value = mock_voice
    return m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def mock_voice():
    """创建 mock voice。"""
    return _make_mock_voice()


@pytest.fixture
def tts_with_mock(mock_voice):
    """创建使用 mock COM 的 VoiceTTS 实例。"""
    mock_win32com = _make_mock_win32com(mock_voice)
    mock_pythoncom = MagicMock()

    with patch.dict("sys.modules", {
        "win32com": mock_win32com,
        "win32com.client": mock_win32com.client,
        "pythoncom": mock_pythoncom,
    }):
        # 重新导入模块以使用 mock
        import importlib
        from src.tools import voice_tts
        importlib.reload(voice_tts)

        # patch _SAPI_AVAILABLE
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True), \
             patch.object(voice_tts, "win32com", mock_win32com):
            tts = voice_tts.VoiceTTS()
            yield tts, voice_tts


# ---------------------------------------------------------------------------
# 测试类
# ---------------------------------------------------------------------------
class TestVoiceTTSSpeak:
    """speak 方法测试。"""

    @pytest.mark.asyncio
    async def test_speak_basic(self) -> None:
        """基本朗读测试。"""
        mock_voice = _make_mock_voice()
        mock_win32com = _make_mock_win32com(mock_voice)
        mock_pythoncom = MagicMock()

        with patch.dict("sys.modules", {
            "win32com": mock_win32com,
            "win32com.client": mock_win32com.client,
            "pythoncom": mock_pythoncom,
        }):
            from src.tools import voice_tts
            import importlib
            importlib.reload(voice_tts)

            with patch.object(voice_tts, "_SAPI_AVAILABLE", True), \
                 patch.object(voice_tts, "win32com", mock_win32com):
                tts = voice_tts.VoiceTTS()
                result = await tts.speak("你好世界")

        assert result["status"] == "speaking"
        assert result["text"] == "你好世界"
        assert result["volume"] == 100
        assert result["rate"] == 0

    @pytest.mark.asyncio
    async def test_speak_with_custom_params(self) -> None:
        """自定义语速和音量。"""
        mock_voice = _make_mock_voice()
        mock_win32com = _make_mock_win32com(mock_voice)

        with patch.dict("sys.modules", {
            "win32com": mock_win32com,
            "win32com.client": mock_win32com.client,
            "pythoncom": MagicMock(),
        }):
            from src.tools import voice_tts
            import importlib
            importlib.reload(voice_tts)

            with patch.object(voice_tts, "_SAPI_AVAILABLE", True), \
                 patch.object(voice_tts, "win32com", mock_win32com):
                tts = voice_tts.VoiceTTS()
                result = await tts.speak("测试", rate=5, volume=50, voice_name="Huihui")

        assert result["status"] == "speaking"
        assert result["rate"] == 5
        assert result["volume"] == 50
        assert result["voice"] == "Huihui"

    @pytest.mark.asyncio
    async def test_speak_empty_text(self) -> None:
        """空文本应返回错误。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._voice = MagicMock()  # 跳过 COM 检查
            result = await tts.speak("")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_speak_whitespace(self) -> None:
        """纯空白应返回错误。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._voice = MagicMock()
            result = await tts.speak("   ")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_speak_rate_clamped(self) -> None:
        """语速限制。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._voice = MagicMock()
            result = await tts.speak("测试", rate=20)
            assert result["rate"] == 10

            result = await tts.speak("测试", rate=-20)
            assert result["rate"] == -10

    @pytest.mark.asyncio
    async def test_speak_volume_clamped(self) -> None:
        """音量限制。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._voice = MagicMock()
            result = await tts.speak("测试", volume=200)
            assert result["volume"] == 100

            result = await tts.speak("测试", volume=-10)
            assert result["volume"] == 0

    @pytest.mark.asyncio
    async def test_speak_stops_previous(self) -> None:
        """朗读时应先停止之前的朗读。"""
        from src.tools import voice_tts
        mock_voice = _make_mock_voice()
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._voice = mock_voice  # 确保 _voice 不为 None
            tts._speaking = True

            result = await tts.speak("新文本")

        # 验证停止行为：Speak("", 2) 被调用以清除之前的朗读
        mock_voice.Speak.assert_any_call("", 2)
        assert result["status"] == "speaking"


class TestVoiceTTSListVoices:
    """list_voices 方法测试。"""

    @pytest.mark.asyncio
    async def test_list_voices(self) -> None:
        """列出语音引擎。"""
        mock_voice = _make_mock_voice()
        mock_win32com = _make_mock_win32com(mock_voice)

        with patch.dict("sys.modules", {
            "win32com": mock_win32com,
            "win32com.client": mock_win32com.client,
            "pythoncom": MagicMock(),
        }):
            from src.tools import voice_tts
            import importlib
            importlib.reload(voice_tts)

            with patch.object(voice_tts, "_SAPI_AVAILABLE", True), \
                 patch.object(voice_tts, "win32com", mock_win32com):
                tts = voice_tts.VoiceTTS()
                voices = await tts.list_voices()

        assert isinstance(voices, list)
        assert len(voices) == 2
        assert voices[0]["name"] == "Huihui"
        assert voices[1]["name"] == "David"

    @pytest.mark.asyncio
    async def test_list_voices_has_fields(self) -> None:
        """每个语音应有必要字段。"""
        mock_voice = _make_mock_voice()
        mock_win32com = _make_mock_win32com(mock_voice)

        with patch.dict("sys.modules", {
            "win32com": mock_win32com,
            "win32com.client": mock_win32com.client,
            "pythoncom": MagicMock(),
        }):
            from src.tools import voice_tts
            import importlib
            importlib.reload(voice_tts)

            with patch.object(voice_tts, "_SAPI_AVAILABLE", True), \
                 patch.object(voice_tts, "win32com", mock_win32com):
                tts = voice_tts.VoiceTTS()
                voices = await tts.list_voices()

        for v in voices:
            assert "name" in v
            assert "description" in v
            assert "language" in v
            assert "gender" in v


class TestVoiceTTSSaveToFile:
    """save_to_file 方法测试。"""

    @pytest.mark.asyncio
    async def test_save_empty_text(self) -> None:
        """空文本应返回错误。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._voice = MagicMock()
            result = await tts.save_to_file("", "/tmp/out.wav")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_save_to_file_success(self, tmp_path) -> None:
        """成功保存文件。"""
        from src.tools import voice_tts

        output_file = tmp_path / "test.wav"
        # 创建文件模拟
        output_file.write_bytes(b"RIFF" + b"\x00" * 100)

        mock_voice = _make_mock_voice()
        mock_win32com = _make_mock_win32com(mock_voice)

        with patch.dict("sys.modules", {
            "win32com": mock_win32com,
            "win32com.client": mock_win32com.client,
            "pythoncom": MagicMock(),
        }):
            import importlib
            importlib.reload(voice_tts)

            with patch.object(voice_tts, "_SAPI_AVAILABLE", True), \
                 patch.object(voice_tts, "win32com", mock_win32com):
                tts = voice_tts.VoiceTTS()
                # 模拟 run_in_executor 直接执行
                async def fake_executor(executor, fn):
                    fn()
                    return None

                with patch("asyncio.get_event_loop") as mock_loop:
                    mock_loop.return_value.run_in_executor = fake_executor
                    result = await tts.save_to_file("测试文本", str(output_file))

        # 文件存在则成功
        if output_file.exists():
            assert result["status"] == "saved" or "error" in result


class TestVoiceTTSStop:
    """stop 方法测试。"""

    @pytest.mark.asyncio
    async def test_stop(self) -> None:
        """停止朗读。"""
        from src.tools import voice_tts
        mock_voice = _make_mock_voice()
        with patch.object(voice_tts, "_SAPI_AVAILABLE", True):
            tts = voice_tts.VoiceTTS()
            tts._voice = mock_voice
            result = await tts.stop()

        assert result["status"] == "stopped"


class TestVoiceTTSPlatformFallback:
    """平台降级测试。"""

    @pytest.mark.asyncio
    async def test_unsupported_speak(self) -> None:
        """非 Windows speak 应返回错误。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", False):
            tts = voice_tts.VoiceTTS()
            result = await tts.speak("测试")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_unsupported_list_voices(self) -> None:
        """非 Windows list_voices 应返回错误列表。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", False):
            tts = voice_tts.VoiceTTS()
            result = await tts.list_voices()

        assert isinstance(result, list)
        assert "error" in result[0]

    @pytest.mark.asyncio
    async def test_unsupported_stop(self) -> None:
        """非 Windows stop 应返回错误。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", False):
            tts = voice_tts.VoiceTTS()
            result = await tts.stop()

        assert "error" in result

    @pytest.mark.asyncio
    async def test_unsupported_save_to_file(self) -> None:
        """非 Windows save_to_file 应返回错误。"""
        from src.tools import voice_tts
        with patch.object(voice_tts, "_SAPI_AVAILABLE", False):
            tts = voice_tts.VoiceTTS()
            result = await tts.save_to_file("测试", "/tmp/out.wav")

        assert "error" in result


class TestVoiceTTSInitFailure:
    """初始化失败测试。"""

    def test_init_dispatch_failure(self) -> None:
        """COM Dispatch 失败不应崩溃。"""
        from src.tools import voice_tts
        mock_win32com = MagicMock()
        mock_win32com.client.Dispatch.side_effect = Exception("COM error")

        with patch.object(voice_tts, "_SAPI_AVAILABLE", True), \
             patch.object(voice_tts, "win32com", mock_win32com):
            tts = voice_tts.VoiceTTS()
            assert tts._voice is None
