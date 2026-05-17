# -*- coding: utf-8 -*-
"""技能自动录制器 — 录制 Agent 操作并导出为 YAML 技能描述。

功能：
- 监听 Agent 的每次操作（截图、点击、输入、等待）
- 按时间顺序记录为步骤列表
- 自动识别关键帧（操作前后的截图对比）
- 录制结果自动转换为 YAML 技能描述
- 泛化坐标为语义描述（"点击'保存'按钮"而非"点击(300,200)"）
- 自动提取 OCR 文本作为步骤描述
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml
from loguru import logger


# ======================================================================
# T12.1：操作记录数据模型
# ======================================================================


@dataclass
class ActionRecord:
    """单次操作的录制记录。

    Attributes:
        action: 操作类型（click / type_text / screenshot / wait / key_combo 等）
        timestamp: 操作时间戳（time.time()）
        params: 操作参数字典
        screenshot_before: 操作前截图（bytes 或 None）
        screenshot_after: 操作后截图（bytes 或 None）
        ocr_text_before: 操作前 OCR 文本
        ocr_text_after: 操作后 OCR 文本
    """

    action: str
    timestamp: float
    params: dict[str, Any] = field(default_factory=dict)
    screenshot_before: Optional[bytes] = None
    screenshot_after: Optional[bytes] = None
    ocr_text_before: str = ""
    ocr_text_after: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典（截图转为长度标记）。"""
        return {
            "action": self.action,
            "timestamp": self.timestamp,
            "params": self.params,
            "has_screenshot_before": self.screenshot_before is not None,
            "has_screenshot_after": self.screenshot_after is not None,
            "ocr_text_before": self.ocr_text_before,
            "ocr_text_after": self.ocr_text_after,
        }


# ======================================================================
# T12.1：关键帧检测器
# ======================================================================

# 始终标记为关键帧的操作类型（改变系统状态的操作）
_KEY_FRAME_ACTIONS = frozenset({
    "click", "double_click", "right_click",
    "click_text", "click_icon",
    "type_text", "key_combo", "key_type",
    "screenshot",
})


