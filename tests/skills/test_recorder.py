# -*- coding: utf-8 -*-
"""技能自动录制器 (recorder) 测试。

覆盖：
- T12.1：操作录制、关键帧识别、步骤列表生成
- T12.2：YAML 技能描述转换、坐标泛化、OCR 文本提取
"""

import time
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from src.skills.recorder import (
    ActionRecord,
    KeyFrameDetector,
    Recorder,
    SkillExporter,
)


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def recorder():
    """创建录制器实例。"""
    return Recorder()


@pytest.fixture
def recorder_with_ocr():
    """创建带 OCR mock 的录制器。"""
    rec = Recorder()
    mock_perception = MagicMock()
    mock_perception.get_screen_text = AsyncMock(return_value="文件 编辑 查看")
    mock_perception.find_text = AsyncMock(return_value=(300, 200))
    rec.set_perception(mock_perception)
    return rec


@pytest.fixture
def exporter():
    """创建技能导出器。"""
    return SkillExporter()


# ======================================================================
# T12.1：ActionRecord 数据模型
# ======================================================================


class TestActionRecord:
    def test_create_action_record(self):
        """测试创建操作记录。"""
        record = ActionRecord(
            action="click",
            timestamp=time.time(),
            params={"x": 300, "y": 200},
        )
        assert record.action == "click"
        assert record.params["x"] == 300
        assert record.params["y"] == 200

    def test_action_record_with_screenshot(self):
        """测试带截图的操作记录。"""
        record = ActionRecord(
            action="click",
            timestamp=time.time(),
            params={"x": 100, "y": 50},
            screenshot_before=b"\x89PNG",
            screenshot_after=b"\x89PNG_DATA",
        )
        assert record.screenshot_before is not None
        assert record.screenshot_after is not None

    def test_action_record_to_dict(self):
        """测试序列化为字典。"""
        record = ActionRecord(
            action="type_text",
            timestamp=1700000000.0,
            params={"text": "hello", "speed": "fast"},
        )
        d = record.to_dict()
        assert d["action"] == "type_text"
        assert d["params"]["text"] == "hello"
        assert "timestamp" in d

    def test_action_record_with_ocr_text(self):
        """测试带 OCR 文本的操作记录。"""
        record = ActionRecord(
            action="click",
            timestamp=time.time(),
            params={"x": 300, "y": 200},
            ocr_text_before="保存 取消",
            ocr_text_after="保存 取消",
        )
        assert record.ocr_text_before == "保存 取消"


# ======================================================================
# T12.1：Recorder 录制操作
# ======================================================================


class TestRecorderBasic:
    def test_recorder_initial_state(self, recorder):
        """录制器初始状态。"""
        assert recorder.is_recording() is False
        assert len(recorder.get_records()) == 0

    def test_start_recording(self, recorder):
        """开始录制。"""
        recorder.start_recording(skill_name="test_skill")
        assert recorder.is_recording() is True
        assert recorder.skill_name == "test_skill"

    def test_stop_recording(self, recorder):
        """停止录制。"""
        recorder.start_recording()
        recorder.stop_recording()
        assert recorder.is_recording() is False

    def test_record_action(self, recorder):
        """记录单个操作。"""
        recorder.start_recording()
        recorder.record_action("click", {"x": 100, "y": 200})
        records = recorder.get_records()
        assert len(records) == 1
        assert records[0].action == "click"
        assert records[0].params["x"] == 100

    def test_record_multiple_actions_in_order(self, recorder):
        """按时间顺序记录多个操作。"""
        recorder.start_recording()

        recorder.record_action("screenshot", {})
        recorder.record_action("click", {"x": 100, "y": 200})
        recorder.record_action("type_text", {"text": "hello"})
        recorder.record_action("wait", {"duration": 1.0})
        recorder.record_action("key_combo", {"keys": "enter"})

        records = recorder.get_records()
        assert len(records) == 5
        # 验证顺序
        assert records[0].action == "screenshot"
        assert records[1].action == "click"
        assert records[2].action == "type_text"
        assert records[3].action == "wait"
        assert records[4].action == "key_combo"
        # 验证时间递增
        for i in range(1, len(records)):
            assert records[i].timestamp >= records[i - 1].timestamp

    def test_record_ignores_when_not_recording(self, recorder):
        """未录制时忽略操作。"""
        recorder.record_action("click", {"x": 0, "y": 0})
        assert len(recorder.get_records()) == 0

    def test_clear_records(self, recorder):
        """清除录制记录。"""
        recorder.start_recording()
        recorder.record_action("click", {"x": 100, "y": 200})
        recorder.stop_recording()
        recorder.clear()
        assert len(recorder.get_records()) == 0


# ======================================================================
# T12.1：关键帧识别
# ======================================================================


