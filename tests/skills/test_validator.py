# -*- coding: utf-8 -*-
"""SkillValidator 测试。"""

import pytest
from pathlib import Path
import tempfile
import os

from src.skills.validator import SkillValidator, ValidationResult


@pytest.fixture
def validator():
    return SkillValidator()


def _valid_skill() -> dict:
    """返回一个合法的技能定义。"""
    return {
        "name": "测试技能",
        "description": "用于测试的技能",
        "steps": [
            {"action": "wait", "duration": 1.0},
        ],
    }


class TestValidSkill:
    def test_valid_passes(self, validator):
        result = validator.validate(_valid_skill())
        assert result.valid is True
        assert result.errors == []

    def test_valid_with_optional_fields(self, validator):
        data = _valid_skill()
        data["triggers"] = ["test"]
        data["parameters"] = {"filename": {"type": "string"}}
        result = validator.validate(data)
        assert result.valid is True


class TestMissingFields:
    def test_missing_name(self, validator):
        data = _valid_skill()
        del data["name"]
        result = validator.validate(data)
        assert result.valid is False
        assert any("name" in e for e in result.errors)

    def test_missing_description(self, validator):
        data = _valid_skill()
        del data["description"]
        result = validator.validate(data)
        assert result.valid is False

    def test_missing_steps(self, validator):
        data = _valid_skill()
        del data["steps"]
        result = validator.validate(data)
        assert result.valid is False

    def test_empty_name(self, validator):
        data = _valid_skill()
        data["name"] = ""
        result = validator.validate(data)
        assert result.valid is False


class TestInvalidActions:
    def test_unknown_action(self, validator):
        data = _valid_skill()
        data["steps"] = [{"action": "fly_to_moon"}]
        result = validator.validate(data)
        assert result.valid is False
        assert any("未知 action" in e for e in result.errors)

    def test_missing_action(self, validator):
        data = _valid_skill()
        data["steps"] = [{"duration": 1.0}]
        result = validator.validate(data)
        assert result.valid is False


class TestLoopValidation:
    def test_loop_without_max_iterations(self, validator):
        data = _valid_skill()
        data["steps"] = [{"action": "loop", "steps": []}]
        result = validator.validate(data)
        assert result.valid is False
        assert any("max_iterations" in e for e in result.errors)

    def test_loop_max_iterations_over_100(self, validator):
        data = _valid_skill()
        data["steps"] = [{"action": "loop", "max_iterations": 200, "steps": []}]
        result = validator.validate(data)
        assert result.valid is False

    def test_loop_valid_max_iterations(self, validator):
        data = _valid_skill()
        data["steps"] = [{"action": "loop", "max_iterations": 10, "steps": []}]
        result = validator.validate(data)
        assert result.valid is True


class TestConditionValidation:
    def test_condition_without_when(self, validator):
        data = _valid_skill()
        data["steps"] = [{"action": "condition", "then": []}]
        result = validator.validate(data)
        assert result.valid is False

    def test_condition_with_when(self, validator):
        data = _valid_skill()
        data["steps"] = [{"action": "condition", "when": 'x == "y"', "then": []}]
        result = validator.validate(data)
        assert result.valid is True


class TestRunSkillWarning:
    def test_run_skill_has_warning(self, validator):
        data = _valid_skill()
        data["steps"] = [{"action": "run_skill", "skill_name": "other"}]
        result = validator.validate(data)
        assert result.valid is True
        assert len(result.warnings) > 0
        assert any("run_skill" in w for w in result.warnings)


class TestValidateFile:
    def test_validate_valid_file(self, validator, tmp_path):
        yaml_content = """
name: "文件测试"
description: "测试 validate_file"
steps:
  - action: wait
    duration: 1.0
"""
        f = tmp_path / "test.yaml"
        f.write_text(yaml_content, encoding="utf-8")
        result = validator.validate_file(f)
        assert result.valid is True

    def test_validate_invalid_file(self, validator, tmp_path):
        yaml_content = """
description: "缺少 name"
steps:
  - action: wait
"""
        f = tmp_path / "bad.yaml"
        f.write_text(yaml_content, encoding="utf-8")
        result = validator.validate_file(f)
        assert result.valid is False

    def test_validate_nonexistent_file(self, validator):
        result = validator.validate_file(Path("/nonexistent/skill.yaml"))
        assert result.valid is False

    def test_validate_bad_yaml(self, validator, tmp_path):
        f = tmp_path / "bad.yaml"
        f.write_text("{{invalid yaml}}", encoding="utf-8")
        result = validator.validate_file(f)
        assert result.valid is False
