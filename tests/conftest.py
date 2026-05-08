"""测试配置和共享 fixtures。"""

from __future__ import annotations

import pytest

from src.utils.config import AppConfig, AgentConfig, LLMConfig


@pytest.fixture
def app_config() -> AppConfig:
    """创建测试用的配置。"""
    return AppConfig(
        agent=AgentConfig(
            name="TestAgent",
            ask_human_threshold=0.6,
            max_task_duration=60,
            max_step_retries=1,
        ),
        llm=LLMConfig(default_provider="zhipuai"),
    )
