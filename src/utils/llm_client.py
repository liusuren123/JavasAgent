"""LLM 客户端模块。

支持多提供商（智谱、OpenAI 等）的统一 LLM 调用接口。
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger

from src.utils.config import LLMConfig, LLMProviderConfig


class LLMClient:
    """统一的 LLM 调用客户端。"""

    def __init__(self, config: LLMConfig) -> None:
        self._config = config
        self._clients: dict[str, httpx.AsyncClient] = {}

    def _get_api_key(self, provider: LLMProviderConfig) -> str:
        """从环境变量获取 API Key。"""
        key = os.environ.get(provider.api_key_env, "")
        if not key:
            logger.warning(f"环境变量 {provider.api_key_env} 未设置")
        return key

    def _get_provider(self, provider_name: str | None = None) -> tuple[str, LLMProviderConfig]:
        """获取指定的或默认的提供商配置。"""
        name = provider_name or self._config.default_provider
        if name not in self._config.providers:
            raise ValueError(f"未配置的 LLM 提供商: {name}")
        return name, self._config.providers[name]

    async def chat(
        self,
        messages: list[dict[str, str]],
        provider: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """发送聊天请求。

        Args:
            messages: 消息列表，格式 [{"role": "user", "content": "..."}]
            provider: 指定提供商，为 None 则使用默认
            temperature: 生成温度
            max_tokens: 最大生成 token 数

        Returns:
            模型的回复文本
        """
        name, prov = self._get_provider(provider)
        api_key = self._get_api_key(prov)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": prov.model,
            "messages": messages,
            "temperature": temperature or self._config.temperature,
            "max_tokens": max_tokens or self._config.max_tokens,
        }

        url = f"{prov.base_url.rstrip('/')}/chat/completions"

        async with httpx.AsyncClient(timeout=120.0) as client:
            logger.debug(f"LLM 请求: provider={name}, model={prov.model}")
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()

            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            logger.debug(f"LLM 响应长度: {len(content)} 字符")
            return content

    async def chat_with_system(
        self,
        system_prompt: str,
        user_message: str,
        provider: str | None = None,
    ) -> str:
        """带系统提示的聊天快捷方法。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return await self.chat(messages, provider=provider)
