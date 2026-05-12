# -*- coding: utf-8 -*-
"""YAML 技能文件加载器。

扫描 skills/ 目录，加载 .yaml 技能文件，转换为 SkillDefinition。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from src.memory.skill_models import SkillDefinition
from src.skills.validator import SkillValidator


class SkillLoader:
    """YAML 技能文件加载器。

    扫描指定目录的 .yaml 文件，验证后转换为 SkillDefinition。
    """

    def __init__(self, skills_dirs: list[str] | None = None) -> None:
        if skills_dirs is None:
            skills_dirs = ["./skills", "./data/skills"]
        self._dirs = [Path(d) for d in skills_dirs]
        self._validator = SkillValidator()
        self._cache: dict[str, SkillDefinition] = {}

    def load_all(self) -> list[SkillDefinition]:
        """扫描所有目录的 .yaml 文件并加载。

        Returns:
            加载成功的技能定义列表。
        """
        skills: list[SkillDefinition] = []
        seen_names: set[str] = set()

        for dir_path in self._dirs:
            if not dir_path.exists():
                logger.debug("技能目录不存在: {}", dir_path)
                continue

            for yaml_file in sorted(dir_path.rglob("*.yaml")):
                skill = self.load_file(yaml_file)
                if skill and skill.name not in seen_names:
                    skills.append(skill)
                    seen_names.add(skill.name)
                    self._cache[skill.name] = skill
                    logger.info("加载技能: {} ({})", skill.name, yaml_file)

        logger.info("共加载 {} 个 YAML 技能", len(skills))
        return skills

    def load_file(self, path: Path) -> SkillDefinition | None:
        """加载单个 YAML 文件。

        Args:
            path: YAML 文件路径。

        Returns:
            SkillDefinition 或 None（验证失败时）。
        """
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except Exception as e:
            logger.warning("YAML 加载失败 {}: {}", path, e)
            return None

        if not isinstance(data, dict):
            logger.warning("YAML 顶层不是字典: {}", path)
            return None

        # 验证
        result = self._validator.validate(data)
        if not result.valid:
            logger.warning("技能验证失败 {}: {}", path, "; ".join(result.errors))
            return None

        if result.warnings:
            for w in result.warnings:
                logger.debug("技能警告 {} - {}", path.name, w)

        # 转换为 SkillDefinition
        try:
            skill = SkillDefinition.create(
                name=data["name"],
                description=data["description"],
                category=data.get("category", "yaml"),
                parameters=data.get("parameters", {}),
                tags=data.get("triggers", []),
                source="yaml",
            )
            skill.yaml_path = str(path)
            skill.skill_version = data.get("version", "1.0")
            skill.triggers = data.get("triggers", [])
            skill.requirements = data.get("requirements", [])
            skill.steps = data.get("steps", [])
            skill.metadata = {
                "author": data.get("author", ""),
                "category": data.get("category", ""),
            }
            return skill
        except Exception as e:
            logger.warning("技能转换失败 {}: {}", path, e)
            return None

    def reload(self) -> list[SkillDefinition]:
        """清空缓存后重新加载所有技能。

        Returns:
            重新加载后的技能列表。
        """
        self._cache.clear()
        return self.load_all()

    def get_skill_path(self, skill_name: str) -> Path | None:
        """根据技能名称找到对应的文件路径。

        Args:
            skill_name: 技能名称。

        Returns:
            文件路径或 None。
        """
        if skill_name in self._cache:
            path = self._cache[skill_name].yaml_path
            if path:
                return Path(path)
        return None
