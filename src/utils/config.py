"""配置管理模块。

使用 YAML 配置文件 + pydantic 进行类型安全的配置管理。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LLMProviderConfig(BaseModel):
    """单个 LLM 提供商配置。"""

    model: str = "glm-4-plus"
    api_key_env: str = "ZHIPUAI_API_KEY"
    base_url: str = "https://open.bigmodel.cn/api/paas/v4"


class LLMConfig(BaseModel):
    """LLM 配置。"""

    default_provider: str = "ollama"
    providers: dict[str, LLMProviderConfig] = Field(
        default_factory=lambda: {
            "ollama": LLMProviderConfig(
                model="qwen3.6",
                api_key_env="",
                base_url="http://localhost:11434/v1",
            ),
            "ollama-vision": LLMProviderConfig(
                model="qwen3.6",
                api_key_env="",
                base_url="http://localhost:11434/v1",
            ),
            "zhipuai": LLMProviderConfig(
                model="glm-4-plus",
                api_key_env="ZHIPUAI_API_KEY",
                base_url="https://open.bigmodel.cn/api/paas/v4",
            ),
            "openai": LLMProviderConfig(
                model="gpt-4o",
                api_key_env="OPENAI_API_KEY",
                base_url="https://api.openai.com/v1",
            ),
        }
    )
    temperature: float = 0.7
    max_tokens: int = 4096


class MemoryConfig(BaseModel):
    """记忆系统配置。"""

    short_term_max_messages: int = 50
    long_term_db_path: str = "./data/memory/chroma"
    embedding_model: str = "text-embedding-3-small"


class PlatformConfig(BaseModel):
    """平台配置。"""

    action_delay: float = 0.5
    screenshot_path: str = "./data/screenshots"
    log_level: str = "INFO"
    log_path: str = "./data/logs"


class ToolConfig(BaseModel):
    """单个工具配置。"""

    enabled: bool = False


class ToolsConfig(BaseModel):
    """工具集配置。"""

    system_control: ToolConfig = Field(default_factory=lambda: ToolConfig(enabled=True))
    code_dev: ToolConfig = Field(default_factory=lambda: ToolConfig(enabled=True))
    office_ops: ToolConfig = Field(default_factory=ToolConfig)
    creative_tools: ToolConfig = Field(default_factory=ToolConfig)
    browser_control: ToolConfig = Field(default_factory=ToolConfig)


class AgentConfig(BaseModel):
    """Agent 配置。"""

    name: str = "JavasAgent"
    version: str = "0.1.0"
    ask_human_threshold: float = 0.6
    max_task_duration: int = 3600
    max_step_retries: int = 3


class PerceptionConfig(BaseModel):
    """视觉感知配置。"""

    enabled: bool = True
    provider: str | None = None  # 使用哪个 LLM 提供商，None 表示默认
    describe_max_tokens: int = 1024
    locate_max_tokens: int = 512
    analyze_max_tokens: int = 2048
    image_detail: str = "auto"  # low / high / auto


class AppConfig(BaseModel):
    """应用全局配置。"""

    agent: AgentConfig = Field(default_factory=AgentConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    platform: PlatformConfig = Field(default_factory=PlatformConfig)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """加载配置文件。

    优先级：指定路径 > 环境变量 JAVAS_CONFIG > 项目根目录 config/default.yaml
    """
    if config_path is None:
        config_path = os.environ.get(
            "JAVAS_CONFIG",
            Path(__file__).parent.parent.parent / "config" / "default.yaml",
        )

    path = Path(config_path)
    if not path.exists():
        return AppConfig()

    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    return AppConfig(**raw)