class TestKeyFrameDetector:
    def test_detect_key_frame_on_click(self):
        """点击操作标记为关键帧。"""
        detector = KeyFrameDetector()
        record = ActionRecord(
            action="click",
            timestamp=time.time(),
            params={"x": 300, "y": 200},
            screenshot_before=b"before_data",
            screenshot_after=b"after_data_different",
        )
        assert detector.is_key_frame(record) is True

    def test_detect_key_frame_on_type_text(self):
        """文字输入标记为关键帧。"""
        detector = KeyFrameDetector()
        record = ActionRecord(
            action="type_text",
            timestamp=time.time(),
            params={"text": "hello world"},
        )
        assert detector.is_key_frame(record) is True

    def test_wait_not_key_frame(self):
        """等待操作不是关键帧。"""
        detector = KeyFrameDetector()
        record = ActionRecord(
            action="wait",
            timestamp=time.time(),
            params={"duration": 1.0},
        )
        assert detector.is_key_frame(record) is False

    def test_screenshot_diff_triggers_key_frame(self):
        """截图差异大时标记关键帧。"""
        detector = KeyFrameDetector()
        record = ActionRecord(
            action="move_mouse",
            timestamp=time.time(),
            params={"x": 500, "y": 300},
            screenshot_before=b"x" * 1000,
            screenshot_after=b"y" * 1000,
        )
        assert detector.is_key_frame(record) is True

    def test_screenshot_similar_not_key_frame(self):
        """截图相似时不是关键帧。"""
        detector = KeyFrameDetector()
        same_data = b"x" * 1000
        record = ActionRecord(
            action="move_mouse",
            timestamp=time.time(),
            params={"x": 500, "y": 300},
            screenshot_before=same_data,
            screenshot_after=same_data,
        )
        assert detector.is_key_frame(record) is False

    def test_detect_key_frames_from_records(self):
        """从操作列表中提取关键帧。"""
        detector = KeyFrameDetector()
        records = [
            ActionRecord(action="screenshot", timestamp=1.0, params={},
                         screenshot_before=b"aaa", screenshot_after=b"bbb"),
            ActionRecord(action="wait", timestamp=2.0, params={"duration": 1.0}),
            ActionRecord(action="click", timestamp=3.0, params={"x": 100, "y": 200},
                         screenshot_before=b"aaa", screenshot_after=b"ccc"),
            ActionRecord(action="move_mouse", timestamp=4.0, params={"x": 200, "y": 300},
                         screenshot_before=b"ccc", screenshot_after=b"ccc"),
        ]
        key_frames = detector.detect_key_frames(records)
        assert len(key_frames) == 2  # screenshot 和 click
        assert key_frames[0].action == "screenshot"
        assert key_frames[1].action == "click"


# ======================================================================
# T12.2：YAML 技能描述转换
# ======================================================================


class TestSkillExporterBasic:
    def test_export_to_yaml_structure(self, exporter):
        """导出的 YAML 包含完整结构。"""
        records = [
            ActionRecord(action="screenshot", timestamp=1.0, params={}),
            ActionRecord(action="click", timestamp=2.0, params={"x": 300, "y": 200},
                         ocr_text_before="保存 取消"),
            ActionRecord(action="type_text", timestamp=3.0,
                         params={"text": "hello", "speed": "fast"}),
            ActionRecord(action="key_combo", timestamp=4.0, params={"keys": "ctrl+s"}),
            ActionRecord(action="wait", timestamp=5.0, params={"duration": 1.0}),
        ]

        result = exporter.export_to_yaml(
            records=records,
            skill_name="save_file",
            description="保存文件技能",
        )
        parsed = yaml.safe_load(result)

        assert parsed["name"] == "save_file"
        assert parsed["description"] == "保存文件技能"
        assert "steps" in parsed
        assert len(parsed["steps"]) == 5

    def test_export_step_actions(self, exporter):
        """导出的步骤包含正确的 action。"""
        records = [
            ActionRecord(action="click", timestamp=1.0, params={"x": 300, "y": 200}),
            ActionRecord(action="type_text", timestamp=2.0, params={"text": "hello"}),
        ]
        result = exporter.export_to_yaml(records, skill_name="test")
        parsed = yaml.safe_load(result)

        assert parsed["steps"][0]["action"] == "click"
        assert parsed["steps"][1]["action"] == "type_text"


# ======================================================================
# T12.2：坐标泛化为语义描述
# ======================================================================


