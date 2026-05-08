"""LLM 客户端测试。"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.utils.config import LLMConfig, LLMProviderConfig
from src.utils.llm_client import LLMClient


def _make_config() -> LLMConfig:
    return LLMConfig(
        default_provider="zhipuai",
        providers={
            "zhipuai": LLMProviderConfig(
                model="glm-4-plus",
                api_key_env="ZHIPUAI_API_KEY",
                base_url="https://open.bigmodel.cn/api/paas/v4",
            ),
            "openai": LLMProviderConfig(
                model="gpt-4",
                api_key_env="OPENAI_API_KEY",
                base_url="https://api.openai.com/v1",
            ),
        },
        temperature=0.7,
        max_tokens=4096,
    )


class TestGetApiKey:
    """测试 _get_api_key 环境变量读取。"""

    def test_returns_key_from_env(self) -> None:
        client = LLMClient(_make_config())
        provider = LLMProviderConfig(api_key_env="TEST_KEY_ENV")
        with patch.dict(os.environ, {"TEST_KEY_ENV": "sk-12345"}):
            assert client._get_api_key(provider) == "sk-12345"

    def test_returns_empty_when_not_set(self) -> None:
        client = LLMClient(_make_config())
        provider = LLMProviderConfig(api_key_env="NONEXISTENT_KEY_XYZ")
        env = os.environ.copy()
        env.pop("NONEXISTENT_KEY_XYZ", None)
        with patch.dict(os.environ, env, clear=True):
            assert client._get_api_key(provider) == ""


class TestGetProvider:
    """测试 _get_provider 方法。"""

    def test_default_provider(self) -> None:
        client = LLMClient(_make_config())
        name, prov = client._get_provider(None)
        assert name == "zhipuai"
        assert prov.model == "glm-4-plus"

    def test_named_provider(self) -> None:
        client = LLMClient(_make_config())
        name, prov = client._get_provider("openai")
        assert name == "openai"
        assert prov.model == "gpt-4"

    def test_missing_provider_raises(self) -> None:
        client = LLMClient(_make_config())
        with pytest.raises(ValueError, match="未配置的 LLM 提供商"):
            client._get_provider("nonexistent")

    def test_no_providers_raises(self) -> None:
        config = LLMConfig(default_provider="missing")
        client = LLMClient(config)
        with pytest.raises(ValueError):
            client._get_provider()


class TestChat:
    """测试 chat() 方法（mock httpx）。"""

    @pytest.mark.asyncio
    async def test_chat_success(self) -> None:
        config = _make_config()
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "你好，我是AI助手"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post.return_value = mock_response
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "sk-test"}):
            with patch("src.utils.llm_client.httpx.AsyncClient", return_value=mock_httpx_client):
                result = await client.chat(
                    messages=[{"role": "user", "content": "你好"}],
                )
                assert result == "你好，我是AI助手"

    @pytest.mark.asyncio
    async def test_chat_with_provider(self) -> None:
        config = _make_config()
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "GPT response"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post.return_value = mock_response
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-openai"}):
            with patch("src.utils.llm_client.httpx.AsyncClient", return_value=mock_httpx_client):
                result = await client.chat(
                    messages=[{"role": "user", "content": "test"}],
                    provider="openai",
                )
                assert result == "GPT response"
                call_args = mock_httpx_client.post.call_args
                url = call_args[0][0] if call_args[0] else call_args.kwargs.get("url", "")
                assert "openai.com" in url

    @pytest.mark.asyncio
    async def test_chat_custom_params(self) -> None:
        config = _make_config()
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "cold response"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post.return_value = mock_response
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "sk-test"}):
            with patch("src.utils.llm_client.httpx.AsyncClient", return_value=mock_httpx_client):
                result = await client.chat(
                    messages=[{"role": "user", "content": "test"}],
                    temperature=0.1,
                    max_tokens=100,
                )
                assert result == "cold response"
                call_kwargs = mock_httpx_client.post.call_args.kwargs
                payload = call_kwargs.get("json", {})
                assert payload["temperature"] == 0.1
                assert payload["max_tokens"] == 100


class TestChatWithSystem:
    """测试 chat_with_system() 快捷方法。"""

    @pytest.mark.asyncio
    async def test_builds_system_user_messages(self) -> None:
        config = _make_config()
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "planned"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post.return_value = mock_response
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "sk-test"}):
            with patch("src.utils.llm_client.httpx.AsyncClient", return_value=mock_httpx_client):
                result = await client.chat_with_system(
                    system_prompt="你是规划器",
                    user_message="规划任务",
                )
                assert result == "planned"
                call_kwargs = mock_httpx_client.post.call_args.kwargs
                messages = call_kwargs.get("json", {})["messages"]
                assert len(messages) == 2
                assert messages[0]["role"] == "system"
                assert messages[0]["content"] == "你是规划器"
                assert messages[1]["role"] == "user"
                assert messages[1]["content"] == "规划任务"
