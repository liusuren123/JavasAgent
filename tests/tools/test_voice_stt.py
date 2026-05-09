"""VoiceSTT 测试。

验证 STT 语音识别工具的正常路径和错误处理。
使用 Mock 替代 speech_recognition 和 whisper，不依赖外部服务。

覆盖：
  - 正常识别流程（Google SR / Whisper fallback）
  - 引擎不可用 fallback
  - 参数错误（空文件、不支持的格式）
  - 文件识别
  - 列出识别引擎
  - 超时处理
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_sr():
    """创建 mock speech_recognition 模块。"""
    m = MagicMock()

    # Mock Recognizer
    recognizer = MagicMock()
    recognizer.recognize_google.return_value = "你好世界"
    m.Recognizer.return_value = recognizer

    # Mock Microphone
    microphone = MagicMock()
    microphone.__enter__ = MagicMock(return_value=microphone)
    microphone.__exit__ = MagicMock(return_value=False)
    m.Microphone.return_value = microphone

    # Mock AudioFile
    audio_file = MagicMock()
    audio_file.__enter__ = MagicMock(return_value=audio_file)
    audio_file.__exit__ = MagicMock(return_value=False)
    m.AudioFile.return_value = audio_file

    # Mock exceptions
    m.WaitTimeoutError = type("WaitTimeoutError", (Exception,), {})
    m.UnknownValueError = type("UnknownValueError", (Exception,), {})
    m.RequestError = type("RequestError", (Exception,), {})

    return m


@pytest.fixture
def mock_whisper():
    """创建 mock whisper 模块。"""
    m = MagicMock()
    model = MagicMock()
    model.transcribe.return_value = {"text": "你好 whisper"}
    m.load_model.return_value = model
    return m


@pytest.fixture
def stt_with_sr(mock_sr):
    """创建使用 mock speech_recognition 的 VoiceSTT 实例。"""
    with patch.dict("sys.modules", {"speech_recognition": mock_sr}):
        from src.tools import voice_stt
        import importlib
        importlib.reload(voice_stt)

        with patch.object(voice_stt, "_SR_AVAILABLE", True):
            stt = voice_stt.VoiceSTT()
            yield stt, voice_stt, mock_sr


@pytest.fixture
def stt_no_sr():
    """创建无 SR 的 VoiceSTT 实例。"""
    from src.tools import voice_stt
    with patch.object(voice_stt, "_SR_AVAILABLE", False), \
         patch.object(voice_stt, "_WHISPER_AVAILABLE", False):
        stt = voice_stt.VoiceSTT()
        yield stt, voice_stt


# ---------------------------------------------------------------------------
# listen 测试
# ---------------------------------------------------------------------------


class TestVoiceSTTListen:
    """listen 方法测试。"""

    @pytest.mark.asyncio
    async def test_listen_google_success(self, stt_with_sr) -> None:
        """Google SR 正常识别。"""
        stt, module, mock_sr = stt_with_sr

        # 模拟 listen 返回 audio data
        mock_audio = MagicMock()
        mock_sr.Recognizer.return_value.listen.return_value = mock_audio
        mock_sr.Recognizer.return_value.recognize_google.return_value = "你好世界"

        result = await stt.listen(timeout=5.0)

        assert result["status"] == "recognized"
        assert result["text"] == "你好世界"
        assert result["engine"] == "google"

    @pytest.mark.asyncio
    async def test_listen_with_phrase_time_limit(self, stt_with_sr) -> None:
        """传入 phrase_time_limit 参数。"""
        stt, module, mock_sr = stt_with_sr
        mock_audio = MagicMock()
        mock_sr.Recognizer.return_value.listen.return_value = mock_audio
        mock_sr.Recognizer.return_value.recognize_google.return_value = "测试"

        result = await stt.listen(timeout=5.0, phrase_time_limit=3.0)

        assert result["status"] == "recognized"

    @pytest.mark.asyncio
    async def test_listen_timeout(self, stt_with_sr) -> None:
        """录音超时。"""
        stt, module, mock_sr = stt_with_sr

        # 模拟 WaitTimeoutError
        mock_sr.Recognizer.return_value.listen.side_effect = mock_sr.WaitTimeoutError()

        result = await stt.listen(timeout=1.0)

        assert result["status"] == "timeout"
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_listen_unrecognized(self, stt_with_sr) -> None:
        """无法识别语音。"""
        stt, module, mock_sr = stt_with_sr

        mock_audio = MagicMock()
        mock_sr.Recognizer.return_value.listen.return_value = mock_audio
        mock_sr.Recognizer.return_value.recognize_google.side_effect = (
            mock_sr.UnknownValueError()
        )

        result = await stt.listen(timeout=5.0)

        assert result["status"] == "no_result"
        assert result["text"] == ""

    @pytest.mark.asyncio
    async def test_listen_google_down_whisper_fallback(self, stt_with_sr, mock_whisper) -> None:
        """Google SR 不可用时 fallback 到 Whisper。"""
        stt, module, mock_sr = stt_with_sr

        mock_audio = MagicMock()
        mock_audio.get_wav_data.return_value = b"RIFF" + b"\x00" * 100
        mock_sr.Recognizer.return_value.listen.return_value = mock_audio
        mock_sr.Recognizer.return_value.recognize_google.side_effect = (
            mock_sr.RequestError("Service down")
        )

        with patch.object(module, "_WHISPER_AVAILABLE", True), \
             patch.object(module, "_whisper_module", mock_whisper):
            result = await stt.listen(timeout=5.0)

        assert result["status"] == "recognized"
        assert result["engine"] == "whisper"

    @pytest.mark.asyncio
    async def test_listen_no_sr(self, stt_no_sr) -> None:
        """SR 未安装应返回错误。"""
        stt, module = stt_no_sr
        result = await stt.listen()

        assert "error" in result


# ---------------------------------------------------------------------------
# recognize_file 测试
# ---------------------------------------------------------------------------


class TestVoiceSTTRecognizeFile:
    """recognize_file 方法测试。"""

    @pytest.mark.asyncio
    async def test_file_not_exists(self, stt_with_sr) -> None:
        """不存在的文件应返回错误。"""
        stt, module, mock_sr = stt_with_sr

        with patch("src.tools.voice_stt.safe_resolve_path") as mock_safe:
            mock_safe.return_value = Path("/nonexistent/path/audio.wav")
            with patch.object(Path, "exists", return_value=False):
                result = await stt.recognize_file("audio.wav")

        assert "error" in result
        assert "不存在" in result["error"]

    @pytest.mark.asyncio
    async def test_unsupported_format(self, stt_with_sr) -> None:
        """不支持的音频格式应返回错误。"""
        stt, module, mock_sr = stt_with_sr

        fake_path = Path("/fake/test.xyz")
        with patch("src.tools.voice_stt.safe_resolve_path", return_value=fake_path):
            with patch.object(Path, "exists", return_value=True):
                result = await stt.recognize_file("test.xyz")

        assert "error" in result
        assert "不支持" in result["error"]

    @pytest.mark.asyncio
    async def test_wav_file_google_success(self, stt_with_sr, tmp_path) -> None:
        """WAV 文件使用 Google SR 成功识别。"""
        stt, module, mock_sr = stt_with_sr

        wav_file = tmp_path / "test.wav"
        wav_file.write_bytes(b"RIFF" + b"\x00" * 100)

        mock_audio = MagicMock()
        mock_sr.Recognizer.return_value.record.return_value = mock_audio
        mock_sr.Recognizer.return_value.recognize_google.return_value = "你好"

        with patch("src.tools.voice_stt.safe_resolve_path", return_value=wav_file):
            result = await stt.recognize_file("test.wav")

        assert result["status"] == "recognized"
        assert result["text"] == "你好"
        assert result["engine"] == "google"

    @pytest.mark.asyncio
    async def test_non_wav_with_whisper(self, stt_with_sr, mock_whisper, tmp_path) -> None:
        """非 WAV 文件使用 Whisper 识别。"""
        stt, module, mock_sr = stt_with_sr

        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        with patch("src.tools.voice_stt.safe_resolve_path", return_value=mp3_file), \
             patch.object(module, "_WHISPER_AVAILABLE", True), \
             patch.object(module, "_whisper_module", mock_whisper):
            result = await stt.recognize_file("test.mp3")

        assert result["status"] == "recognized"
        assert result["engine"] == "whisper"

    @pytest.mark.asyncio
    async def test_non_wav_no_whisper(self, stt_with_sr, tmp_path) -> None:
        """非 WAV 文件且无 Whisper 应返回错误。"""
        stt, module, mock_sr = stt_with_sr

        mp3_file = tmp_path / "test.mp3"
        mp3_file.write_bytes(b"fake mp3 data")

        with patch("src.tools.voice_stt.safe_resolve_path", return_value=mp3_file), \
             patch.object(module, "_WHISPER_AVAILABLE", False):
            result = await stt.recognize_file("test.mp3")

        assert "error" in result
        assert "whisper" in result["error"].lower() or "WAV" in result["error"]

    @pytest.mark.asyncio
    async def test_unsafe_path(self, stt_with_sr) -> None:
        """不安全路径应返回错误。"""
        stt, module, mock_sr = stt_with_sr
        from src.utils.path_safety import PathSafetyError

        with patch(
            "src.tools.voice_stt.safe_resolve_path",
            side_effect=PathSafetyError("path traversal"),
        ):
            result = await stt.recognize_file("../../etc/passwd")

        assert "error" in result
        assert "路径" in result["error"]

    @pytest.mark.asyncio
    async def test_no_sr(self, stt_no_sr) -> None:
        """SR 未安装应返回错误。"""
        stt, module = stt_no_sr
        result = await stt.recognize_file("test.wav")

        assert "error" in result


# ---------------------------------------------------------------------------
# list_recognizers 测试
# ---------------------------------------------------------------------------


class TestVoiceSTTListRecognizers:
    """list_recognizers 方法测试。"""

    @pytest.mark.asyncio
    async def test_list_with_sr(self, stt_with_sr) -> None:
        """SR 可用时列出引擎。"""
        stt, module, mock_sr = stt_with_sr
        result = await stt.list_recognizers()

        assert result["status"] == "ok"
        assert len(result["engines"]) >= 1
        assert result["engines"][0]["name"] == "google"

    @pytest.mark.asyncio
    async def test_list_with_whisper(self, mock_sr, mock_whisper) -> None:
        """Whisper 可用时也列出。"""
        with patch.dict("sys.modules", {"speech_recognition": mock_sr, "whisper": mock_whisper}):
            from src.tools import voice_stt
            import importlib
            importlib.reload(voice_stt)

            with patch.object(voice_stt, "_SR_AVAILABLE", True), \
                 patch.object(voice_stt, "_WHISPER_AVAILABLE", True):
                stt = voice_stt.VoiceSTT()
                result = await stt.list_recognizers()

        assert result["status"] == "ok"
        engine_names = [e["name"] for e in result["engines"]]
        assert "google" in engine_names
        assert "whisper" in engine_names

    @pytest.mark.asyncio
    async def test_list_no_engine(self, stt_no_sr) -> None:
        """无引擎时返回空列表。"""
        stt, module = stt_no_sr
        result = await stt.list_recognizers()

        assert result["status"] == "ok"
        assert result["engines"] == []
