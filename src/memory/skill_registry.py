"""技能注册表模块。

管理所有已注册的工具/技能，支持动态注册、搜索和持久化。
可从 TOOL_REGISTRY 自动加载已有工具。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from loguru import logger

from src.memory.skill_models import SkillDefinition


class SkillRegistry:
    """技能注册表。

    管理所有已注册的工具/技能元信息，支持：
    - 动态注册/注销技能
    - 按名称、类别、关键词搜索
    - 从 TOOL_REGISTRY 自动加载已有工具
    - JSON 文件持久化

    Usage::

        registry = SkillRegistry(storage_dir="./data/skills")
        await registry.initialize()

        # 注册
        skill_id = await registry.register(
            SkillDefinition.create(name="截图", description="截取屏幕截图", category="tool")
        )

        # 搜索
        results = await registry.search("截图")
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        """初始化技能注册表。

        Args:
            storage_dir: JSON 持久化目录路径。None 则仅内存模式。
        """
        self._skills: dict[str, SkillDefinition] = {}
        self._name_index: dict[str, str] = {}  # name -> skill_id
        self._storage_dir: Path | None = Path(storage_dir) if storage_dir else None
        logger.debug("技能注册表初始化 (dir={})", self._storage_dir or "内存模式")

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """从磁盘加载已有技能数据。"""
        if self._storage_dir is None:
            logger.debug("内存模式，跳过磁盘加载")
            return

        storage_file = self._storage_dir / "registry.json"
        if not storage_file.exists():
            logger.info("技能注册表文件不存在，将创建新文件: {}", storage_file)
            return

        try:
            raw = storage_file.read_text(encoding="utf-8")
            items: list[dict] = json.loads(raw) if raw.strip() else []
            for item in items:
                skill = SkillDefinition.from_dict(item)
                self._skills[skill.id] = skill
                self._name_index[skill.name] = skill.id
            logger.info("从 {} 加载了 {} 个技能", storage_file, len(self._skills))
        except Exception:
            logger.exception("加载技能注册表失败: {}", storage_file)

    async def save(self) -> None:
        """持久化到磁盘。"""
        if self._storage_dir is None:
            logger.debug("内存模式，跳过持久化")
            return

        self._storage_dir.mkdir(parents=True, exist_ok=True)
        storage_file = self._storage_dir / "registry.json"

        items = [s.to_dict() for s in self._skills.values()]
        storage_file.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.debug("技能注册表已保存到 {} ({} 个)", storage_file, len(items))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def register(self, skill_def: SkillDefinition) -> str:
        """注册一个技能。

        如果同名技能已存在，则更新其信息。

        Args:
            skill_def: 技能定义

        Returns:
            技能 ID
        """
        # 检查同名技能
        existing_id = self._name_index.get(skill_def.name)
        if existing_id is not None:
            existing = self._skills[existing_id]
            # 更新已有技能
            existing.description = skill_def.description
            existing.category = skill_def.category
            existing.parameters = skill_def.parameters
            existing.examples = skill_def.examples
            existing.tags = skill_def.tags
            existing.source = skill_def.source
            existing.pattern_steps = skill_def.pattern_steps
            existing.metadata = skill_def.metadata
            existing.updated_at = skill_def.updated_at
            logger.debug("更新技能: {} ({})", skill_def.name, existing_id)
            return existing_id

        self._skills[skill_def.id] = skill_def
        self._name_index[skill_def.name] = skill_def.id
        logger.debug("注册技能: {} ({})", skill_def.name, skill_def.id)
        return skill_def.id

    async def unregister(self, skill_id: str) -> bool:
        """注销一个技能。

        Args:
            skill_id: 技能 ID

        Returns:
            是否成功注销
        """
        skill = self._skills.pop(skill_id, None)
        if skill is None:
            logger.debug("注销技能失败，未找到: {}", skill_id)
            return False

        # 清理名称索引
        if self._name_index.get(skill.name) == skill_id:
            del self._name_index[skill.name]

        logger.debug("注销技能: {} ({})", skill.name, skill_id)
        return True

    async def get(self, skill_id: str) -> SkillDefinition | None:
        """获取指定 ID 的技能。

        Args:
            skill_id: 技能 ID

        Returns:
            技能定义，不存在返回 None
        """
        return self._skills.get(skill_id)

    async def get_by_name(self, name: str) -> SkillDefinition | None:
        """按名称获取技能。

        Args:
            name: 技能名称

        Returns:
            技能定义，不存在返回 None
        """
        skill_id = self._name_index.get(name)
        if skill_id is None:
            return None
        return self._skills.get(skill_id)

    async def list_all(self, category: str | None = None) -> list[SkillDefinition]:
        """列出所有技能。

        Args:
            category: 按类别过滤，None 表示全部

        Returns:
            技能定义列表
        """
        skills = list(self._skills.values())
        if category is not None:
            skills = [s for s in skills if s.category == category]
        return skills

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[SkillDefinition]:
        """搜索技能。

        支持关键词匹配名称、描述和标签，按相关度排序。

        Args:
            query: 搜索关键词
            category: 按类别过滤
            top_k: 返回最多 K 个结果

        Returns:
            按相关度排序的技能列表
        """
        candidates = list(self._skills.values())

        # 按类别过滤
        if category is not None:
            candidates = [s for s in candidates if s.category == category]

        if not query.strip():
            return candidates[:top_k]

        # 计算相关度分数
        scored: list[tuple[SkillDefinition, float]] = []
        query_lower = query.lower()
        query_terms = set(re.findall(r"\w+", query_lower))

        for skill in candidates:
            score = self._compute_relevance(skill, query_lower, query_terms)
            if score > 0:
                scored.append((skill, score))

        # 按分数降序排序
        scored.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in scored[:top_k]]

    def _compute_relevance(
        self,
        skill: SkillDefinition,
        query_lower: str,
        query_terms: set[str],
    ) -> float:
        """计算技能与查询的相关度分数。"""
        score = 0.0

        name_lower = skill.name.lower()
        desc_lower = skill.description.lower()

        # 精确名称匹配
        if query_lower == name_lower:
            score += 10.0
        # 名称包含查询
        elif query_lower in name_lower:
            score += 5.0
        # 查询包含名称
        elif name_lower in query_lower:
            score += 3.0

        # 描述匹配
        if query_lower in desc_lower:
            score += 2.0

        # 标签匹配
        for tag in skill.tags:
            tag_lower = tag.lower()
            if query_lower == tag_lower:
                score += 4.0
            elif query_lower in tag_lower or tag_lower in query_lower:
                score += 1.5

        # 词汇级别匹配（名称和描述）
        name_terms = set(re.findall(r"\w+", name_lower))
        desc_terms = set(re.findall(r"\w+", desc_lower))

        name_overlap = len(query_terms & name_terms)
        desc_overlap = len(query_terms & desc_terms)
        score += name_overlap * 1.0 + desc_overlap * 0.5

        return score

    # ------------------------------------------------------------------
    # 从 TOOL_REGISTRY 加载
    # ------------------------------------------------------------------

    async def load_from_tools(self) -> None:
        """从 TOOL_REGISTRY 自动加载已有工具为技能。

        读取 src.tools.TOOL_REGISTRY 中注册的工具类，提取其元信息。
        """
        try:
            from src.tools import TOOL_REGISTRY
        except ImportError:
            logger.warning("无法导入 TOOL_REGISTRY，跳过工具加载")
            return

        loaded_count = 0
        for tool_name, tool_cls in TOOL_REGISTRY.items():
            # 检查是否已注册
            if tool_name in self._name_index:
                logger.debug("工具 '{}' 已注册，跳过", tool_name)
                continue

            # 从类中提取描述
            description = self._extract_tool_description(tool_cls)

            skill = SkillDefinition.create(
                name=tool_name,
                description=description,
                category="builtin",
                source="tool_registry",
                tags=[tool_name],
            )
            self._skills[skill.id] = skill
            self._name_index[skill.name] = skill.id
            loaded_count += 1
            logger.debug("从 TOOL_REGISTRY 加载工具: {}", tool_name)

        logger.info("从 TOOL_REGISTRY 加载了 {} 个工具", loaded_count)

    def _extract_tool_description(self, tool_cls: type) -> str:
        """从工具类中提取描述信息。"""
        doc = tool_cls.__doc__
        if doc:
            # 取第一行非空文本
            lines = [line.strip() for line in doc.strip().splitlines() if line.strip()]
            if lines:
                return lines[0]
        return f"{tool_cls.__name__} 工具"

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """已注册的技能数量。"""
        return len(self._skills)

    async def list_categories(self) -> list[str]:
        """列出所有技能类别。"""
        return sorted({s.category for s in self._skills.values()})
