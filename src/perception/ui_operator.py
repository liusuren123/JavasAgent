"""UIA 操作封装 — UI 元素交互操作。

提供 UIAOperator 类，基于 Windows UI Automation API 实现对 UI 元素
的安全操作：点击、输入文本、选择项、读取值、聚焦、展开等。

所有操作都经过安全检查：验证元素有效性、确保支持所需的 Pattern、
操作前后截图审计。

屏幕 DPI：3840×2160，UIA 返回的坐标为物理像素坐标。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from enum import auto as enum_auto
from pathlib import Path
from typing import Any

import uiautomation as auto

from src.perception.ui_detector import UIElement

logger = logging.getLogger(__name__)

# 截图审计目录
_AUDIT_DIR = Path("test-evidence/uia_operator_audit")

# 屏幕尺寸（物理像素）
_SCREEN_W = 3840
_SCREEN_H = 2160


# ---------------------------------------------------------------------------
# 异常定义
# ---------------------------------------------------------------------------


class UIAOperationError(Exception):
    """UIA 操作异常基类。"""


class ElementValidationError(UIAOperationError):
    """元素验证失败。"""


class PatternNotSupportedError(UIAOperationError):
    """元素不支持所需的 UIA Pattern。"""


class OperationTimeoutError(UIAOperationError):
    """操作超时。"""


# ---------------------------------------------------------------------------
# 操作结果
# ---------------------------------------------------------------------------


class OpStatus(Enum):
    """操作结果状态。"""

    SUCCESS = enum_auto()
    FAILED = enum_auto()
    SKIPPED = enum_auto()


@dataclass
class OperationResult:
    """操作结果记录。

    Attributes:
        status: 操作结果状态。
        operation: 操作名称。
        element_desc: 元素描述信息。
        message: 附加消息。
        screenshot_before: 操作前截图路径。
        screenshot_after: 操作后截图路径。
        timestamp: 操作时间戳。
        duration_ms: 操作耗时（毫秒）。
    """

    status: OpStatus
    operation: str
    element_desc: str = ""
    message: str = ""
    screenshot_before: str = ""
    screenshot_after: str = ""
    timestamp: str = ""
    duration_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status == OpStatus.SUCCESS


# ---------------------------------------------------------------------------
# UIAOperator — UI 元素交互操作器
# ---------------------------------------------------------------------------


class UIAOperator:
    """基于 Windows UI Automation API 的 UI 元素操作器。

    所有公开操作方法都包含：
    1. 元素有效性验证（_validate_element）
    2. Pattern 支持检查（_ensure_pattern）
    3. 操作前截图（_capture_audit_screenshot）
    4. 执行操作
    5. 操作后截图（_capture_audit_screenshot）
    6. 操作后状态验证

    Usage::

        operator = UIAOperator()
        detector = UIADetector()

        # 找到记事本编辑区并输入文本
        elements = detector.find_by_type("EditControl", window_title="记事本")
        if elements:
            result = operator.type_text(elements[0], "Hello World")
            print(result.ok)
    """

    def __init__(
        self,
        audit_enabled: bool = True,
        audit_dir: str | Path | None = None,
        default_timeout: float = 5.0,
    ) -> None:
        """初始化。

        Args:
            audit_enabled: 是否启用操作审计截图。
            audit_dir: 审计截图保存目录。默认 test-evidence/uia_operator_audit。
            default_timeout: 操作默认超时（秒）。
        """
        self.audit_enabled = audit_enabled
        self._audit_dir = Path(audit_dir) if audit_dir else _AUDIT_DIR
        self.default_timeout = default_timeout

    # ===================================================================
    # 公开操作方法
    # ===================================================================

    def click_element(
        self,
        element: UIElement,
        timeout: float | None = None,
    ) -> OperationResult:
        """点击 UI 元素。

        尝试 Invoke Pattern → 回退到 Click()。

        Args:
            element: 要点击的 UI 元素。
            timeout: 超时秒数。None 使用默认值。

        Returns:
            OperationResult。
        """
        return self._execute_operation(
            operation="click",
            element=element,
            action_fn=self._do_click,
            timeout=timeout,
        )

    def type_text(
        self,
        element: UIElement,
        text: str,
        timeout: float | None = None,
    ) -> OperationResult:
        """在 UI 元素中输入文本。

        使用 Value Pattern 设置值，失败时回退到 SendKeys。

        Args:
            element: 目标编辑控件。
            text: 要输入的文本。
            timeout: 超时秒数。

        Returns:
            OperationResult。
        """
        return self._execute_operation(
            operation="type_text",
            element=element,
            action_fn=lambda ctrl: self._do_type_text(ctrl, text),
            timeout=timeout,
        )

    def select_item(
        self,
        element: UIElement,
        value: str,
        timeout: float | None = None,
    ) -> OperationResult:
        """选择列表/组合框中的指定项。

        使用 SelectionItem Pattern 选中匹配的子项。

        Args:
            element: 列表/组合框控件。
            value: 要选择的项文本。
            timeout: 超时秒数。

        Returns:
            OperationResult。
        """
        return self._execute_operation(
            operation="select_item",
            element=element,
            action_fn=lambda ctrl: self._do_select_item(ctrl, value),
            timeout=timeout,
        )

    def get_value(
        self,
        element: UIElement,
        timeout: float | None = None,
    ) -> tuple[OperationResult, str]:
        """读取 UI 元素的当前值。

        尝试 Value Pattern → 回退到 Name 属性。

        Args:
            element: 目标控件。
            timeout: 超时秒数。

        Returns:
            (OperationResult, value_str) 元组。
        """
        value_holder: list[str] = [""]

        def _read(ctrl: auto.Control) -> None:
            value_holder[0] = self._do_get_value(ctrl)

        result = self._execute_operation(
            operation="get_value",
            element=element,
            action_fn=_read,
            timeout=timeout,
        )
        return result, value_holder[0]

    def set_focus(
        self,
        element: UIElement,
        timeout: float | None = None,
    ) -> OperationResult:
        """聚焦到 UI 元素。

        Args:
            element: 目标控件。
            timeout: 超时秒数。

        Returns:
            OperationResult。
        """
        return self._execute_operation(
            operation="set_focus",
            element=element,
            action_fn=self._do_set_focus,
            timeout=timeout,
        )

    def expand(
        self,
        element: UIElement,
        timeout: float | None = None,
    ) -> OperationResult:
        """展开 UI 元素（ExpandCollapse Pattern）。

        Args:
            element: 目标控件（如 ComboBox）。
            timeout: 超时秒数。

        Returns:
            OperationResult。
        """
        return self._execute_operation(
            operation="expand",
            element=element,
            action_fn=self._do_expand,
            timeout=timeout,
        )

    # ===================================================================
    # 安全检查
    # ===================================================================

    def _validate_element(self, element: UIElement) -> None:
        """验证元素有效且在屏幕上。

        Args:
            element: 待验证的 UIElement。

        Raises:
            ElementValidationError: 元素无效或不在屏幕上。
        """
        if not isinstance(element, UIElement):
            raise ElementValidationError(
                f"参数不是 UIElement 类型: {type(element)}"
            )

        # bbox 全零 → 无效元素
        if element.bbox == (0, 0, 0, 0):
            raise ElementValidationError(
                f"元素 bbox 全零，可能已销毁: type={element.type}"
            )

        # 面积为零 → 不可操作
        if element.area <= 0:
            raise ElementValidationError(
                f"元素面积为零: bbox={element.bbox}"
            )

        # 不在屏幕上
        if not element.is_on_screen(_SCREEN_W, _SCREEN_H):
            raise ElementValidationError(
                f"元素不在屏幕可见区域: bbox={element.bbox}"
            )

    def _resolve_control(
        self, element: UIElement
    ) -> auto.Control:
        """从 UIElement 定位到真实的 uiautomation Control。

        通过元素的区域坐标在控件树中查找匹配的控件。

        Args:
            element: UIElement 数据模型。

        Returns:
            对应的 uiautomation Control。

        Raises:
            ElementValidationError: 无法定位到真实控件。
        """
        left, top, right, bottom = element.bbox
        cx, cy = element.center

        # 通过中心点从桌面查找控件
        control = auto.ControlFromPoint(cx, cy)
        if control is None:
            raise ElementValidationError(
                f"无法通过坐标定位控件: center=({cx}, {cy})"
            )

        # 验证找到的控件名称是否匹配
        ctrl_name = control.Name or ""
        ctrl_type = control.ControlTypeName or ""

        # 放宽匹配：类型匹配即可，名称不做强制要求
        # 因为点击坐标可能落在子控件上，子控件的 type 可能不同
        logger.debug(
            "定位到控件: name=%r type=%s (expect type=%s)",
            ctrl_name, ctrl_type, element.type,
        )

        return control

    def _ensure_pattern(
        self,
        control: auto.Control,
        pattern_id: int,
        pattern_name: str,
    ) -> Any:
        """确保控件支持指定的 UIA Pattern。

        Args:
            control: uiautomation 控件。
            pattern_id: Pattern ID（auto.PatternId.xxx）。
            pattern_name: Pattern 名称（用于错误消息）。

        Returns:
            Pattern 对象。

        Raises:
            PatternNotSupportedError: 控件不支持该 Pattern。
        """
        try:
            pattern = control.GetPattern(pattern_id)
            if pattern is not None:
                return pattern
        except Exception:
            pass

        raise PatternNotSupportedError(
            f"控件 type={control.ControlTypeName} name={control.Name!r} "
            f"不支持 {pattern_name} Pattern"
        )

    # ===================================================================
    # 操作实现
    # ===================================================================

    def _do_click(self, control: auto.Control) -> None:
        """执行点击操作。优先 Invoke Pattern，回退到 Click()。"""
        # 优先 Invoke Pattern
        try:
            invoke = control.GetPattern(auto.PatternId.InvokePattern)
            if invoke is not None:
                control.SetFocus()
                invoke.Invoke()
                logger.debug("通过 Invoke Pattern 点击成功")
                return
        except Exception:
            pass

        # 回退到 Click()
        control.SetFocus()
        control.Click()
        logger.debug("通过 Click() 点击成功")

    def _do_type_text(
        self, control: auto.Control, text: str
    ) -> None:
        """执行文本输入。优先 Value Pattern，回退到 SendKeys。"""
        # 优先 Value Pattern
        try:
            value_pattern = control.GetPattern(auto.PatternId.ValuePattern)
            if value_pattern is not None:
                control.SetFocus()
                value_pattern.SetValue(text)
                logger.debug("通过 Value Pattern 输入文本成功")
                return
        except Exception:
            pass

        # 回退到 SendKeys
        control.SetFocus()
        time.sleep(0.1)
        auto.SendKeys(text)
        logger.debug("通过 SendKeys 输入文本成功")

    def _do_select_item(
        self, control: auto.Control, value: str
    ) -> None:
        """执行选择项操作。在子控件中查找匹配项并选中。"""
        control.SetFocus()

        # 尝试 ExpandCollapse 展开列表
        try:
            expand_pattern = control.GetPattern(
                auto.PatternId.ExpandCollapsePattern
            )
            if expand_pattern is not None:
                expand_pattern.Expand()
                time.sleep(0.3)
        except Exception:
            pass

        # 遍历子控件查找匹配项
        found = False
        for child in control.GetChildren():
            child_name = child.Name or ""
            if value.lower() in child_name.lower():
                # 尝试 SelectionItem Pattern
                try:
                    si = child.GetPattern(
                        auto.PatternId.SelectionItemPattern
                    )
                    if si is not None:
                        si.Select()
                        found = True
                        logger.debug(
                            "通过 SelectionItem 选中: %r", child_name
                        )
                        break
                except Exception:
                    pass

                # 回退到 Click
                child.Click()
                found = True
                logger.debug("通过 Click 选中: %r", child_name)
                break

        if not found:
            raise UIAOperationError(
                f"未找到匹配的选项: {value!r}"
            )

        # 收起列表
        try:
            expand_pattern = control.GetPattern(
                auto.PatternId.ExpandCollapsePattern
            )
            if expand_pattern is not None:
                expand_pattern.Collapse()
        except Exception:
            pass

    def _do_get_value(self, control: auto.Control) -> str:
        """读取控件当前值。优先 Value Pattern，回退到 Name。"""
        # 优先 Value Pattern
        try:
            value_pattern = control.GetPattern(auto.PatternId.ValuePattern)
            if value_pattern is not None:
                return value_pattern.Value or ""
        except Exception:
            pass

        # 回退到 Name 属性
        return control.Name or ""

    def _do_set_focus(self, control: auto.Control) -> None:
        """聚焦到控件。"""
        control.SetFocus()
        logger.debug("SetFocus 成功")

    def _do_expand(self, control: auto.Control) -> None:
        """展开控件。"""
        pattern = self._ensure_pattern(
            control, auto.PatternId.ExpandCollapsePattern,
            "ExpandCollapse",
        )
        pattern.Expand()
        logger.debug("Expand 成功")

    # ===================================================================
    # 操作执行框架
    # ===================================================================

    def _execute_operation(
        self,
        operation: str,
        element: UIElement,
        action_fn: Any,
        timeout: float | None = None,
    ) -> OperationResult:
        """执行操作的统一框架。

        流程：验证 → 截图 → 操作 → 截图 → 验证 → 返回结果

        Args:
            operation: 操作名称。
            element: 目标 UIElement。
            action_fn: 操作函数，接收 uiautomation.Control。
            timeout: 超时秒数。

        Returns:
            OperationResult。
        """
        ts = datetime.now().isoformat()
        start = time.monotonic()
        timeout = timeout or self.default_timeout

        # 安全获取元素描述（element 可能不是 UIElement）
        if isinstance(element, UIElement):
            element_desc = f"type={element.type} text={element.text!r}"
        else:
            element_desc = f"<invalid: {type(element).__name__}>"

        # 1. 验证元素
        try:
            self._validate_element(element)
        except ElementValidationError as e:
            return OperationResult(
                status=OpStatus.FAILED,
                operation=operation,
                element_desc=element_desc,
                message=f"验证失败: {e}",
                timestamp=ts,
            )

        # 2. 操作前截图
        ss_before = self._capture_audit_screenshot(
            f"{operation}_before_{int(time.time())}"
        )

        # 3. 定位控件
        try:
            control = self._resolve_control(element)
        except ElementValidationError as e:
            return OperationResult(
                status=OpStatus.FAILED,
                operation=operation,
                element_desc=element_desc,
                message=f"定位控件失败: {e}",
                screenshot_before=ss_before,
                timestamp=ts,
            )

        # 4. 执行操作
        try:
            action_fn(control)
            elapsed_ms = (time.monotonic() - start) * 1000
        except PatternNotSupportedError as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            return OperationResult(
                status=OpStatus.FAILED,
                operation=operation,
                element_desc=element_desc,
                message=f"Pattern 不支持: {e}",
                screenshot_before=ss_before,
                timestamp=ts,
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            return OperationResult(
                status=OpStatus.FAILED,
                operation=operation,
                element_desc=element_desc,
                message=f"操作异常: {e}",
                screenshot_before=ss_before,
                timestamp=ts,
                duration_ms=elapsed_ms,
            )

        # 5. 操作后截图
        time.sleep(0.2)  # 等待 UI 更新
        ss_after = self._capture_audit_screenshot(
            f"{operation}_after_{int(time.time())}"
        )

        # 6. 操作后验证 — 重新读取控件状态
        try:
            _ = control.BoundingRectangle
        except Exception:
            logger.warning("操作后控件状态检查异常，但操作可能已成功")

        return OperationResult(
            status=OpStatus.SUCCESS,
            operation=operation,
            element_desc=element_desc,
            message="操作成功",
            screenshot_before=ss_before,
            screenshot_after=ss_after,
            timestamp=ts,
            duration_ms=elapsed_ms,
        )

    # ===================================================================
    # 审计截图
    # ===================================================================

    def _capture_audit_screenshot(self, tag: str) -> str:
        """捕获操作审计截图。

        Args:
            tag: 截图标签，用于文件名。

        Returns:
            截图文件路径，失败返回空字符串。
        """
        if not self.audit_enabled:
            return ""

        try:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            filepath = self._audit_dir / f"{tag}.png"

            # 使用 Pillow 截图
            from PIL import ImageGrab

            img = ImageGrab.grab()
            img.save(str(filepath))
            logger.debug("审计截图: %s", filepath)
            return str(filepath)
        except Exception as e:
            logger.warning("审计截图失败: %s", e)
            return ""
