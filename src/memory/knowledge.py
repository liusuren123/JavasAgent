"""知识库模块。

存储和管理规则、偏好、项目知识、技能注册表等结构化信息。
支持 JSON 持久化和分类检索。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

# 合法的分类枚举
VALID_CATEGORIES = {"rule", "preference", "project", "skill"}


@dataclass
class KnowledgeEntry:
    """一条知识条目。"""

    id: str
    title: str
    content: str
    category: str  # "rule" | "preference" | "project" | "skill"
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # ------------------------------------------------------------------
    # 序列化辅助
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化的字典。"""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["updated_at"] = self.updated_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeEntry:
        """从字典还原 KnowledgeEntry。"""
        data = dict(data)  # shallow copy
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("updated_at"), str):
            data["updated_at"] = datetime.fromisoformat(data["updated_at"])
        return cls(**data)


class KnowledgeBase:
    """知识库，提供 CRUD、分类检索和 JSON 持久化。"""

    def __init__(self, storage_path: str | Path | None = None) -> None:
        """初始化知识库。

        Args:
            storage_path: JSON 存储路径。None 则仅内存模式。
        """
        self._entries: dict[str, KnowledgeEntry] = {}
        self._storage_path: Path | None = Path(storage_path) if storage_path else None
        logger.debug(
            "知识库初始化 (path={})",
            self._storage_path or "内存模式",
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """从磁盘加载已有知识库数据。"""
        if self._storage_path is None:
            logger.debug("内存模式，跳过磁盘加载")
            return

        path = self._storage_path
        if not path.exists():
            logger.info("知识库文件不存在，将创建新文件: {}", path)
            return

        try:
            raw = path.read_text(encoding="utf-8")
            items: list[dict] = json.loads(raw) if raw.strip() else []
            for item in items:
                entry = KnowledgeEntry.from_dict(item)
                self._entries[entry.id] = entry
            logger.info("从 {} 加载了 {} 条知识", path, len(self._entries))
        except Exception:
            logger.exception("加载知识库失败: {}", path)

    async def save(self) -> None:
        """持久化到磁盘。"""
        if self._storage_path is None:
            logger.debug("内存模式，跳过持久化")
            return

        path = self._storage_path
        path.parent.mkdir(parents=True, exist_ok=True)

        items = [e.to_dict() for e in self._entries.values()]
        path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.debug("知识库已保存到 {} ({} 条)", path, len(items))

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def add(
        self,
        title: str,
        content: str,
        category: str,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> str:
        """添加知识条目，返回条目 ID。"""
        if category not in VALID_CATEGORIES:
            raise ValueError(f"无效分类 '{category}'，合法值: {VALID_CATEGORIES}")

        entry_id = uuid.uuid4().hex[:12]
        now = datetime.now()
        entry = KnowledgeEntry(
            id=entry_id,
            title=title,
            content=content,
            category=category,
            tags=tags or [],
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._entries[entry_id] = entry
        logger.debug("添加知识条目 [{}] {}: {}", category, entry_id, title)
        return entry_id

    async def get(self, entry_id: str) -> KnowledgeEntry | None:
        """获取指定 ID 的知识条目。"""
        return self._entries.get(entry_id)

    async def update(self, entry_id: str, **kwargs: Any) -> bool:
        """更新知识条目的字段。返回是否成功。"""
        entry = self._entries.get(entry_id)
        if entry is None:
            return False

        if "category" in kwargs and kwargs["category"] not in VALID_CATEGORIES:
            raise ValueError(f"无效分类 '{kwargs['category']}'，合法值: {VALID_CATEGORIES}")

        for key, value in kwargs.items():
            if hasattr(entry, key):
                setattr(entry, key, value)

        entry.updated_at = datetime.now()
        logger.debug("更新知识条目 {}: {}", entry_id, list(kwargs.keys()))
        return True

    async def delete(self, entry_id: str) -> bool:
        """删除知识条目。返回是否成功。"""
        removed = self._entries.pop(entry_id, None)
        if removed is not None:
            logger.debug("删除知识条目 {}: {}", entry_id, removed.title)
            return True
        return False

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> list[KnowledgeEntry]:
        """搜索知识条目。

        支持关键词（匹配 title 和 content）、分类、标签过滤。
        多个条件之间取交集。
        """
        results = list(self._entries.values())

        if category is not None:
            results = [e for e in results if e.category == category]

        if tags:
            tag_set = set(tags)
            results = [e for e in results if tag_set.intersection(e.tags)]

        if query:
            q_lower = query.lower()
            results = [
                e
                for e in results
                if q_lower in e.title.lower() or q_lower in e.content.lower()
            ]

        return results

    async def list_categories(self) -> list[str]:
        """列出所有存在的分类。"""
        return sorted({e.category for e in self._entries.values()})

    # ------------------------------------------------------------------
    # 技能注册（同步方法）
    # ------------------------------------------------------------------

    def register_skill(self, name: str, description: str, usage: str) -> str:
        """注册一个技能到知识库。同步方法，因为可能在高频调用。

        如果同名技能已存在，更新其信息。
        """
        # 检查是否已存在同名 skill
        for entry in self._entries.values():
            if entry.category == "skill" and entry.title == name:
                entry.content = description
                entry.metadata["usage"] = usage
                entry.updated_at = datetime.now()
                logger.debug("更新技能: {}", name)
                return entry.id

        entry_id = uuid.uuid4().hex[:12]
        now = datetime.now()
        entry = KnowledgeEntry(
            id=entry_id,
            title=name,
            content=description,
            category="skill",
            tags=["skill"],
            metadata={"usage": usage},
            created_at=now,
            updated_at=now,
        )
        self._entries[entry_id] = entry
        logger.debug("注册技能: {} ({})", name, entry_id)
        return entry_id

    def get_skill(self, name: str) -> KnowledgeEntry | None:
        """获取已注册的技能信息。"""
        for entry in self._entries.values():
            if entry.category == "skill" and entry.title == name:
                return entry
        return None