class TestCoordinateGeneralization:
    def test_generalize_with_ocr_text(self, exporter):
        """有 OCR 文本时泛化为语义描述。"""
        records = [
            ActionRecord(
                action="click",
                timestamp=1.0,
                params={"x": 300, "y": 200},
                ocr_text_before="保存 取消 关闭",
            ),
        ]
        result = exporter.export_to_yaml(records, skill_name="test")
        parsed = yaml.safe_load(result)

        step = parsed["steps"][0]
        # 应该有语义描述，而非纯坐标
        assert "description" in step
        assert "保存" in step["description"] or "取消" in step["description"] or "关闭" in step["description"]

    def test_generalize_click_text(self, exporter):
        """click_text 类型应使用 OCR 文字而非坐标。"""
        records = [
            ActionRecord(
                action="click",
                timestamp=1.0,
                params={"x": 300, "y": 200},
                ocr_text_before="保存 取消",
            ),
        ]
        result = exporter.export_to_yaml(records, skill_name="test")
        parsed = yaml.safe_load(result)

        step = parsed["steps"][0]
        # 应转换为 click_text 或包含语义信息
        assert step["action"] in ("click", "click_text")
        if step["action"] == "click_text":
            assert "text" in step
            # 文本应该是附近 OCR 结果中的文字
            assert step["text"] in ("保存", "取消")

    def test_generalize_without_ocr_keeps_coordinates(self, exporter):
        """无 OCR 文本时保留坐标。"""
        records = [
            ActionRecord(
                action="click",
                timestamp=1.0,
                params={"x": 300, "y": 200},
            ),
        ]
        result = exporter.export_to_yaml(records, skill_name="test")
        parsed = yaml.safe_load(result)

        step = parsed["steps"][0]
        assert step["action"] == "click"
        assert step["x"] == 300
        assert step["y"] == 200


# ======================================================================
# T12.2：OCR 文本自动提取为步骤描述
# ======================================================================


class TestOCRDescription:
    def test_type_text_preserves_text(self, exporter):
        """type_text 操作保留原始文字。"""
        records = [
            ActionRecord(
                action="type_text",
                timestamp=1.0,
                params={"text": "Hello World", "speed": "normal"},
            ),
        ]
        result = exporter.export_to_yaml(records, skill_name="test")
        parsed = yaml.safe_load(result)

        step = parsed["steps"][0]
        assert step["action"] == "type_text"
        assert step["text"] == "Hello World"

    def test_key_combo_description(self, exporter):
        """key_combo 保留组合键信息。"""
        records = [
            ActionRecord(
                action="key_combo",
                timestamp=1.0,
                params={"keys": "ctrl+s"},
            ),
        ]
        result = exporter.export_to_yaml(records, skill_name="test")
        parsed = yaml.safe_load(result)

        step = parsed["steps"][0]
        assert step["action"] == "key_combo"
        assert step["keys"] == "ctrl+s"
        assert "description" in step

    def test_wait_preserves_duration(self, exporter):
        """wait 操作保留时长。"""
        records = [
            ActionRecord(
                action="wait",
                timestamp=1.0,
                params={"duration": 2.5},
            ),
        ]
        result = exporter.export_to_yaml(records, skill_name="test")
        parsed = yaml.safe_load(result)

        step = parsed["steps"][0]
        assert step["action"] == "wait"
        assert step["duration"] == 2.5


# ======================================================================
# T12.2：完整导出流程
# ======================================================================


class TestFullExportFlow:
    def test_full_recording_and_export(self, recorder, exporter):
        """完整录制 → 导出流程。"""
        # 录制
        recorder.start_recording(skill_name="open_notepad")
        recorder.record_action("screenshot", {})
        recorder.record_action("click", {"x": 50, "y": 800},
                               ocr_text_before="开始")
        recorder.record_action("wait", {"duration": 0.5})
        recorder.record_action("type_text", {"text": "notepad", "speed": "fast"})
        recorder.record_action("key_combo", {"keys": "enter"})
        records = recorder.stop_recording()

        # 导出
        yaml_str = exporter.export_to_yaml(
            records=records,
            skill_name="open_notepad",
            description="打开记事本",
        )
        parsed = yaml.safe_load(yaml_str)

        assert parsed["name"] == "open_notepad"
        assert parsed["description"] == "打开记事本"
        assert len(parsed["steps"]) == 5

    def test_export_empty_records(self, exporter):
        """空录制列表导出有效 YAML。"""
        yaml_str = exporter.export_to_yaml([], skill_name="empty")
        parsed = yaml.safe_load(yaml_str)
        assert parsed["name"] == "empty"
        assert parsed["steps"] == []

    def test_exported_yaml_is_valid(self, exporter):
        """导出的 YAML 语法有效。"""
        records = [
            ActionRecord(action="click", timestamp=1.0, params={"x": 100, "y": 200},
                         ocr_text_before="确定"),
            ActionRecord(action="type_text", timestamp=2.0, params={"text": "测试中文"}),
        ]
        yaml_str = exporter.export_to_yaml(records, skill_name="i18n_test")
        # 确保能被 yaml.safe_load 正常解析
        parsed = yaml.safe_load(yaml_str)
        assert parsed is not None

    def test_exported_yaml_has_version(self, exporter):
        """导出 YAML 包含版本号。"""
        yaml_str = exporter.export_to_yaml([], skill_name="test")
        parsed = yaml.safe_load(yaml_str)
        assert "version" in parsed
