"""LLM 客户端测试。"""

from __future__ import annotations

import base64
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


class TestBuildImageContent:
    """测试 build_image_content() 静态方法。"""

    def test_creates_text_and_image_parts(self) -> None:
        image_data = b"\x89PNG\x0d\x0a\x1a\x0a"
        content = LLMClient.build_image_content("描述图片", image_data)

        assert len(content) == 2
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "描述图片"
        assert content[1]["type"] == "image_url"
        assert "image_url" in content[1]

        url = content[1]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        assert base64.b64encode(image_data).decode() in url

    def test_custom_format(self) -> None:
        content = LLMClient.build_image_content("test", b"abc", image_format="jpeg")
        url = content[1]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")

    def test_custom_detail(self) -> None:
        content = LLMClient.build_image_content("test", b"abc", detail="high")
        assert content[1]["image_url"]["detail"] == "high"

    def test_base64_encoding_correct(self) -> None:
        data = b"hello world"
        content = LLMClient.build_image_content("test", data)
        url = content[1]["image_url"]["url"]
        b64_part = url.split(",")[1]
        assert base64.b64decode(b64_part) == data


class TestChatWithImage:
    """测试 chat_with_image() 多模态方法。"""

    @pytest.mark.asyncio
    async def test_sends_multimodal_messages(self) -> None:
        config = _make_config()
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "这是一张截图"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post.return_value = mock_response
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "sk-test"}):
            with patch("src.utils.llm_client.httpx.AsyncClient", return_value=mock_httpx_client):
                result = await client.chat_with_image(
                    system_prompt="你是屏幕分析助手",
                    user_text="描述截图",
                    image_bytes=b"fake_png_data",
                    detail="low",
                    max_tokens=512,
                )
                assert result == "这是一张截图"
                call_kwargs = mock_httpx_client.post.call_args.kwargs
                messages = call_kwargs.get("json", {})["messages"]
                assert len(messages) == 2
                assert messages[0]["role"] == "system"
                assert messages[0]["content"] == "你是屏幕分析助手"
                # user message should have multimodal content
                user_content = messages[1]["content"]
                assert isinstance(user_content, list)
                assert user_content[0]["type"] == "text"
                assert user_content[1]["type"] == "image_url"
                assert messages[1]["role"] == "user"

    @pytest.mark.asyncio
    async def test_custom_params_passed(self) -> None:
        config = _make_config()
        client = LLMClient(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "ok"}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_httpx_client = AsyncMock()
        mock_httpx_client.post.return_value = mock_response
        mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
        mock_httpx_client.__aexit__ = AsyncMock(return_value=False)

        with patch.dict(os.environ, {"ZHIPUAI_API_KEY": "sk-test"}):
            with patch("src.utils.llm_client.httpx.AsyncClient", return_value=mock_httpx_client):
                await client.chat_with_image(
                    system_prompt="sys",
                    user_text="user",
                    image_bytes=b"data",
                    provider="openai",
                    temperature=0.2,
                    max_tokens=256,
                )
                call_kwargs = mock_httpx_client.post.call_args.kwargs
                payload = call_kwargs.get("json", {})
                assert payload["temperature"] == 0.2
                assert payload["max_tokens"] == 256
