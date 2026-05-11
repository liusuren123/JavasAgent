"""CLI voice 子命令测试。

验证 voice 命令的 CLI 参数解析和配置集成。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from src.main import cli
from src.utils.config import (
    AppConfig,
    STTConfig,
    TTSConfig,
    VADConfig,
    VoiceConfig,
    VoicePipelineConfigModel,
    WakeWordConfig,
)


# ---------------------------------------------------------------------------
# VoiceConfig 测试
# ---------------------------------------------------------------------------


class TestVoiceConfig:
    """Voice 配置模型测试。"""

    def test_defaults(self) -> None:
        """默认值应符合设计。"""
        vc = VoiceConfig()
        assert vc.wake_word.enabled is True
        assert vc.wake_word.keywords == ["porcupine"]
        assert vc.wake_word.sensitivity == 0.5
        assert vc.vad.engine == "silero"
        assert vc.vad.threshold == 0.5
        assert vc.vad.silence_timeout == 1.5
        assert vc.stt.engine == "auto"
        assert vc.stt.language == "zh-CN"
        assert vc.tts.engine == "auto"
        assert vc.tts.rate == 200
        assert vc.tts.volume == 1.0
        assert vc.pipeline.continuous_mode is False
        assert vc.pipeline.continuous_timeout == 30.0
        assert vc.pipeline.interruption_enabled is True
        assert vc.pipeline.greeting == "我在，请说。"
        assert vc.pipeline.farewell == "再见。"

    def test_custom(self) -> None:
        """自定义配置应正确覆盖。"""
        vc = VoiceConfig(
            wake_word=WakeWordConfig(enabled=False, keywords=["贾维斯"]),
            vad=VADConfig(threshold=0.7),
            stt=STTConfig(language="en-US"),
            tts=TTSConfig(rate=150),
            pipeline=VoicePipelineConfigModel(continuous_mode=True, continuous_timeout=60.0),
        )
        assert vc.wake_word.enabled is False
        assert vc.wake_word.keywords == ["贾维斯"]
        assert vc.vad.threshold == 0.7
        assert vc.stt.language == "en-US"
        assert vc.tts.rate == 150
        assert vc.pipeline.continuous_mode is True
        assert vc.pipeline.continuous_timeout == 60.0

    def test_in_app_config(self) -> None:
        """VoiceConfig 应集成到 AppConfig 中。"""
        ac = AppConfig()
        assert isinstance(ac.voice, VoiceConfig)

    def test_yaml_round_trip(self) -> None:
        """从 dict 构造应正常工作（模拟 YAML 加载）。"""
        raw = {
            "voice": {
                "wake_word": {"enabled": False, "keywords": ["jarvis"], "sensitivity": 0.8},
                "vad": {"engine": "webrtcvad", "threshold": 0.6},
                "stt": {"engine": "whisper", "language": "en-US"},
                "tts": {"engine": "edge", "voice": "zh-CN-XiaoxiaoNeural", "rate": 180},
                "pipeline": {
                    "continuous_mode": True,
                    "continuous_timeout": 45.0,
                    "interruption_enabled": False,
                    "greeting": "Hi there.",
                    "farewell": "Bye.",
                },
            }
        }
        ac = AppConfig(**raw)
        assert ac.voice.wake_word.enabled is False
        assert ac.voice.wake_word.keywords == ["jarvis"]
        assert ac.voice.vad.engine == "webrtcvad"
        assert ac.voice.pipeline.greeting == "Hi there."
        assert ac.voice.pipeline.farewell == "Bye."


# ---------------------------------------------------------------------------
# CLI voice 子命令测试
# ---------------------------------------------------------------------------


class TestVoiceListKeywords:
    """--list-keywords 命令测试。"""

    @patch("src.main.load_config")
    def test_list_keywords_default(self, mock_load: MagicMock) -> None:
        """默认唤醒词列表应输出。"""
        mock_load.return_value = AppConfig()
        runner = CliRunner()
        result = runner.invoke(cli, ["voice", "--list-keywords"])
        assert result.exit_code == 0
        assert "porcupine" in result.output

    @patch("src.main.load_config")
    def test_list_keywords_custom(self, mock_load: MagicMock) -> None:
        """自定义唤醒词应正确输出。"""
        cfg = AppConfig(voice=VoiceConfig(wake_word=WakeWordConfig(keywords=["贾维斯", "jarvis"])))
        mock_load.return_value = cfg
        runner = CliRunner()
        result = runner.invoke(cli, ["voice", "--list-keywords"])
        assert result.exit_code == 0
        assert "贾维斯" in result.output
        assert "jarvis" in result.output


class TestVoiceNoWake:
    """--no-wake 参数测试。"""

    @patch("src.main.load_config")
    @patch("src.main.create_agent")
    @patch("src.main.VoiceOps")
    def test_no_wake_flag(self, mock_ops_cls: MagicMock, mock_create: MagicMock, mock_load: MagicMock) -> None:
        """--no-wake 应禁用唤醒词。"""
        mock_load.return_value = AppConfig()
        mock_agent = MagicMock()
        mock_agent.initialize_memory = AsyncMock()
        mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
        mock_agent.__aexit__ = AsyncMock(return_value=False)
        mock_create.return_value = mock_agent

        # Mock VoicePipeline.start to exit quickly
        with patch("src.voice.pipeline.VoicePipeline") as mock_pipeline_cls:
            mock_pipeline = MagicMock()
            mock_pipeline.start = AsyncMock()
            mock_pipeline.stop = AsyncMock()
            mock_pipeline.is_running = False
            mock_pipeline_cls.return_value = mock_pipeline

            runner = CliRunner()
            result = runner.invoke(cli, ["voice", "--no-wake"])

            # 验证 VoicePipelineConfig 传入了 wake_word_enabled=False
            call_args = mock_pipeline_cls.call_args
            pipeline_config = call_args[0][2]  # 第三个参数
            assert pipeline_config.wake_word_enabled is False


class TestVoiceContinuous:
    """--continuous 参数测试。"""

    @patch("src.main.load_config")
    @patch("src.main.create_agent")
    @patch("src.main.VoiceOps")
    def test_continuous_flag(self, mock_ops_cls: MagicMock, mock_create: MagicMock, mock_load: MagicMock) -> None:
        """--continuous 应启用连续对话模式。"""
        mock_load.return_value = AppConfig()
        mock_agent = MagicMock()
        mock_agent.initialize_memory = AsyncMock()
        mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
        mock_agent.__aexit__ = AsyncMock(return_value=False)
        mock_create.return_value = mock_agent

        with patch("src.voice.pipeline.VoicePipeline") as mock_pipeline_cls:
            mock_pipeline = MagicMock()
            mock_pipeline.start = AsyncMock()
            mock_pipeline.stop = AsyncMock()
            mock_pipeline.is_running = False
            mock_pipeline_cls.return_value = mock_pipeline

            runner = CliRunner()
            result = runner.invoke(cli, ["voice", "--continuous"])

            call_args = mock_pipeline_cls.call_args
            pipeline_config = call_args[0][2]
            assert pipeline_config.continuous_mode is True


class TestVoiceKeyword:
    """--keyword 参数测试。"""

    @patch("src.main.load_config")
    @patch("src.main.create_agent")
    @patch("src.main.VoiceOps")
    def test_keyword_override(self, mock_ops_cls: MagicMock, mock_create: MagicMock, mock_load: MagicMock) -> None:
        """--keyword 应覆盖默认唤醒词。"""
        mock_load.return_value = AppConfig()
        mock_agent = MagicMock()
        mock_agent.initialize_memory = AsyncMock()
        mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
        mock_agent.__aexit__ = AsyncMock(return_value=False)
        mock_create.return_value = mock_agent

        with patch("src.voice.pipeline.VoicePipeline") as mock_pipeline_cls:
            mock_pipeline = MagicMock()
            mock_pipeline.start = AsyncMock()
            mock_pipeline.stop = AsyncMock()
            mock_pipeline.is_running = False
            mock_pipeline_cls.return_value = mock_pipeline

            runner = CliRunner()
            result = runner.invoke(cli, ["voice", "--keyword", "贾维斯"])

            call_args = mock_pipeline_cls.call_args
            pipeline_config = call_args[0][2]
            assert pipeline_config.wake_words == ["贾维斯"]
            assert pipeline_config.wake_word_enabled is True


class TestVoiceCombined:
    """组合参数测试。"""

    @patch("src.main.load_config")
    @patch("src.main.create_agent")
    @patch("src.main.VoiceOps")
    def test_no_wake_continuous(self, mock_ops_cls: MagicMock, mock_create: MagicMock, mock_load: MagicMock) -> None:
        """--no-wake + --continuous 组合。"""
        mock_load.return_value = AppConfig()
        mock_agent = MagicMock()
        mock_agent.initialize_memory = AsyncMock()
        mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
        mock_agent.__aexit__ = AsyncMock(return_value=False)
        mock_create.return_value = mock_agent

        with patch("src.voice.pipeline.VoicePipeline") as mock_pipeline_cls:
            mock_pipeline = MagicMock()
            mock_pipeline.start = AsyncMock()
            mock_pipeline.stop = AsyncMock()
            mock_pipeline.is_running = False
            mock_pipeline_cls.return_value = mock_pipeline

            runner = CliRunner()
            result = runner.invoke(cli, ["voice", "--no-wake", "--continuous"])

            call_args = mock_pipeline_cls.call_args
            pipeline_config = call_args[0][2]
            assert pipeline_config.wake_word_enabled is False
            assert pipeline_config.continuous_mode is True

    @patch("src.main.load_config")
    @patch("src.main.create_agent")
    @patch("src.main.VoiceOps")
    def test_config_values_propagated(self, mock_ops_cls: MagicMock, mock_create: MagicMock, mock_load: MagicMock) -> None:
        """YAML 配置值应正确传播到管道配置。"""
        custom_cfg = AppConfig(
            voice=VoiceConfig(
                vad=VADConfig(threshold=0.8),
                stt=STTConfig(engine="whisper"),
                pipeline=VoicePipelineConfigModel(greeting="Hello!", farewell="Bye!"),
            )
        )
        mock_load.return_value = custom_cfg
        mock_agent = MagicMock()
        mock_agent.initialize_memory = AsyncMock()
        mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
        mock_agent.__aexit__ = AsyncMock(return_value=False)
        mock_create.return_value = mock_agent

        with patch("src.voice.pipeline.VoicePipeline") as mock_pipeline_cls:
            mock_pipeline = MagicMock()
            mock_pipeline.start = AsyncMock()
            mock_pipeline.stop = AsyncMock()
            mock_pipeline.is_running = False
            mock_pipeline_cls.return_value = mock_pipeline

            runner = CliRunner()
            result = runner.invoke(cli, ["voice"])

            call_args = mock_pipeline_cls.call_args
            pipeline_config = call_args[0][2]
            assert pipeline_config.vad_threshold == 0.8
            assert pipeline_config.stt_engine == "whisper"
            assert pipeline_config.greeting == "Hello!"
            assert pipeline_config.farewell == "Bye!"