class KeyFrameDetector:
    """关键帧检测器 — 识别操作前后的截图变化。

    判断规则：
    1. 点击、输入、截图等操作默认为关键帧
    2. wait / move_mouse 等操作默认不是，但截图差异大时标记为关键帧
    3. 截图差异通过简单字节比较判断
    """

    def is_key_frame(self, record: ActionRecord) -> bool:
        """判断单个操作是否为关键帧。

        Args:
            record: 操作记录。

        Returns:
            是否为关键帧。
        """
        # 规则 1：特定操作类型始终为关键帧
        if record.action in _KEY_FRAME_ACTIONS:
            return True

        # 规则 2：有截图差异的操作
        if record.screenshot_before and record.screenshot_after:
            if self._screenshots_differ(record.screenshot_before, record.screenshot_after):
                return True

        return False

    def detect_key_frames(self, records: list[ActionRecord]) -> list[ActionRecord]:
        """从操作列表中提取关键帧。

        Args:
            records: 操作记录列表。

        Returns:
            关键帧列表。
        """
        return [r for r in records if self.is_key_frame(r)]

    @staticmethod
    def _screenshots_differ(before: bytes, after: bytes, threshold: float = 0.05) -> bool:
        """比较两幅截图是否有显著差异。

        使用简单的字节差异比例判断。

        Args:
            before: 操作前截图。
            after: 操作后截图。
            threshold: 差异比例阈值（0-1）。

        Returns:
            是否有显著差异。
        """
        if before == after:
            return False

        # 长度不同 → 肯定有差异
        if len(before) != len(after):
            return True

        if not before:
            return False

        # 采样比较（每 100 字节取一个样本点，加速比较）
        sample_count = min(len(before) // 100, 50)
        if sample_count == 0:
            return before != after

        step = len(before) // sample_count
        diff_count = 0
        for i in range(0, len(before), step):
            if i < len(before) and i < len(after) and before[i] != after[i]:
                diff_count += 1

        ratio = diff_count / sample_count
        return ratio > threshold


# ======================================================================
# T12.1：录制器
# ======================================================================


class Recorder:
    """操作录制器 — 监听并记录 Agent 的每次操作。

    使用方式：
    1. recorder.start_recording(skill_name="xxx")
    2. recorder.record_action("click", {"x": 100, "y": 200})
    3. recorder.stop_recording() → 返回操作列表
    """

    def __init__(self) -> None:
        self._recording = False
        self._records: list[ActionRecord] = []
        self._start_time: float = 0.0
        self.skill_name: str = ""
        self._perception: Any = None
        self._key_frame_detector = KeyFrameDetector()

    def set_perception(self, perception: Any) -> None:
        """设置感知模块（用于 OCR）。"""
        self._perception = perception

    def is_recording(self) -> bool:
        """是否正在录制。"""
        return self._recording

    def start_recording(self, skill_name: str = "") -> None:
        """开始录制。

        Args:
            skill_name: 技能名称。
        """
        self._recording = True
        self._start_time = time.time()
        self.skill_name = skill_name
        self._records = []
        logger.info("开始录制: skill_name={}", skill_name)

    def stop_recording(self) -> list[ActionRecord]:
        """停止录制并返回操作列表。

        Returns:
            录制的操作记录列表。
        """
        self._recording = False
        logger.info("停止录制: {} 条记录", len(self._records))
        return list(self._records)

    def record_action(
        self,
        action: str,
        params: dict[str, Any],
        screenshot_before: Optional[bytes] = None,
        screenshot_after: Optional[bytes] = None,
        ocr_text_before: str = "",
        ocr_text_after: str = "",
    ) -> None:
        """记录一次操作。

        Args:
            action: 操作类型。
            params: 操作参数。
            screenshot_before: 操作前截图。
            screenshot_after: 操作后截图。
            ocr_text_before: 操作前 OCR 文本。
            ocr_text_after: 操作后 OCR 文本。
        """
        if not self._recording:
            return

        record = ActionRecord(
            action=action,
            timestamp=time.time(),
            params=dict(params),
            screenshot_before=screenshot_before,
            screenshot_after=screenshot_after,
            ocr_text_before=ocr_text_before,
            ocr_text_after=ocr_text_after,
        )
        self._records.append(record)
        logger.debug("录制操作: {} params={}", action, params)

    def get_records(self) -> list[ActionRecord]:
        """获取当前录制列表。"""
        return list(self._records)

    def get_key_frames(self) -> list[ActionRecord]:
        """获取关键帧列表。"""
        return self._key_frame_detector.detect_key_frames(self._records)

    def clear(self) -> None:
        """清除所有录制记录。"""
        self._records = []


# ======================================================================
# T12.2：技能导出器
# ======================================================================


class SkillExporter:
    """技能导出器 — 将录制记录转换为 YAML 技能描述。

    功能：
    - 泛化坐标为语义描述（"点击'保存'按钮"而非"点击(300,200)"）
    - 自动提取 OCR 文本作为步骤描述
    - 生成标准 YAML 技能格式
    """

    # YAML 技能格式版本
    VERSION = "1.0"

    def export_to_yaml(
        self,
        records: list[ActionRecord],
        skill_name: str,
        description: str = "",
    ) -> str:
        """将录制记录导出为 YAML 技能描述。

        Args:
            records: 操作记录列表。
            skill_name: 技能名称。
            description: 技能描述。

        Returns:
            YAML 格式字符串。
        """
        steps = [self._record_to_step(r) for r in records]

        skill_doc = {
            "version": self.VERSION,
            "name": skill_name,
            "description": description,
            "steps": steps,
        }

        return yaml.dump(
            skill_doc,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )

    def _record_to_step(self, record: ActionRecord) -> dict[str, Any]:
        """将单条操作记录转换为 YAML 步骤。

        根据 action 类型和 OCR 信息决定步骤格式：
        - click + OCR → click_text（泛化为语义描述）
        - click 无 OCR → click（保留坐标）
        - 其他操作 → 保留原始参数

        Args:
            record: 操作记录。

        Returns:
            步骤字典。
        """
        action = record.action
        params = dict(record.params)

        step: dict[str, Any] = {"action": action}

        if action == "click" and record.ocr_text_before:
            # 尝试泛化为 click_text
            semantic = self._generalize_click(record)
            if semantic:
                return semantic

        # 添加操作参数
        step.update(params)

        # 添加语义描述
        desc = self._generate_description(record)
        if desc:
            step["description"] = desc

        return step

    def _generalize_click(self, record: ActionRecord) -> Optional[dict[str, Any]]:
        """将 click 操作泛化为 click_text。

        通过 OCR 文本找到最近的文字目标。

        Args:
            record: click 操作记录。

        Returns:
            泛化后的步骤字典，无法泛化时返回 None。
        """
        if not record.ocr_text_before:
            return None

        # 从 OCR 文本中提取候选文字
        candidates = self._extract_ocr_candidates(record.ocr_text_before)
        if not candidates:
            return None

        x = record.params.get("x", 0)
        y = record.params.get("y", 0)

        # 找到最短的候选文字作为目标（通常最精确）
        best = min(candidates, key=len)
        if len(best) < 1:
            return None

        step = {
            "action": "click_text",
            "text": best,
            "description": f"点击'{best}'按钮" if len(best) <= 4 else f"点击'{best}'",
        }

        return step

    @staticmethod
    def _extract_ocr_candidates(ocr_text: str) -> list[str]:
        """从 OCR 文本中提取候选点击目标。

        Args:
            ocr_text: OCR 识别出的屏幕文字。

        Returns:
            候选文字列表。
        """
        # 按空格/换行分割，过滤空串
        parts = [p.strip() for p in ocr_text.replace("\n", " ").split(" ") if p.strip()]
        return parts

    def _generate_description(self, record: ActionRecord) -> str:
        """为操作生成语义描述。

        Args:
            record: 操作记录。

        Returns:
            描述字符串。
        """
        action = record.action
        params = record.params

        if action == "click":
            x, y = params.get("x", 0), params.get("y", 0)
            if record.ocr_text_before:
                candidates = self._extract_ocr_candidates(record.ocr_text_before)
                nearby = "、".join(candidates[:3])
                return f"点击坐标({x},{y})，附近文字：{nearby}"
            return f"点击坐标({x},{y})"

        if action == "double_click":
            x, y = params.get("x", 0), params.get("y", 0)
            return f"双击坐标({x},{y})"

        if action == "right_click":
            x, y = params.get("x", 0), params.get("y", 0)
            return f"右键点击坐标({x},{y})"

        if action == "type_text":
            text = params.get("text", "")
            speed = params.get("speed", "normal")
            return f"输入文字'{text[:20]}'(速度:{speed})"

        if action == "key_combo":
            keys = params.get("keys", "")
            return f"按下组合键 {keys}"

        if action == "key_type":
            keys = params.get("keys", "")
            return f"按下按键 {keys}"

        if action == "wait":
            duration = params.get("duration", 1.0)
            return f"等待{duration}秒"

        if action == "screenshot":
            return "截取屏幕"

        if action == "drag":
            return f"拖拽({params.get('start_x',0)},{params.get('start_y',0)})→({params.get('end_x',0)},{params.get('end_y',0)})"

        if action == "scroll":
            amount = params.get("amount", 3)
            direction = "向上" if amount > 0 else "向下"
            return f"滚轮{direction}滚动"

        return f"执行{action}"
