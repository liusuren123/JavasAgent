"""长期记忆模块测试。"""

from __future__ import annotations

import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.memory.long_term import LongTermMemory, MemoryEntry
from src.utils.config import MemoryConfig


# ---------------------------------------------------------------------------
# Fixture: 临时目录 + 配置
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db_path():
    """提供一个临时目录用于 ChromaDB，测试结束后自动清理。"""
    d = tempfile.mkdtemp(prefix="javas_ltm_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def config(tmp_db_path):
    return MemoryConfig(
        short_term_max_messages=50,
        long_term_db_path=tmp_db_path,
        embedding_model="text-embedding-3-small",
    )


@pytest.fixture
def memory(config):
    """创建一个 LongTermMemory 实例（不自动初始化）。"""
    return LongTermMemory(config)


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------

class TestInitialize:

    @pytest.mark.asyncio
    async def test_initialize_creates_collection(self, memory, config):
        """初始化应创建 ChromaDB 集合。"""
        await memory.initialize()
        assert memory.is_available
        assert memory.count == 0

    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, memory):
        """重复初始化不应报错。"""
        await memory.initialize()
        await memory.initialize()
        assert memory.is_available

    @pytest.mark.asyncio
    async def test_not_available_before_init(self, memory):
        """未初始化时 is_available 为 False。"""
        assert not memory.is_available

    @pytest.mark.asyncio
    async def test_initialize_graceful_on_import_error(self, config):
        """chromadb import 失败时应优雅降级。"""
        memory = LongTermMemory(config)
        with patch("builtins.__import__", side_effect=ImportError("no chromadb")):
            await memory.initialize()
        assert not memory.is_available

    @pytest.mark.asyncio
    async def test_persistent_storage(self, config):
        """数据应持久化到磁盘，重新创建实例后仍可读取。"""
        m1 = LongTermMemory(config)
        await m1.initialize()
        entry_id = await m1.store("持久化测试内容", category="knowledge")
        assert entry_id is not None

        # 新实例
        m2 = LongTermMemory(config)
        await m2.initialize()
        assert m2.count == 1
        result = await m2.get_by_id(entry_id)
        assert result is not None
        assert result.content == "持久化测试内容"


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------

class TestStore:

    @pytest.mark.asyncio
    async def test_store_returns_id(self, memory):
        await memory.initialize()
        entry_id = await memory.store("测试内容", category="experience")
        assert entry_id is not None
        assert entry_id.startswith("mem_")

    @pytest.mark.asyncio
    async def test_store_increments_count(self, memory):
        await memory.initialize()
        await memory.store("条目1")
        await memory.store("条目2")
        assert memory.count == 2

    @pytest.mark.asyncio
    async def test_store_with_metadata(self, memory):
        await memory.initialize()
        entry_id = await memory.store(
            "带元数据的记忆",
            category="preference",
            metadata={"source": "user", "importance": "high"},
        )
        result = await memory.get_by_id(entry_id)
        assert result is not None
        assert result.metadata.get("source") == "user"
        assert result.metadata.get("importance") == "high"
        assert result.category == "preference"

    @pytest.mark.asyncio
    async def test_store_without_init_returns_none(self, memory):
        """未初始化时 store 应返回 None。"""
        result = await memory.store("不应该存储")
        assert result is None


# ---------------------------------------------------------------------------
# 批量存储
# ---------------------------------------------------------------------------

class TestStoreBatch:

    @pytest.mark.asyncio
    async def test_batch_store(self, memory):
        await memory.initialize()
        entries = [
            {"content": "批量1", "category": "experience"},
            {"content": "批量2", "category": "knowledge"},
            {"content": "批量3", "category": "skill"},
        ]
        ids = await memory.store_batch(entries)
        assert len(ids) == 3
        assert all(id is not None for id in ids)
        assert memory.count == 3

    @pytest.mark.asyncio
    async def test_batch_store_without_init(self, memory):
        ids = await memory.store_batch([{"content": "x"}])
        assert ids == [None]


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------

