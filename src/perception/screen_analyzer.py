"""屏幕分析器。

使用多模态 LLM 分析屏幕截图，支持描述、定位、综合分析三种模式。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from src.utils.config import PerceptionConfig
from src.utils.llm_client import LLMClient


# ── 系统提示词 ──────────────────────────────────────────────

_DESCRIBE_SYSTEM = (
    "你是一个屏幕内容分析助手。用户会给你一张屏幕截图，"
    "请详细描述屏幕上的内容，包括：\n"
    "- 当前活动窗口/应用程序\n"
    "- 可见的 UI 元素（按钮、菜单、输入框等）\n"
    "- 显示的文本内容摘要\n"
    "- 屏幕整体布局\n"
    "请用简洁清晰的中文描述。"
)

_LOCATE_SYSTEM = (
    "你是一个 UI 元素定位助手。用户会给你一张屏幕截图和需要定位的目标元素描述。"
    "请在截图中找到该元素，并返回其中心坐标。\n\n"
    "请严格按以下 JSON 格式回复，不要包含其他内容：\n"
    '{"found": true, "x": <x坐标>, "y": <y坐标>, "description": "<对找到元素的简短描述>"}\n'
    "如果未找到该元素，请回复：\n"
    '{"found": false, "x": null, "y": null, "description": "<未找到的原因>"}\n'
    "坐标应为元素中心的像素坐标。"
)

_ANALYZE_SYSTEM = (
    "你是一个智能助手，能分析屏幕截图并建议下一步操作。"
    "用户会给你一张屏幕截图，请：\n"
    "1. 描述屏幕上当前的内容\n"
    "2. 判断当前处于什么状态/场景\n"
    "3. 建议接下来可以执行的操作\n\n"
    "请用中文回复，结构清晰。"
)


@dataclass
class LocateResult:
    """定位结果。"""

    found: bool
    x: int | None = None
    y: int | None = None
    description: str = ""


@dataclass
class AnalysisResult:
    """综合分析结果。"""

    description: str = ""
    scene: str = ""
    suggestions: list[str] = field(default_factory=list)


class ScreenAnalyzer:
    """屏幕内容分析器。

    接收截图的 bytes 数据，通过多模态 LLM 分析屏幕内容。

    Usage::

        analyzer = ScreenAnalyzer(llm_client, config)
        desc = await analyzer.describe(screenshot_bytes)
        loc = await analyzer.locate(screenshot_bytes, "保存按钮")
        result = await analyzer.analyze(screenshot_bytes)
    """

    def __init__(self, llm: LLMClient, config: PerceptionConfig) -> None:
        self._llm = llm
        self._config = config

    async def describe(self, screenshot: bytes) -> str:
        """描述当前屏幕内容。

        Args:
            screenshot: PNG 格式的截图 bytes

        Returns:
            屏幕内容的文字描述
        """
        if not self._config.enabled:
            logger.warning("视觉感知模块已禁用")
            return ""

        logger.debug("开始描述屏幕内容")
        try:
            result = await self._llm.chat_with_image(
                system_prompt=_DESCRIBE_SYSTEM,
                user_text="请描述这张屏幕截图的内容。",
                image_bytes=screenshot,
                detail=self._config.image_detail,
                provider=self._config.provider,
                max_tokens=self._config.describe_max_tokens,
            )
            logger.debug(f"屏幕描述完成，长度: {len(result)} 字符")
            return result.strip()
        except Exception as e:
            logger.error(f"屏幕描述失败: {e}")
            return f"[屏幕描述失败: {e}]"

    async def locate(self, screenshot: bytes, target: str) -> LocateResult:
        """在屏幕上定位特定 UI 元素。

        Args:
            screenshot: PNG 格式的截图 bytes
            target: 要定位的 UI 元素描述（如 "保存按钮"、"关闭图标"）

        Returns:
            LocateResult 包含是否找到、坐标和描述
        """
        if not self._config.enabled:
            logger.warning("视觉感知模块已禁用")
            return LocateResult(found=False, description="视觉感知模块已禁用")

        logger.debug(f"开始定位 UI 元素: {target}")
        try:
            raw = await self._llm.chat_with_image(
                system_prompt=_LOCATE_SYSTEM,
                user_text=f'请在截图中定位: "{target}"',
                image_bytes=screenshot,
                detail=self._config.image_detail,
                provider=self._config.provider,
                max_tokens=self._config.locate_max_tokens,
            )
            result = self._parse_locate_response(raw)
            if result.found:
                logger.info(f"找到 {target}: ({result.x}, {result.y})")
            else:
                logger.info(f"未找到 {target}: {result.description}")
            return result
        except Exception as e:
            logger.error(f"UI 元素定位失败: {e}")
            return LocateResult(found=False, description=f"定位失败: {e}")

    async def analyze(self, screenshot: bytes) -> AnalysisResult:
        """综合分析屏幕内容。

        包含描述、场景判断和下一步建议。

        Args:
            screenshot: PNG 格式的截图 bytes

        Returns:
            AnalysisResult 包含描述、场景和建议
        """
        if not self._config.enabled:
            logger.warning("视觉感知模块已禁用")
            return AnalysisResult(description="视觉感知模块已禁用")

        logger.debug("开始综合分析屏幕内容")
        try:
            raw = await self._llm.chat_with_image(
                system_prompt=_ANALYZE_SYSTEM,
                user_text="请综合分析这张屏幕截图。",
                image_bytes=screenshot,
                detail=self._config.image_detail,
                provider=self._config.provider,
                max_tokens=self._config.analyze_max_tokens,
            )
            result = self._parse_analyze_response(raw)
            logger.debug(f"分析完成，场景: {result.scene}，建议数: {len(result.suggestions)}")
            return result
        except Exception as e:
            logger.error(f"屏幕分析失败: {e}")
            return AnalysisResult(description=f"分析失败: {e}")

    @staticmethod
    def _parse_locate_response(raw: str) -> LocateResult:
        """解析定位模式的 LLM 响应。

        Args:
            raw: LLM 返回的原始文本

        Returns:
            解析后的 LocateResult
        """
        # 尝试提取 JSON（LLM 可能在 JSON 前后附加额外文本）
        json_match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if not json_match:
            logger.warning(f"无法从 LLM 响应中提取 JSON: {raw[:200]}")
            return LocateResult(found=False, description=f"无法解析响应: {raw[:100]}")

        try:
            data: dict[str, Any] = json.loads(json_match.group())
            found = bool(data.get("found", False))
            x = data.get("x")
            y = data.get("y")
            desc = data.get("description", "")

            if found and isinstance(x, (int, float)) and isinstance(y, (int, float)):
                return LocateResult(found=True, x=int(x), y=int(y), description=desc)
            return LocateResult(found=False, description=desc or "未找到元素")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"JSON 解析失败: {e}, 原始内容: {raw[:200]}")
            return LocateResult(found=False, description=f"JSON 解析失败: {e}")

    @staticmethod
    def _parse_analyze_response(raw: str) -> AnalysisResult:
        """解析综合分析模式的 LLM 响应。

        尝试从自由格式文本中提取描述、场景和建议。

        Args:
            raw: LLM 返回的原始文本

        Returns:
            解析后的 AnalysisResult
        """
        text = raw.strip()
        description = text
        scene = ""
        suggestions: list[str] = []

        # 尝试提取场景关键词
        scene_patterns = [
            r"当前(?:状态|场景)[：:]\s*(.+)",
            r"场景[：:]\s*(.+)",
        ]
        for pat in scene_patterns:
            m = re.search(pat, text)
            if m:
                scene = m.group(1).strip()
                break

        # 尝试提取建议列表
        suggestion_lines: list[str] = []
        in_suggestions = False
        for line in text.split("\n"):
            stripped = line.strip()
            if re.match(r"(?:建议|下一步|可以执行)", stripped):
                in_suggestions = True
                # 可能同行有内容
                rest = re.sub(r"^(?:建议|下一步|可以执行)[^\n：:]*[：:]?\s*", "", stripped)
                if rest:
                    suggestion_lines.append(rest)
                continue
            if in_suggestions:
                # 匹配列表项 (1. xxx / - xxx / * xxx / • xxx)
                item_match = re.match(r"(?:\d+[.、)\s]|[•\-*])\s*(.+)", stripped)
                if item_match:
                    suggestion_lines.append(item_match.group(1).strip())
                elif stripped:
                    # 非列表行说明建议部分结束
                    break

        if suggestion_lines:
            suggestions = suggestion_lines

        return AnalysisResult(description=description, scene=scene, suggestions=suggestions)
