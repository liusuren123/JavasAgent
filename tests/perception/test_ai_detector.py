"""AI 检测器和混合检测器测试。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from src.perception.ai_detector import AIDetector
from src.perception.hybrid_detector import HybridDetector
from src.perception.ui_detector import UIElement


# ---------------------------------------------------------------------------
# AIDetector 测试
# ---------------------------------------------------------------------------


class TestAIDetector:
    """AIDetector 单元测试（Mock Ollama 响应）。"""

    def _mock_ollama_response(self, elements: list[dict]) -> dict:
        """构造 mock Ollama 响应。"""
        content = json.dumps(elements)
        return {"message": {"content": content}}

    def test_parse_empty_response(self) -> None:
        """空响应返回空列表。"""
        detector = AIDetector()
        result = detector._parse_response("")
        assert result == []

    def test_parse_valid_json(self) -> None:
        """有效 JSON 返回正确的 UIElement 列表。"""
        detector = AIDetector()
        content = json.dumps([
            {"bbox": [10, 20, 100, 50], "type": "button", "text": "Click", "confidence": 0.9},
            {"bbox": [200, 300, 400, 340], "type": "input", "text": "", "confidence": 0.8},
        ])
        result = detector._parse_response(content)
        assert len(result) == 2
        assert result[0].type == "button"
        assert result[0].text == "Click"
        assert result[0].source == "ai"
        assert result[0].confidence == 0.9
        assert result[1].type == "input"

    def test_parse_markdown_wrapped_json(self) -> None:
        """markdown 代码块包裹的 JSON 也能解析。"""
        detector = AIDetector()
        content = '```json\n[{"bbox": [0, 0, 50, 30], "type": "text", "text": "Hi", "confidence": 0.7}]\n```'
        result = detector._parse_response(content)
        assert len(result) == 1
        assert result[0].text == "Hi"

    def test_parse_invalid_bbox_skipped(self) -> None:
        """无效 bbox 的元素被跳过。"""
        detector = AIDetector()
        content = json.dumps([
            {"bbox": [10], "type": "button", "text": "X", "confidence": 0.5},
            {"bbox": [10, 20, 100, 50], "type": "button", "text": "OK", "confidence": 0.9},
        ])
        result = detector._parse_response(content)
        assert len(result) == 1
        assert result[0].text == "OK"

    @patch("src.perception.ai_detector.httpx.Client")
    def test_detect_with_pil_image(self, mock_client_cls: MagicMock) -> None:
        """PIL Image 输入正常工作。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._mock_ollama_response([
            {"bbox": [0, 0, 100, 50], "type": "button", "text": "Test", "confidence": 0.95},
        ])
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        detector = AIDetector()
        img = Image.new("RGB", (200, 100), "white")
        result = detector.detect(img)
        assert len(result) == 1
        assert result[0].text == "Test"

    @patch("src.perception.ai_detector.httpx.Client")
    def test_detect_with_region(self, mock_client_cls: MagicMock) -> None:
        """指定区域检测时坐标正确偏移。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = self._mock_ollama_response([
            {"bbox": [0, 0, 50, 30], "type": "button", "text": "X", "confidence": 0.9},
        ])
        mock_resp.raise_for_status = MagicMock()

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        detector = AIDetector()
        img = Image.new("RGB", (500, 500), "white")
        result = detector.detect(img, region=(100, 200, 300, 400))
        assert len(result) == 1
        # 坐标应加上偏移 (100, 200)
        assert result[0].bbox == (100, 200, 150, 230)

    @patch("src.perception.ai_detector.httpx.Client")
    def test_detect_ollama_error(self, mock_client_cls: MagicMock) -> None:
        """Ollama 调用失败返回空列表。"""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.side_effect = Exception("connection refused")
        mock_client_cls.return_value = mock_client

        detector = AIDetector()
        img = Image.new("RGB", (100, 100), "white")
        result = detector.detect(img)
        assert result == []


# ---------------------------------------------------------------------------
# HybridDetector 测试
# ---------------------------------------------------------------------------


class TestHybridDetector:
    """HybridDetector 融合逻辑测试。"""

    def test_merge_no_overlap(self) -> None:
        """无重叠的 UIA 和 AI 结果全部保留。"""
        hd = HybridDetector()
        uia = [
            UIElement(bbox=(0, 0, 100, 50), type="button", text="A", confidence=1.0, source="uia"),
        ]
        ai = [
            UIElement(bbox=(200, 200, 300, 250), type="button", text="B", confidence=0.9, source="ai"),
        ]
        merged = hd._merge(uia, ai)
        assert len(merged) == 2

    def test_merge_with_overlap_discards_ai(self) -> None:
        """AI 结果与 UIA 高度重叠时被丢弃。"""
        hd = HybridDetector()
        uia = [
            UIElement(bbox=(0, 0, 100, 50), type="button", text="Save", confidence=1.0, source="uia"),
        ]
        ai = [
            # 完全包含在 UIA 元素内
            UIElement(bbox=(5, 5, 95, 45), type="button", text="Save", confidence=0.8, source="ai"),
        ]
        merged = hd._merge(uia, ai)
        assert len(merged) == 1
        assert merged[0].source == "uia"

    def test_merge_ai_only_confidence_reduced(self) -> None:
        """AI 独有的元素置信度被降低。"""
        hd = HybridDetector()
        uia = [
            UIElement(bbox=(0, 0, 100, 50), type="button", text="A", confidence=1.0, source="uia"),
        ]
        ai = [
            UIElement(bbox=(500, 500, 600, 550), type="input", text="B", confidence=1.0, source="ai"),
        ]
        merged = hd._merge(uia, ai)
        assert len(merged) == 2
        ai_elem = [e for e in merged if e.source == "ai"][0]
        assert ai_elem.confidence == pytest.approx(0.7)

    def test_calc_overlap_no_overlap(self) -> None:
        """不重叠的两个 bbox 返回 0。"""
        overlap = HybridDetector._calc_overlap((0, 0, 10, 10), (20, 20, 30, 30))
        assert overlap == 0.0

    def test_calc_overlap_full_overlap(self) -> None:
        """完全重叠返回 1.0。"""
        overlap = HybridDetector._calc_overlap((0, 0, 100, 100), (0, 0, 100, 100))
        assert overlap == 1.0

    def test_calc_overlap_partial(self) -> None:
        """部分重叠返回正确的比例。"""
        overlap = HybridDetector._calc_overlap((0, 0, 100, 100), (50, 50, 150, 150))
        assert 0.0 < overlap < 1.0

    def test_find_by_type_mapping(self) -> None:
        """find() 方法能通过中文关键词匹配类型。"""
        hd = HybridDetector()
        # Mock detect 返回固定元素
        mock_elements = [
            UIElement(bbox=(0, 0, 100, 50), type="EditControl", text="搜索", confidence=1.0, source="uia", clickable=True, actionable=True),
            UIElement(bbox=(100, 0, 200, 50), type="ButtonControl", text="提交", confidence=1.0, source="uia", clickable=True, actionable=True),
            UIElement(bbox=(200, 0, 300, 50), type="TextControl", text="标题", confidence=1.0, source="uia"),
        ]

        with patch.object(hd, "detect", return_value=mock_elements):
            results = hd.find("输入框")
            assert any(e.type == "EditControl" for e in results)

            results = hd.find("按钮")
            assert any(e.type == "ButtonControl" for e in results)

    def test_find_by_text(self) -> None:
        """find() 方法能按文本内容匹配。"""
        hd = HybridDetector()
        mock_elements = [
            UIElement(bbox=(0, 0, 100, 50), type="ButtonControl", text="保存文件", confidence=1.0, source="uia"),
            UIElement(bbox=(100, 0, 200, 50), type="ButtonControl", text="取消", confidence=1.0, source="uia"),
        ]

        with patch.object(hd, "detect", return_value=mock_elements):
            results = hd.find("保存")
            assert len(results) == 1
            assert results[0].text == "保存文件"

    def test_find_in_area(self) -> None:
        """find_in_area 返回指定区域内的元素。"""
        hd = HybridDetector()
        mock_elements = [
            UIElement(bbox=(10, 10, 90, 90), type="button", text="A", confidence=1.0, source="uia"),
            UIElement(bbox=(200, 200, 300, 300), type="button", text="B", confidence=1.0, source="uia"),
        ]

        with patch.object(hd, "detect", return_value=mock_elements):
            results = hd.find_in_area(0, 0, 100, 100)
            assert len(results) == 1
            assert results[0].text == "A"
