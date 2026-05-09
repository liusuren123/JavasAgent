"""长期记忆模块。

基于 ChromaDB 的向量存储，支持语义检索历史经验与知识。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

from src.utils.config import MemoryConfig


@dataclass
class MemoryEntry:
    """一条长期记忆条目。"""

    id: str
    content: str
    category: str  # "experience" | "knowledge" | "preference" | "skill"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    relevance_score: float = 0.0


class LongTermMemory:
    """长期记忆（跨会话持久化）。

    使用 ChromaDB 做向量存储和语义检索，让 Agent 能从历史经验中学习。

    Usage::

        memory = LongTermMemory(config)
        await memory.initialize()

        # 存储
        entry_id = await memory.store("用户偏好深色主题", category="preference")

        # 检索
        results = await memory.recall("主题偏好", top_k=5)

        # 删除
        await memory.forget(entry_id)
    """

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        self._client: Any = None
        self._collection: Any = None
        self._initialized = False

    async def initialize(self) -> None:
        """初始化 ChromaDB 客户端和集合。

        首次调用时创建持久化目录和集合，后续调用复用已有数据。
        """
        if self._initialized:
            return

        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=self._config.long_term_db_path)
            self._collection = self._client.get_or_create_collection(
                name="javas_memory",
                metadata={"description": "JavasAgent 长期记忆"},
            )
            self._initialized = True
            logger.info(
                f"长期记忆初始化完成: {self._collection.count()} 条已有记录, "
                f"路径={self._config.long_term_db_path}"
            )
        except ImportError:
            logger.warning("chromadb 未安装，长期记忆不可用。请运行: pip install chromadb")
            self._initialized = False
        except Exception as e:
            logger.error(f"长期记忆初始化失败: {e}")
            self._initialized = False

    @property
    def is_available(self) -> bool:
        """长期记忆是否可用。"""
        return self._initialized and self._collection is not None

    async def store(
        self,
        content: str,
        category: str = "experience",
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """存储一条记忆。

        Args:
            content: 记忆内容（文本）
            category: 记忆分类（experience / knowledge / preference / skill）
            metadata: 附加元数据

        Returns:
            记忆条目 ID，存储失败返回 None
        """
        if not self.is_available:
            logger.warning("长期记忆不可用，跳过存储")
            return None

        entry_id = f"mem_{uuid.uuid4().hex[:12]}"
        meta: dict[str, Any] = {
            "category": category,
            "created_at": datetime.now().isoformat(),
        }
        if metadata:
            meta.update(metadata)

        try:
            self._collection.add(
                documents=[content],
                ids=[entry_id],
                metadatas=[meta],
            )
            logger.debug(f"长期记忆已存储: {entry_id} [{category}] ({len(content)} 字符)")
            return entry_id
        except Exception as e:
            logger.error(f"长期记忆存储失败: {e}")
            return None

    async def store_batch(
        self,
        entries: list[dict[str, Any]],
    ) -> list[str | None]:
        """批量存储记忆条目。

        Args:
            entries: 每个元素包含 content, category(可选), metadata(可选)

        Returns:
            与 entries 等长的 ID 列表，失败项为 None
        """
        if not self.is_available:
            logger.warning("长期记忆不可用，跳过批量存储")
            return [None] * len(entries)

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for entry in entries:
            entry_id = f"mem_{uuid.uuid4().hex[:12]}"
            content = entry.get("content", "")
            category = entry.get("category", "experience")
            meta: dict[str, Any] = {
                "category": category,
                "created_at": datetime.now().isoformat(),
            }
            meta.update(entry.get("metadata", {}))

            ids.append(entry_id)
            documents.append(content)
            metadatas.append(meta)

        try:
            self._collection.add(
                documents=documents,
                ids=ids,
                metadatas=metadatas,
            )
            logger.info(f"批量存储 {len(ids)} 条长期记忆")
            return ids
        except Exception as e:
            logger.error(f"批量存储失败: {e}")
            return [None] * len(entries)

    async def recall(
        self,
        query: str,
        top_k: int = 5,
        category: str | None = None,
    ) -> list[MemoryEntry]:
        """语义检索相关记忆。

        Args:
            query: 查询文本
            top_k: 返回最多 K 条结果
            category: 限定分类，None 表示所有分类

        Returns:
            按相关度排序的记忆条目列表
        """
        if not self.is_available:
            logger.warning("长期记忆不可用，无法检索")
            return []

        try:
            where_filter: dict[str, Any] | None = None
            if category:
                where_filter = {"category": category}

            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, self._collection.count()) if self._collection.count() > 0 else top_k,
                where=where_filter,
            )

            entries: list[MemoryEntry] = []
            if results and results["documents"] and results["documents"][0]:
                docs = results["documents"][0]
                metas = results["metadatas"][0] if results["metadatas"] else [{}] * len(docs)
                distances = results["distances"][0] if results["distances"] else [0.0] * len(docs)
                ids = results["ids"][0] if results["ids"] else [""] * len(docs)

                for doc, meta, dist, doc_id in zip(docs, metas, distances, ids):
                    created_str = meta.pop("created_at", datetime.now().isoformat())
                    try:
                        created_at = datetime.fromisoformat(created_str)
                    except (ValueError, TypeError):
                        created_at = datetime.now()

                    entries.append(MemoryEntry(
                        id=doc_id,
                        content=doc,
                        category=meta.get("category", "experience"),
                        metadata=meta,
                        created_at=created_at,
                        relevance_score=round(1.0 - dist, 4) if dist is not None else 0.0,
                    ))

            logger.debug(f"检索 '{query[:30]}...' 返回 {len(entries)} 条结果")
            return entries
        except Exception as e:
            logger.error(f"长期记忆检索失败: {e}")
            return []

    async def forget(self, entry_id: str) -> bool:
        """删除一条记忆。

        Args:
            entry_id: 记忆条目 ID

        Returns:
            是否成功删除
        """
        if not self.is_available:
            logger.warning("长期记忆不可用，无法删除")
            return False

        try:
            self._collection.delete(ids=[entry_id])
            logger.info(f"长期记忆已删除: {entry_id}")
            return True
        except Exception as e:
            logger.error(f"长期记忆删除失败: {e}")
            return False

    async def forget_batch(self, entry_ids: list[str]) -> int:
        """批量删除记忆条目。

        Args:
            entry_ids: 要删除的 ID 列表

        Returns:
            成功删除的数量
        """
        if not self.is_available or not entry_ids:
            return 0

        try:
            self._collection.delete(ids=entry_ids)
            logger.info(f"批量删除 {len(entry_ids)} 条长期记忆")
            return len(entry_ids)
        except Exception as e:
            logger.error(f"批量删除失败: {e}")
            return 0

    async def get_by_id(self, entry_id: str) -> MemoryEntry | None:
        """按 ID 获取单条记忆。

        Args:
            entry_id: 记忆条目 ID

        Returns:
            记忆条目，不存在返回 None
        """
        if not self.is_available:
            return None

        try:
            results = self._collection.get(ids=[entry_id])
            if not results["documents"]:
                return None

            doc = results["documents"][0]
            meta = results["metadatas"][0] if results["metadatas"] else {}
            created_str = meta.pop("created_at", datetime.now().isoformat())
            try:
                created_at = datetime.fromisoformat(created_str)
            except (ValueError, TypeError):
                created_at = datetime.now()

            return MemoryEntry(
                id=entry_id,
                content=doc,
                category=meta.get("category", "experience"),
                metadata=meta,
                created_at=created_at,
            )
        except Exception as e:
            logger.error(f"获取记忆失败: {e}")
            return None

    async def list_entries(
        self,
        category: str | None = None,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        """列出记忆条目。

        Args:
            category: 限定分类，None 表示所有分类
            limit: 最多返回数量

        Returns:
            记忆条目列表
        """
        if not self.is_available:
            return []

        try:
            where_filter = {"category": category} if category else None
            results = self._collection.get(
                where=where_filter,
                limit=limit,
            )

            entries: list[MemoryEntry] = []
            if results and results["documents"]:
                docs = results["documents"]
                metas = results["metadatas"] or [{}] * len(docs)
                ids = results["ids"] or [""] * len(docs)

                for doc, meta, doc_id in zip(docs, metas, ids):
                    created_str = meta.pop("created_at", datetime.now().isoformat())
                    try:
                        created_at = datetime.fromisoformat(created_str)
                    except (ValueError, TypeError):
                        created_at = datetime.now()

                    entries.append(MemoryEntry(
                        id=doc_id,
                        content=doc,
                        category=meta.get("category", "experience"),
                        metadata=meta,
                        created_at=created_at,
                    ))

            return entries
        except Exception as e:
            logger.error(f"列出记忆失败: {e}")
            return []

    @property
    def count(self) -> int:
        """当前存储的记忆条目总数。"""
        if not self.is_available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    async def clear(self) -> bool:
        """清空所有长期记忆。

        ⚠️ 不可恢复，调用前应确认。

        Returns:
            是否成功清空
        """
        if not self.is_available:
            return False

        try:
            # 删除集合后重建
            self._client.delete_collection("javas_memory")
            self._collection = self._client.get_or_create_collection(
                name="javas_memory",
                metadata={"description": "JavasAgent 长期记忆"},
            )
            logger.warning("长期记忆已清空")
            return True
        except Exception as e:
            logger.error(f"清空长期记忆失败: {e}")
            return False
