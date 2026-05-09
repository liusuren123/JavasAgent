"""测试知识库模块。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.memory.knowledge import KnowledgeBase, KnowledgeEntry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run(coro):
    """同步运行异步函数。"""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def kb(tmp_path: Path) -> KnowledgeBase:
    """创建使用临时目录的知识库。"""
    path = tmp_path / "knowledge.json"
    kb = KnowledgeBase(storage_path=path)
    run(kb.initialize())
    return kb


@pytest.fixture
def kb_memory() -> KnowledgeBase:
    """纯内存模式知识库。"""
    return KnowledgeBase()


# ---------------------------------------------------------------------------
# 基本 CRUD
# ---------------------------------------------------------------------------


class TestCRUD:
    async def test_add_and_get(self, kb: KnowledgeBase):
        eid = await kb.add("规则1", "不要在凌晨发邮件", "rule")
        entry = await kb.get(eid)
        assert entry is not None
        assert entry.title == "规则1"
        assert entry.content == "不要在凌晨发邮件"
        assert entry.category == "rule"
        assert entry.tags == []
        assert entry.metadata == {}

    async def test_get_nonexistent(self, kb: KnowledgeBase):
        result = await kb.get("no_such_id")
        assert result is None

    async def test_update(self, kb: KnowledgeBase):
        eid = await kb.add("标题", "内容", "project")
        ok = await kb.update(eid, title="新标题", content="新内容")
        assert ok is True
        entry = await kb.get(eid)
        assert entry.title == "新标题"
        assert entry.content == "新内容"
        assert entry.updated_at >= entry.created_at

    async def test_update_nonexistent(self, kb: KnowledgeBase):
        ok = await kb.update("no_such_id", title="x")
        assert ok is False

    async def test_delete(self, kb: KnowledgeBase):
        eid = await kb.add("临时", "待删除", "rule")
        ok = await kb.delete(eid)
        assert ok is True
        assert await kb.get(eid) is None

    async def test_delete_nonexistent(self, kb: KnowledgeBase):
        ok = await kb.delete("no_such_id")
        assert ok is False

    async def test_invalid_category(self, kb: KnowledgeBase):
        with pytest.raises(ValueError, match="无效分类"):
            await kb.add("标题", "内容", "invalid_cat")


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


class TestSearch:
    @pytest.fixture(autouse=True)
    async def _setup(self, kb: KnowledgeBase):
        self.kb = kb
        self.id1 = await kb.add(
            "邮件规则", "不要在凌晨发送邮件", "rule", tags=["email", "notification"]
        )
        self.id2 = await kb.add(
            "代码风格", "使用 Python 类型注解", "preference", tags=["python", "style"]
        )
        self.id3 = await kb.add(
            "API 设计", "RESTful 接口规范", "project", tags=["api", "design"]
        )
        self.id4 = await kb.add(
            "搜索偏好", "优先使用语义搜索", "preference", tags=["search"]
        )

    async def test_search_by_keyword(self):
        results = await self.kb.search(query="邮件")
        assert len(results) == 1
        assert results[0].title == "邮件规则"

    async def test_search_by_keyword_content(self):
        results = await self.kb.search(query="RESTful")
        assert len(results) == 1
        assert results[0].title == "API 设计"

    async def test_search_by_category(self):
        results = await self.kb.search(category="preference")
        assert len(results) == 2
        titles = {r.title for r in results}
        assert titles == {"代码风格", "搜索偏好"}

    async def test_search_by_tags(self):
        results = await self.kb.search(tags=["python"])
        assert len(results) == 1
        assert results[0].title == "代码风格"

    async def test_search_combined(self):
        results = await self.kb.search(query="搜索", category="preference")
        assert len(results) == 1
        assert results[0].title == "搜索偏好"

    async def test_search_no_match(self):
        results = await self.kb.search(query="不存在的关键词")
        assert results == []

    async def test_search_no_filter(self):
        results = await self.kb.search()
        assert len(results) == 4


class TestListCategories:
    async def test_list_categories(self, kb: KnowledgeBase):
        await kb.add("r1", "c1", "rule")
        await kb.add("p1", "c1", "preference")
        await kb.add("pr1", "c1", "project")
        cats = await kb.list_categories()
        assert cats == ["preference", "project", "rule"]

    async def test_empty(self, kb_memory: KnowledgeBase):
        await kb_memory.initialize()
        cats = await kb_memory.list_categories()
        assert cats == []


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------


class TestPersistence:
    async def test_save_and_reload(self, tmp_path: Path):
        path = tmp_path / "knowledge.json"

        # 写入
        kb1 = KnowledgeBase(storage_path=path)
        await kb1.initialize()
        eid = await kb1.add("持久测试", "内容持久化", "rule", tags=["test"])
        await kb1.save()

        # 重新加载
        kb2 = KnowledgeBase(storage_path=path)
        await kb2.initialize()
        entry = await kb2.get(eid)
        assert entry is not None
        assert entry.title == "持久测试"
        assert entry.tags == ["test"]

    async def test_memory_mode_no_file(self, tmp_path: Path):
        kb = KnowledgeBase()  # 纯内存
        await kb.initialize()
        await kb.add("内存条目", "不会保存到磁盘", "project")
        await kb.save()  # 不应报错
        assert (tmp_path / "knowledge.json").exists() is False


# ---------------------------------------------------------------------------
# 技能注册
# ---------------------------------------------------------------------------


class TestSkill:
    def test_register_and_get(self, kb: KnowledgeBase):
        sid = kb.register_skill("weather", "获取天气信息", "/weather <城市>")
        entry = kb.get_skill("weather")
        assert entry is not None
        assert entry.title == "weather"
        assert entry.content == "获取天气信息"
        assert entry.metadata["usage"] == "/weather <城市>"
        assert entry.category == "skill"

    def test_register_duplicate_updates(self, kb: KnowledgeBase):
        sid1 = kb.register_skill("tool1", "描述v1", "用法v1")
        sid2 = kb.register_skill("tool1", "描述v2", "用法v2")
        assert sid1 == sid2
        entry = kb.get_skill("tool1")
        assert entry.content == "描述v2"
        assert entry.metadata["usage"] == "用法v2"

    def test_get_nonexistent_skill(self, kb: KnowledgeBase):
        assert kb.get_skill("no_such_skill") is None

    async def test_skill_appears_in_search(self, kb: KnowledgeBase):
        kb.register_skill("my_tool", "测试工具", "/my_tool")
        results = await kb.search(category="skill")
        assert len(results) == 1
        assert results[0].title == "my_tool"


# ---------------------------------------------------------------------------
# 空知识库操作
# ---------------------------------------------------------------------------


class TestEmptyKnowledgeBase:
    async def test_get_on_empty(self, kb_memory: KnowledgeBase):
        await kb_memory.initialize()
        assert await kb_memory.get("any") is None

    async def test_search_on_empty(self, kb_memory: KnowledgeBase):
        await kb_memory.initialize()
        assert await kb_memory.search() == []
        assert await kb_memory.search(query="test") == []
        assert await kb_memory.search(category="rule") == []

    async def test_delete_on_empty(self, kb_memory: KnowledgeBase):
        await kb_memory.initialize()
        assert await kb_memory.delete("any") is False

    async def test_update_on_empty(self, kb_memory: KnowledgeBase):
        await kb_memory.initialize()
        assert await kb_memory.update("any", title="x") is False

    async def test_list_categories_on_empty(self, kb_memory: KnowledgeBase):
        await kb_memory.initialize()
        assert await kb_memory.list_categories() == []
