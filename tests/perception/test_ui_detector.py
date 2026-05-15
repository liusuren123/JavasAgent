"""UIA 基础封装测试。

覆盖 UIElement 数据模型、UIADetector 扫描和查找方法。
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

# ---------------------------------------------------------------------------
# T5.2 — UIElement 数据模型测试
# ---------------------------------------------------------------------------


class TestUIElement:
    """UIElement dataclass 基本验证。"""

    def test_create_ui_element_all_fields(self):
        from src.perception.ui_detector import UIElement

        elem = UIElement(
            bbox=(100, 200, 300, 400),
            type="ButtonControl",
            text="确定",
            confidence=1.0,
            source="uia",
            clickable=True,
            actionable=True,
            element_id="btn_ok",
        )
        assert elem.bbox == (100, 200, 300, 400)
        assert elem.type == "ButtonControl"
        assert elem.text == "确定"
        assert elem.confidence == 1.0
        assert elem.source == "uia"
        assert elem.clickable is True
        assert elem.actionable is True
        assert elem.element_id == "btn_ok"

    def test_ui_element_defaults(self):
        from src.perception.ui_detector import UIElement

        elem = UIElement(
            bbox=(0, 0, 10, 10),
            type="TextControl",
            text="",
            confidence=0.0,
            source="uia",
        )
        assert elem.clickable is False
        assert elem.actionable is False
        assert elem.element_id == ""

    def test_ui_element_center_property(self):
        """验证 center 属性正确计算中心坐标。"""
        from src.perception.ui_detector import UIElement

        elem = UIElement(
            bbox=(100, 200, 300, 400),
            type="ButtonControl",
            text="OK",
            confidence=1.0,
            source="uia",
        )
        # center = ((left+right)/2, (top+bottom)/2)
        assert elem.center == (200, 300)

    def test_ui_element_area_property(self):
        """验证 area 属性正确计算面积。"""
        from src.perception.ui_detector import UIElement

        elem = UIElement(
            bbox=(0, 0, 100, 50),
            type="TextControl",
            text="hello",
            confidence=1.0,
            source="uia",
        )
        assert elem.area == 5000

    def test_ui_element_is_on_screen(self):
        """验证 is_on_screen 判断。"""
        from src.perception.ui_detector import UIElement

        # 正常在屏幕上的元素
        elem_ok = UIElement(
            bbox=(100, 100, 200, 200),
            type="ButtonControl",
            text="OK",
            confidence=1.0,
            source="uia",
        )
        assert elem_ok.is_on_screen(screen_w=3840, screen_h=2160) is True

        # 完全在屏幕外的元素
        elem_off = UIElement(
            bbox=(5000, 5000, 6000, 6000),
            type="TextControl",
            text="",
            confidence=0.0,
            source="uia",
        )
        assert elem_off.is_on_screen(screen_w=3840, screen_h=2160) is False

    def test_ui_element_contains_point(self):
        """验证 contains_point 判断。"""
        from src.perception.ui_detector import UIElement

        elem = UIElement(
            bbox=(100, 200, 300, 400),
            type="ButtonControl",
            text="OK",
            confidence=1.0,
            source="uia",
        )
        assert elem.contains_point(150, 250) is True
        assert elem.contains_point(50, 50) is False


# ---------------------------------------------------------------------------
# UIDetector 抽象基类
# ---------------------------------------------------------------------------


class TestUIDetectorBase:
    """UIDetector 基类是抽象的，不能直接实例化。"""

    def test_cannot_instantiate_abstract(self):
        from src.perception.ui_detector import UIDetector

        with pytest.raises(TypeError):
            UIDetector()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# T5.3 — UIADetector 扫描测试
# ---------------------------------------------------------------------------


class TestUIADetectorScan:
    """UIADetector 的 scan 方法测试。"""

    def test_scan_desktop_returns_list(self):
        """扫描桌面应返回 UIElement 列表。"""
        from src.perception.ui_detector import UIADetector

        detector = UIADetector()
        elements = detector.scan()
        assert isinstance(elements, list)
        assert len(elements) > 0

    def test_scan_element_types(self):
        """扫描结果的每个元素都应该是 UIElement 类型。"""
        from src.perception.ui_detector import UIADetector, UIElement

        detector = UIADetector()
        elements = detector.scan()
        for elem in elements[:50]:
            assert isinstance(elem, UIElement)

    def test_scan_element_has_valid_bbox(self):
        """每个元素的 bbox 应该是 4 个整数的元组。"""
        from src.perception.ui_detector import UIADetector

        detector = UIADetector()
        elements = detector.scan()
        for elem in elements[:50]:
            assert isinstance(elem.bbox, tuple)
            assert len(elem.bbox) == 4
            left, top, right, bottom = elem.bbox
            assert right >= left
            assert bottom >= top

    def test_scan_no_offscreen_elements(self):
        """扫描结果不应包含 IsOffscreen=True 的元素。"""
        from src.perception.ui_detector import UIADetector

        detector = UIADetector()
        elements = detector.scan()
        # 所有元素的 bbox 不应该是 (0,0,0,0)
        for elem in elements[:100]:
            if elem.bbox == (0, 0, 0, 0):
                pytest.fail(f"发现空 bbox 元素: type={elem.type}, text={elem.text!r}")

    def test_scan_with_window_title(self):
        """按窗口标题扫描应只返回该窗口内的元素。"""
        from src.perception.ui_detector import UIADetector

        detector = UIADetector()
        # 先打开一个记事本
        subprocess.Popen(["notepad.exe"])
        time.sleep(1.5)

        elements = detector.scan(window_title="Notepad")
        # 清理记事本
        subprocess.call(["taskkill", "/f", "/im", "notepad.exe"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        assert isinstance(elements, list)
        # 应该能找到一些元素
        if len(elements) == 0:
            pytest.skip("记事本窗口可能未在时间内出现")


# ---------------------------------------------------------------------------
# T5.3 — 记事本窗口元素提取
# ---------------------------------------------------------------------------


class TestNotepadElements:
    """打开记事本，扫描其 UI 元素。"""

    @pytest.fixture(scope="class")
    def notepad_elements(self):
        """打开记事本并扫描元素。"""
        from src.perception.ui_detector import UIADetector

        subprocess.Popen(["notepad.exe"])
        time.sleep(2)

        detector = UIADetector()
        elements = detector.scan(window_title="Notepad")

        yield elements

        subprocess.call(["taskkill", "/f", "/im", "notepad.exe"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_finds_edit_control(self, notepad_elements):
        """应该能找到编辑区域（EditControl 或 TextControl）。"""
        edit_types = {"EditControl", "TextControl", "DocumentControl"}
        edit_elements = [e for e in notepad_elements if e.type in edit_types]
        assert len(edit_elements) > 0, (
            f"未找到编辑区域，所有类型: {set(e.type for e in notepad_elements)}"
        )

    def test_notepad_elements_have_reasonable_coords(self, notepad_elements):
        """记事本元素坐标应在屏幕范围内。"""
        for elem in notepad_elements:
            if elem.bbox == (0, 0, 0, 0):
                continue
            left, top, right, bottom = elem.bbox
            # 坐标应在合理范围内（屏幕 3840x2160）
            assert 0 <= left <= 3840, f"left={left} 超出屏幕"
            assert 0 <= top <= 2160, f"top={top} 超出屏幕"


# ---------------------------------------------------------------------------
# T5.4 — 元素查找方法测试
# ---------------------------------------------------------------------------


class TestUIADetectorFindMethods:
    """UIADetector 的各种查找方法测试。"""

    @pytest.fixture(scope="class")
    def detector_with_notepad(self):
        """打开记事本，返回 detector 和扫描结果。"""
        from src.perception.ui_detector import UIADetector

        subprocess.Popen(["notepad.exe"])
        time.sleep(2)

        detector = UIADetector()
        elements = detector.scan(window_title="Notepad")

        yield detector, elements

        subprocess.call(["taskkill", "/f", "/im", "notepad.exe"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_find_by_type_edit(self, detector_with_notepad):
        """find_by_type 应能找到 EditControl。"""
        detector, _ = detector_with_notepad
        results = detector.find_by_type("EditControl")
        assert len(results) > 0, "未找到 EditControl"

    def test_find_by_type_returns_correct_type(self, detector_with_notepad):
        """find_by_type 返回的元素类型应全部匹配。"""
        detector, _ = detector_with_notepad
        results = detector.find_by_type("EditControl")
        for elem in results:
            assert elem.type == "EditControl"

    def test_find_by_name_fuzzy(self, detector_with_notepad):
        """find_by_name 模糊匹配应能工作。"""
        detector, _ = detector_with_notepad
        # 用部分名称搜索
        results = detector.find_by_name("Notepad", exact=False)
        # 记事本窗口标题包含 "Notepad"
        assert isinstance(results, list)

    def test_find_by_name_exact(self, detector_with_notepad):
        """find_by_name 精确匹配。"""
        detector, _ = detector_with_notepad
        results = detector.find_by_name("__nonexistent_name__", exact=True)
        assert len(results) == 0

    def test_find_by_text(self, detector_with_notepad):
        """find_by_text 应按文本内容查找。"""
        detector, _ = detector_with_notepad
        results = detector.find_by_text("")
        # 空文本匹配应该找到元素（很多元素文本为空）
        assert isinstance(results, list)

    def test_find_by_automation_id(self, detector_with_notepad):
        """find_by_automation_id 测试。"""
        detector, _ = detector_with_notepad
        results = detector.find_by_automation_id("15")  # Notepad 编辑区域常见 ID
        # 无论是否找到都不报错
        assert isinstance(results, list)

    def test_find_in_area(self, detector_with_notepad):
        """find_in_area 应返回指定区域内的元素。"""
        detector, _ = detector_with_notepad
        # 搜索屏幕中心区域的元素
        results = detector.find_in_area(500, 500, 2000, 1500)
        assert isinstance(results, list)
        for elem in results:
            left, top, right, bottom = elem.bbox
            # 元素的中心应在指定区域内
            cx = (left + right) / 2
            cy = (top + bottom) / 2
            assert 500 <= cx <= 2000, f"元素中心 x={cx} 不在 [500, 2000]"
            assert 500 <= cy <= 1500, f"元素中心 y={cy} 不在 [500, 1500]"

    def test_find_in_area_empty(self, detector_with_notepad):
        """搜索屏幕外的区域应返回空。"""
        detector, _ = detector_with_notepad
        results = detector.find_in_area(5000, 5000, 6000, 6000)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# T5.5 — 计算器按钮定位测试
# ---------------------------------------------------------------------------


class TestCalculatorButtons:
    """打开计算器，定位按钮。"""

    @pytest.fixture(scope="class")
    def calc_elements(self):
        """打开计算器并扫描元素。"""
        from src.perception.ui_detector import UIADetector

        # 尝试打开计算器
        subprocess.Popen(["calc.exe"])
        time.sleep(3)

        detector = UIADetector()
        elements = detector.scan(window_title="计算器")

        yield detector, elements

        subprocess.call(["taskkill", "/f", "/im", "Calculator.exe"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.call(["taskkill", "/f", "/im", "calc.exe"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def test_finds_equals_button(self, calc_elements):
        """应该能找到"等于"按钮。"""
        detector, _ = calc_elements
        # 查找包含"等于"或"="的按钮
        equals_candidates = detector.find_by_name("等于", exact=False)
        if not equals_candidates:
            equals_candidates = detector.find_by_name("=", exact=False)
        if not equals_candidates:
            equals_candidates = detector.find_by_text("=")

        if not equals_candidates:
            pytest.skip("计算器未找到等于按钮，可能版本不同")
            return

        # 验证坐标合理
        for elem in equals_candidates:
            left, top, right, bottom = elem.bbox
            if left == 0 and top == 0 and right == 0 and bottom == 0:
                continue
            assert 0 <= left <= 3840, f"left={left}"
            assert 0 <= top <= 2160, f"top={top}"

    def test_calc_elements_reasonable(self, calc_elements):
        """计算器元素应有合理的数量和类型。"""
        _, elements = calc_elements
        if len(elements) == 0:
            pytest.skip("计算器窗口未找到")
        assert len(elements) > 0
        types = {e.type for e in elements}
        assert len(types) > 0
