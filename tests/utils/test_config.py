"""配置管理测试。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from src.utils.config import (
    AppConfig,
    AgentConfig,
    LLMConfig,
    LLMProviderConfig,
    MemoryConfig,
    PlatformConfig,
    ToolConfig,
    ToolsConfig,
    load_config,
)


class TestDefaultConfig:
    """测试默认配置值。"""

    def test_default_agent_config(self) -> None:
        cfg = AgentConfig()
        assert cfg.name == "JavasAgent"
        assert cfg.version == "0.1.0"
        assert cfg.ask_human_threshold == 0.6
        assert cfg.max_task_duration == 3600
        assert cfg.max_step_retries == 3

    def test_default_llm_config(self) -> None:
        cfg = LLMConfig()
        assert cfg.default_provider == "ollama"
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096

    def test_default_memory_config(self) -> None:
        cfg = MemoryConfig()
        assert cfg.short_term_max_messages == 50

    def test_default_platform_config(self) -> None:
        cfg = PlatformConfig()
        assert cfg.action_delay == 0.5
        assert cfg.log_level == "INFO"

    def test_default_app_config(self) -> None:
        cfg = AppConfig()
        assert isinstance(cfg.agent, AgentConfig)
        assert isinstance(cfg.llm, LLMConfig)
        assert isinstance(cfg.memory, MemoryConfig)
        assert isinstance(cfg.platform, PlatformConfig)
        assert isinstance(cfg.tools, ToolsConfig)

    def test_default_tools_config(self) -> None:
        cfg = ToolsConfig()
        assert cfg.system_control.enabled is True
        assert cfg.code_dev.enabled is True
        assert cfg.office_ops.enabled is False
        assert cfg.creative_tools.enabled is False


class TestLoadConfig:
    """测试 load_config() 函数。"""

    def test_missing_file_returns_default(self) -> None:
        cfg = load_config("/nonexistent/path/config.yaml")
        assert isinstance(cfg, AppConfig)
        assert cfg.agent.name == "JavasAgent"

    def test_load_from_yaml(self) -> None:
        data = {
            "agent": {"name": "CustomAgent", "ask_human_threshold": 0.8},
            "llm": {"temperature": 0.5, "max_tokens": 2048},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as f:
            yaml.dump(data, f)
            tmp_path = f.name

        try:
            cfg = load_config(tmp_path)
            assert cfg.agent.name == "CustomAgent"
            assert cfg.agent.ask_human_threshold == 0.8
            assert cfg.llm.temperature == 0.5
            assert cfg.llm.max_tokens == 2048
        finally:
            os.unlink(tmp_path)

    def test_partial_yaml_uses_defaults(self) -> None:
        data = {"agent": {"name": "Partial"}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as f:
            yaml.dump(data, f)
            tmp_path = f.name

        try:
            cfg = load_config(tmp_path)
            assert cfg.agent.name == "Partial"
            # other fields stay default
            assert cfg.agent.ask_human_threshold == 0.6
            assert cfg.llm.temperature == 0.7
        finally:
            os.unlink(tmp_path)

    def test_empty_yaml_returns_default(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as f:
            f.write("")
            tmp_path = f.name

        try:
            cfg = load_config(tmp_path)
            assert cfg.agent.name == "JavasAgent"
        finally:
            os.unlink(tmp_path)

    def test_load_with_providers(self) -> None:
        data = {
            "llm": {
                "default_provider": "openai",
                "providers": {
                    "openai": {
                        "model": "gpt-4",
                        "api_key_env": "OPENAI_API_KEY",
                        "base_url": "https://api.openai.com/v1",
                    },
                },
            },
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as f:
            yaml.dump(data, f)
            tmp_path = f.name

        try:
            cfg = load_config(tmp_path)
            assert "openai" in cfg.llm.providers
            assert cfg.llm.providers["openai"].model == "gpt-4"
        finally:
            os.unlink(tmp_path)

    def test_env_variable_override(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8",
        ) as f:
            yaml.dump({"agent": {"name": "EnvAgent"}}, f)
            tmp_path = f.name

        try:
            os.environ["JAVAS_CONFIG"] = tmp_path
            cfg = load_config()
            assert cfg.agent.name == "EnvAgent"
        finally:
            del os.environ["JAVAS_CONFIG"]
            os.unlink(tmp_path)


class TestPydanticValidation:
    """测试 pydantic 验证。"""

    def test_invalid_threshold_type(self) -> None:
        """ask_human_threshold 必须是 float。"""
        cfg = AgentConfig(ask_human_threshold=0.5)
        assert cfg.ask_human_threshold == 0.5

    def test_llm_provider_config(self) -> None:
        cfg = LLMProviderConfig(model="glm-4")
        assert cfg.model == "glm-4"
        assert cfg.api_key_env == "ZHIPUAI_API_KEY"

    def test_tool_config(self) -> None:
        cfg = ToolConfig(enabled=True)
        assert cfg.enabled is True


