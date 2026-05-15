"""AI 辅助 UI 元素检测器。

使用本地 Ollama 多模态模型（qwen3-vl）分析截图，
检测 UIA 可能遗漏的 UI 元素，作为 UIADetector 的补充。

设计原则：
- 不引入重量级依赖（OmniParser 等），优先用本地模型
- 返回标准的 UIElement 列表，与 UIADetector 结果格式一致
- 支持同步和异步调用
"""

from __future__ import annotations

import base64
import io
import json
import logging
from typing import Sequence

import httpx
from PIL import Image

from src.perception.ui_detector import UIElement

logger = logging.getLogger(__name__)

# 默认 Ollama 配置
DEFAULT_OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "qwen3-vl:8b"

# AI 检测提示词
DETECTION_PROMPT = """Analyze this screenshot of a desktop application. Identify all interactive UI elements.

Return a JSON array. Each element should have:
- "bbox": [x1, y1, x2, y2] — bounding box in pixel coordinates
- "type": element type — one of: button, input, text, link, checkbox, dropdown, tab, menu, icon, panel, scrollbar, slider, other
- "text": visible text on or near the element (empty string if none)
- "confidence": 0.0 to 1.0

IMPORTANT: Return ONLY the JSON array, no other text. Example:
[{"bbox": [100, 200, 300, 240], "type": "button", "text": "Save", "confidence": 0.95}]
"""


class AIDetector:
    """AI 辅助 UI 元素检测器。

    使用多模态 LLM 分析截图，返回 UIElement 列表。
    """

    def __init__(
        self,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
    ) -> None:
        self.ollama_url = ollama_url
        self.model = model
        self.timeout = timeout

    def detect(
        self,
        screenshot: str | Image.Image,
        region: tuple[int, int, int, int] | None = None,
    ) -> list[UIElement]:
        """分析截图，返回检测到的 UI 元素。

        Args:
            screenshot: 截图路径（str）或 PIL Image 对象
            region: 可选，只分析指定区域 (x1, y1, x2, y2)

        Returns:
            检测到的 UIElement 列表，source="ai"
        """
        # 加载图片
        if isinstance(screenshot, str):
            img = Image.open(screenshot)
        else:
            img = screenshot

        # 裁剪区域
        if region:
            img = img.crop(region)

        # 编码为 base64
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # 调用 Ollama
        try:
            elements = self._call_ollama(img_b64)
        except Exception as e:
            logger.error(f"AI 检测失败: {e}")
            return []

        # 如果有区域偏移，调整坐标
        if region:
            x_off, y_off = region[0], region[1]
            for elem in elements:
                elem.bbox = (
                    elem.bbox[0] + x_off,
                    elem.bbox[1] + y_off,
                    elem.bbox[2] + x_off,
                    elem.bbox[3] + y_off,
                )

        return elements

    def _call_ollama(self, img_b64: str) -> list[UIElement]:
        """调用 Ollama 多模态模型进行检测。"""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DETECTION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": f"data:image/png;base64,{img_b64}",
                        },
                    ],
                }
            ],
            "stream": False,
            "options": {"temperature": 0.1},
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.ollama_url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # 解析响应
        content = data.get("message", {}).get("content", "")
        return self._parse_response(content)

    def _parse_response(self, content: str) -> list[UIElement]:
        """解析 LLM 返回的 JSON 为 UIElement 列表。"""
        # 尝试提取 JSON 数组
        content = content.strip()

        # 去掉可能的 markdown 代码块标记
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1])

        # 尝试找到 JSON 数组
        start = content.find("[")
        end = content.rfind("]")
        if start == -1 or end == -1:
            logger.warning(f"AI 响应中未找到 JSON 数组: {content[:200]}")
            return []

        json_str = content[start : end + 1]

        try:
            items = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"AI 响应 JSON 解析失败: {e}")
            return []

        elements = []
        for item in items:
            if not isinstance(item, dict):
                continue

            bbox = item.get("bbox")
            if not bbox or len(bbox) != 4:
                continue

            elem = UIElement(
                bbox=(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])),
                type=item.get("type", "other"),
                text=item.get("text", ""),
                confidence=float(item.get("confidence", 0.5)),
                source="ai",
                clickable=item.get("type", "") in (
                    "button", "link", "checkbox", "dropdown",
                    "tab", "menu", "icon", "slider",
                ),
                actionable=item.get("type", "") in (
                    "button", "input", "dropdown", "checkbox",
                    "tab", "slider", "link",
                ),
            )
            elements.append(elem)

        logger.info(f"AI 检测到 {len(elements)} 个 UI 元素")
        return elements