class TestRecall:

    @pytest.mark.asyncio
    async def test_recall_by_semantic_similarity(self, memory):
        await memory.initialize()
        await memory.store("用户喜欢深色主题，不喜欢亮色", category="preference")
        await memory.store("Python 是最好的编程语言", category="knowledge")
        await memory.store("用户习惯用 Vim 编辑器", category="preference")

        results = await memory.recall("用户的视觉偏好", top_k=2)
        assert len(results) >= 1
        # 第一条应该与颜色/主题最相关
        assert any("主题" in r.content or "深色" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_recall_with_category_filter(self, memory):
        await memory.initialize()
        await memory.store("知识条目1", category="knowledge")
        await memory.store("经验条目1", category="experience")

        results = await memory.recall("条目", top_k=10, category="knowledge")
        assert all(r.category == "knowledge" for r in results)

    @pytest.mark.asyncio
    async def test_recall_returns_memory_entries(self, memory):
        await memory.initialize()
        await memory.store("测试检索结果格式", category="experience")

        results = await memory.recall("测试")
        assert len(results) >= 1
        entry = results[0]
        assert isinstance(entry, MemoryEntry)
        assert entry.id.startswith("mem_")
        assert entry.content == "测试检索结果格式"
        assert entry.relevance_score >= 0.0

    @pytest.mark.asyncio
    async def test_recall_without_init(self, memory):
        results = await memory.recall("测试")
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_empty_collection(self, memory):
        await memory.initialize()
        results = await memory.recall("不存在的查询")
        assert results == []


# ---------------------------------------------------------------------------
# 获取单条
# ---------------------------------------------------------------------------

class TestGetById:

    @pytest.mark.asyncio
    async def test_get_existing_entry(self, memory):
        await memory.initialize()
        entry_id = await memory.store("获取测试内容", category="knowledge")
        result = await memory.get_by_id(entry_id)
        assert result is not None
        assert result.content == "获取测试内容"
        assert result.category == "knowledge"

    @pytest.mark.asyncio
    async def test_get_nonexistent_entry(self, memory):
        await memory.initialize()
        result = await memory.get_by_id("mem_nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_without_init(self, memory):
        result = await memory.get_by_id("any_id")
        assert result is None


# ---------------------------------------------------------------------------
# 删除
# ---------------------------------------------------------------------------

class TestForget:

    @pytest.mark.asyncio
    async def test_forget_existing_entry(self, memory):
        await memory.initialize()
        entry_id = await memory.store("待删除内容")
        assert memory.count == 1

        success = await memory.forget(entry_id)
        assert success is True
        assert memory.count == 0

    @pytest.mark.asyncio
    async def test_forget_nonexistent_entry(self, memory):
        await memory.initialize()
        # ChromaDB 的 delete 对不存在的 id 不会报错，但返回 True
        success = await memory.forget("mem_nonexistent")
        # 具体行为取决于 ChromaDB 版本，只要不崩溃即可

    @pytest.mark.asyncio
    async def test_forget_without_init(self, memory):
        success = await memory.forget("any_id")
        assert success is False

    @pytest.mark.asyncio
    async def test_forget_batch(self, memory):
        await memory.initialize()
        entries = [
            {"content": "批量删除1"},
            {"content": "批量删除2"},
            {"content": "批量删除3"},
        ]
        ids = await memory.store_batch(entries)
        assert memory.count == 3

        deleted = await memory.forget_batch([id for id in ids if id is not None])
        assert deleted == 3
        assert memory.count == 0

    @pytest.mark.asyncio
    async def test_forget_batch_empty(self, memory):
        await memory.initialize()
        deleted = await memory.forget_batch([])
        assert deleted == 0


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------

class TestListEntries:

    @pytest.mark.asyncio
    async def test_list_all_entries(self, memory):
        await memory.initialize()
        await memory.store("列表条目1", category="knowledge")
        await memory.store("列表条目2", category="experience")

        entries = await memory.list_entries()
        assert len(entries) == 2

    @pytest.mark.asyncio
    async def test_list_by_category(self, memory):
        await memory.initialize()
        await memory.store("知识1", category="knowledge")
        await memory.store("经验1", category="experience")
        await memory.store("知识2", category="knowledge")

        entries = await memory.list_entries(category="knowledge")
        assert len(entries) == 2
        assert all(e.category == "knowledge" for e in entries)

    @pytest.mark.asyncio
    async def test_list_with_limit(self, memory):
        await memory.initialize()
        for i in range(10):
            await memory.store(f"条目{i}")

        entries = await memory.list_entries(limit=3)
        assert len(entries) == 3

    @pytest.mark.asyncio
    async def test_list_without_init(self, memory):
        entries = await memory.list_entries()
        assert entries == []


# ---------------------------------------------------------------------------
# 清空
# ---------------------------------------------------------------------------

class TestClear:

    @pytest.mark.asyncio
    async def test_clear_removes_all(self, memory):
        await memory.initialize()
        for i in range(5):
            await memory.store(f"待清空{i}")
        assert memory.count == 5

        success = await memory.clear()
        assert success is True
        assert memory.count == 0

    @pytest.mark.asyncio
    async def test_clear_without_init(self, memory):
        success = await memory.clear()
        assert success is False

    @pytest.mark.asyncio
    async def test_can_store_after_clear(self, memory):
        """清空后应仍可正常存储。"""
        await memory.initialize()
        await memory.store("清空前")
        await memory.clear()

        entry_id = await memory.store("清空后")
        assert entry_id is not None
        assert memory.count == 1


# ---------------------------------------------------------------------------
# count 属性
# ---------------------------------------------------------------------------

class TestCount:

    @pytest.mark.asyncio
    async def test_count_without_init(self, memory):
        assert memory.count == 0

    @pytest.mark.asyncio
    async def test_count_reflects_changes(self, memory):
        await memory.initialize()
        assert memory.count == 0

        entry_id = await memory.store("计数测试")
        assert memory.count == 1

        await memory.forget(entry_id)  # type: ignore[arg-type]
        assert memory.count == 0


# ---------------------------------------------------------------------------
# MemoryEntry 数据结构
# ---------------------------------------------------------------------------

class TestMemoryEntry:

    def test_default_values(self):
        entry = MemoryEntry(id="test", content="hello", category="experience")
        assert entry.metadata == {}
        assert entry.relevance_score == 0.0
        assert entry.created_at is not None

    def test_custom_values(self):
        import datetime
        now = datetime.datetime.now()
        entry = MemoryEntry(
            id="test",
            content="hello",
            category="knowledge",
            metadata={"key": "value"},
            created_at=now,
            relevance_score=0.95,
        )
        assert entry.category == "knowledge"
        assert entry.metadata["key"] == "value"
        assert entry.relevance_score == 0.95
        assert entry.created_at == now
