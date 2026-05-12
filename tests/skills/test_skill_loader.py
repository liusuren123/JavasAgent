# -*- coding: utf-8 -*-
"""SkillLoader 测试。"""

import pytest
from pathlib import Path

from src.skills.skill_loader import SkillLoader


@pytest.fixture
def skills_dir(tmp_path):
    """创建临时技能目录和测试文件。"""
    d = tmp_path / "skills"
    d.mkdir()

    # 合法技能
    (d / "good.yaml").write_text("""
name: "测试技能"
description: "一个合法的测试技能"
category: "test"
triggers:
  - "测试"
  - "test"
steps:
  - action: wait
    duration: 1.0
  - action: key_combo
    keys: "ctrl+s"
""", encoding="utf-8")

    # 另一个合法技能（子目录）
    sub = d / "sub"
    sub.mkdir()
    (sub / "nested.yaml").write_text("""
name: "嵌套技能"
description: "子目录中的技能"
steps:
  - action: wait
    duration: 0.5
""", encoding="utf-8")

    # 非法技能（缺少 name）
    (d / "bad.yaml").write_text("""
description: "缺少 name 字段"
steps:
  - action: wait
""", encoding="utf-8")

    return d


class TestLoadAll:
    def test_load_all_scans_directory(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills = loader.load_all()
        names = [s.name for s in skills]
        assert "测试技能" in names
        assert "嵌套技能" in names
        assert len(skills) == 2  # bad.yaml 应被跳过

    def test_load_all_nonexistent_dir(self, tmp_path):
        loader = SkillLoader(skills_dirs=[str(tmp_path / "nonexistent")])
        skills = loader.load_all()
        assert skills == []


class TestLoadFile:
    def test_load_file_parses_yaml(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skill = loader.load_file(skills_dir / "good.yaml")
        assert skill is not None
        assert skill.name == "测试技能"
        assert skill.source == "yaml"
        assert len(skill.steps) == 2
        assert skill.triggers == ["测试", "test"]

    def test_load_file_validation_failure(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skill = loader.load_file(skills_dir / "bad.yaml")
        assert skill is None

    def test_load_file_nonexistent(self, tmp_path):
        loader = SkillLoader(skills_dirs=[str(tmp_path)])
        skill = loader.load_file(tmp_path / "missing.yaml")
        assert skill is None

    def test_load_file_has_yaml_path(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skill = loader.load_file(skills_dir / "good.yaml")
        assert skill is not None
        assert "good.yaml" in skill.yaml_path


class TestReload:
    def test_reload_clears_and_reloads(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills1 = loader.load_all()
        assert len(skills1) == 2

        # reload 应返回相同数量
        skills2 = loader.reload()
        assert len(skills2) == 2


class TestGetSkillPath:
    def test_get_skill_path_found(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        loader.load_all()
        path = loader.get_skill_path("测试技能")
        assert path is not None
        assert "good.yaml" in str(path)

    def test_get_skill_path_not_found(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        loader.load_all()
        path = loader.get_skill_path("不存在的技能")
        assert path is None


class TestSubdirectoryScan:
    def test_recursive_scan(self, skills_dir):
        loader = SkillLoader(skills_dirs=[str(skills_dir)])
        skills = loader.load_all()
        names = [s.name for s in skills]
        assert "嵌套技能" in names  # 子目录中的文件被扫描到


class TestMultipleDirs:
    def test_multiple_dirs(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "a.yaml").write_text("""
name: "技能A"
description: "来自dir1"
steps:
  - action: wait
""", encoding="utf-8")

        (dir2 / "b.yaml").write_text("""
name: "技能B"
description: "来自dir2"
steps:
  - action: wait
""", encoding="utf-8")

        loader = SkillLoader(skills_dirs=[str(dir1), str(dir2)])
        skills = loader.load_all()
        names = [s.name for s in skills]
        assert "技能A" in names
        assert "技能B" in names
