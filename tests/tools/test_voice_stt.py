"""VoiceSTT 和 VoiceOps 测试。

验证 STT 语音识别工具和 VoiceOps 门面模块的正常路径和错误处理。
使用 Mock 替代 win32com.client，不依赖实际 COM 组件。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 创建 mock COM 对象
# ---------------------------------------------------------------------------
def _make_mock_recognizer():
    """创建模拟的 SAPI 识别器 COM 对象。"""
    recognizer = MagicMock()
    tokens = MagicMock()
    tokens.Count = 1

    item0 = MagicMock()
    item0.GetDescription.return_value = "Microsoft Speech Recognizer zh-CN"
    item0.GetAttribute.side_effect = lambda k: {
        "Language": "804", "Name": "MSR-zh-CN"
    }.get(k, "")

    tokens.Item.side_effect = [item0]
    recognizer.GetRecognizers.return_value = tokens
    recognizer.CreateRecoContext.return_value = MagicMock()
    return recognizer


def _make_mock_win32com(mock_recognizer=None):
    """创建 mock win32com 模块。"""
    m = MagicMock()
    if mock_recognizer:
        m.client.Dispatch.return_value = mock_recognizer
    return m


# ---------------------------------------------------------------------------
# VoiceSTT 测试
# ---------------------------------------------------------------------------
class TestVoiceSTTListen:
    """listen 方法测试。"""

    @pytest.mark.asyncio
    async def test_listen_with_sapi_sr(self) -> None:
        """SAPI SR 可用时使用识别。"""
        from src.tools import voice_stt
        mock_rec = _make_mock_recognizer()

        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            stt._sr_available = True
            stt._recognizer = mock_rec

            with patch.object(stt, "_listen_with_sapi", new_callable=AsyncMock) as mock_listen:
                mock_listen.return_value = {
                    "status": "recognized",
                    "text": "你好世界",
                    "timeout": 10.0,
                }
                result = await stt.listen(timeout=10.0)

        assert result["status"] == "recognized"
        assert result["text"] == "你好世界"
        mock_listen.assert_called_once_with(10.0)

    @pytest.mark.asyncio
    async def test_listen_fallback(self) -> None:
        """SAPI SR 不可用时回退。"""
        from src.tools import voice_stt

        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            stt._sr_available = False

            with patch.object(stt, "_fallback_record", new_callable=AsyncMock) as mock_fb:
                mock_fb.return_value = {
                    "status": "fallback",
                    "message": "SAPI 语音识别引擎不可用",
                }
                result = await stt.listen()

        assert result["status"] == "fallback"
        mock_fb.assert_called_once_with(10.0)

    @pytest.mark.asyncio
    async def test_listen_unsupported_platform(self) -> None:
        """非 Windows 平台应返回 unsupported。"""
        from src.tools import voice_stt
        with patch.object(voice_stt, "_SAPI_AVAILABLE", False):
            stt = voice_stt.VoiceSTT()
            result = await stt.listen()

        assert "error" in result
        assert "Windows" in result["error"]


class TestVoiceSTTRecognizeFile:
    """recognize_file 方法测试。"""

    @pytest.mark.asyncio
    async def test_file_not_exists(self) -> None:
        """不存在的文件应返回错误。"""
        from src.tools import voice_stt
        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            stt._voice = MagicMock()  # 跳过 null 检查
            result = await stt.recognize_file("/nonexistent/path/audio.wav")

        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_file_not_wav(self, tmp_path) -> None:
        """非 WAV 文件应返回错误。"""
        from src.tools import voice_stt
        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_text("fake mp3")

        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            result = await stt.recognize_file(str(mp3_file))

        assert "error" in result
        assert "WAV" in result["error"]

    @pytest.mark.asyncio
    async def test_file_sr_unavailable(self, tmp_path) -> None:
        """SR 不可用时应返回 unsupported。"""
        from src.tools import voice_stt
        wav_file = tmp_path / "test.wav"
        wav_file.write_text("fake wav")

        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            stt._sr_available = False
            result = await stt.recognize_file(str(wav_file))

        assert result["status"] == "unsupported"

    @pytest.mark.asyncio
    async def test_file_unsupported_platform(self) -> None:
        """非 Windows 平台应返回错误。"""
        from src.tools import voice_stt
        with patch.object(voice_stt, "_SAPI_AVAILABLE", False):
            stt = voice_stt.VoiceSTT()
            result = await stt.recognize_file("test.wav")

        assert "error" in result

    @pytest.mark.asyncio
    async def test_file_recognize_success(self, tmp_path) -> None:
        """SR 可用时识别文件。"""
        from src.tools import voice_stt
        wav_file = tmp_path / "test.wav"
        wav_file.write_text("fake wav")

        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            stt._sr_available = True

            with patch.object(stt, "_recognize_file_with_sapi", new_callable=AsyncMock) as mock_rf:
                mock_rf.return_value = {
                    "status": "recognized",
                    "text": "你好",
                    "path": str(wav_file),
                }
                result = await stt.recognize_file(str(wav_file))

        assert result["status"] == "recognized"
        assert result["text"] == "你好"


class TestVoiceSTTListRecognizers:
    """list_recognizers 方法测试。"""

    @pytest.mark.asyncio
    async def test_list_recognizers(self) -> None:
        """列出识别引擎。"""
        from src.tools import voice_stt

        # 直接构造 STT 并手动设置 recognizer
        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            stt._recognizer = _make_mock_recognizer()

            # Mock _extract_token_attr
            with patch.object(voice_stt.VoiceSTT, "_extract_token_attr", side_effect=lambda t, k: {
                "Language": "zh-CN", "Name": "MSR-zh-CN"
            }.get(k, "unknown")):
                result = await stt.list_recognizers()

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["name"] == "MSR-zh-CN"

    @pytest.mark.asyncio
    async def test_list_recognizers_unsupported(self) -> None:
        """非 Windows 平台应返回错误。"""
        from src.tools import voice_stt
        with patch.object(voice_stt, "_SAPI_AVAILABLE", False):
            stt = voice_stt.VoiceSTT()
            result = await stt.list_recognizers()

        assert isinstance(result, list)
        assert "error" in result[0]


class TestVoiceSTTInitFailure:
    """初始化失败测试。"""

    def test_init_sr_failure(self) -> None:
        """SR 初始化失败不应崩溃。"""
        from src.tools import voice_stt

        # _init_sapi_sr 内部调用 win32com.client.Dispatch，但模块没有 win32com
        # 所以 _init_sapi_sr 会因 NameError 进入 except，设置 _sr_available=False
        with patch.object(voice_stt, "_SAPI_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            # 由于 win32com 未安装，_init_sapi_sr 会失败，sr_available 保持 False
            assert stt._sr_available is False


# ---------------------------------------------------------------------------
# VoiceOps 门面测试
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
            mock_lv.return_value = [{"name": "Huihui"}]
            result = await ops.execute("list_voices", {})

        assert len(result) == 1
        mock_lv.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_save_to_file_routing(self) -> None:
        """save_to_file 应委托给 TTS。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._tts, "save_to_file", new_callable=AsyncMock) as mock_save:
            mock_save.return_value = {"status": "saved"}
            result = await ops.execute("save_to_file", {"text": "test", "output_path": "out.wav"})

        assert result["status"] == "saved"
        mock_save.assert_called_once_with(text="test", output_path="out.wav")

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
            result = await ops.execute("recognize_file", {"audio_path": "a.wav"})

        assert result["status"] == "recognized"
        mock_rf.assert_called_once_with(audio_path="a.wav")

    @pytest.mark.asyncio
    async def test_list_recognizers_routing(self) -> None:
        """list_recognizers 应委托给 STT。"""
        from src.tools.voice_ops import VoiceOps
        ops = VoiceOps()

        with patch.object(ops._stt, "list_recognizers", new_callable=AsyncMock) as mock_lr:
            mock_lr.return_value = [{"name": "MSR"}]
            result = await ops.execute("list_recognizers", {})

        assert len(result) == 1

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
