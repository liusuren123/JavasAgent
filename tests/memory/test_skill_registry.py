"""测试技能注册表模块。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from src.memory.skill_models import SkillDefinition
from src.memory.skill_registry import SkillRegistry


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def run(coro):
    """同步运行异步函数。"""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def registry(tmp_path: Path) -> SkillRegistry:
    """创建使用临时目录的技能注册表。"""
    reg = SkillRegistry(storage_dir=tmp_path / "skills")
    run(reg.initialize())
    return reg


@pytest.fixture
def registry_memory() -> SkillRegistry:
    """纯内存模式的技能注册表。"""
    return SkillRegistry()


def _make_skill(
    name: str = "test_skill",
    description: str = "测试技能",
    category: str = "tool",
    **kwargs,
) -> SkillDefinition:
    """创建测试用技能定义。"""
    return SkillDefinition.create(
        name=name,
        description=description,
        category=category,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 基本 CRUD
# ---------------------------------------------------------------------------


class TestRegister:
    async def test_register_new_skill(self, registry: SkillRegistry):
        skill = _make_skill(name="截图", description="截取屏幕截图")
        skill_id = await registry.register(skill)

        assert skill_id == skill.id
        assert registry.count == 1

        fetched = await registry.get(skill_id)
        assert fetched is not None
        assert fetched.name == "截图"
        assert fetched.description == "截取屏幕截图"

    async def test_register_duplicate_name_updates(self, registry: SkillRegistry):
        """同名技能注册时更新已有条目。"""
        skill1 = _make_skill(name="截图", description="旧描述")
        id1 = await registry.register(skill1)

        skill2 = _make_skill(name="截图", description="新描述")
        id2 = await registry.register(skill2)

        assert id1 == id2  # ID 不变
        assert registry.count == 1

        fetched = await registry.get(id1)
        assert fetched.description == "新描述"

    async def test_register_multiple(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="a"))
        await registry.register(_make_skill(name="b"))
        await registry.register(_make_skill(name="c"))
        assert registry.count == 3


class TestUnregister:
    async def test_unregister_existing(self, registry: SkillRegistry):
        skill = _make_skill(name="remove_me")
        sid = await registry.register(skill)

        result = await registry.unregister(sid)
        assert result is True
        assert registry.count == 0
        assert await registry.get(sid) is None

    async def test_unregister_nonexistent(self, registry: SkillRegistry):
        result = await registry.unregister("nonexistent_id")
        assert result is False


class TestGet:
    async def test_get_existing(self, registry: SkillRegistry):
        skill = _make_skill(name="find_me")
        sid = await registry.register(skill)

        fetched = await registry.get(sid)
        assert fetched is not None
        assert fetched.name == "find_me"

    async def test_get_nonexistent(self, registry: SkillRegistry):
        fetched = await registry.get("nonexistent")
        assert fetched is None

    async def test_get_by_name(self, registry: SkillRegistry):
        skill = _make_skill(name="by_name")
        await registry.register(skill)

        fetched = await registry.get_by_name("by_name")
        assert fetched is not None
        assert fetched.name == "by_name"

    async def test_get_by_name_nonexistent(self, registry: SkillRegistry):
        fetched = await registry.get_by_name("nope")
        assert fetched is None


class TestListAll:
    async def test_list_all(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="a", category="tool"))
        await registry.register(_make_skill(name="b", category="workflow"))
        await registry.register(_make_skill(name="c", category="tool"))

        all_skills = await registry.list_all()
        assert len(all_skills) == 3

    async def test_list_by_category(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="a", category="tool"))
        await registry.register(_make_skill(name="b", category="workflow"))
        await registry.register(_make_skill(name="c", category="tool"))

        tools = await registry.list_all(category="tool")
        assert len(tools) == 2
        assert all(s.category == "tool" for s in tools)

    async def test_list_empty(self, registry: SkillRegistry):
        skills = await registry.list_all()
        assert skills == []


class TestListCategories:
    async def test_list_categories(self, registry: SkillRegistry):
        await registry.register(_make_skill(category="tool"))
        await registry.register(_make_skill(name="b", category="workflow"))
        await registry.register(_make_skill(name="c", category="learned"))

        cats = await registry.list_categories()
        assert cats == ["learned", "tool", "workflow"]


# ---------------------------------------------------------------------------
# 搜索
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_search_by_name(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="屏幕截图", description="截取屏幕"))
        await registry.register(_make_skill(name="文件读取", description="读取文件"))

        results = await registry.search("截图")
        assert len(results) == 1
        assert results[0].name == "屏幕截图"

    async def test_search_by_description(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="工具A", description="用于数据分析"))
        await registry.register(_make_skill(name="工具B", description="用于文件管理"))

        results = await registry.search("数据")
        assert len(results) == 1
        assert results[0].name == "工具A"

    async def test_search_by_tag(self, registry: SkillRegistry):
        await registry.register(
            _make_skill(name="工具A", tags=["截图", "屏幕"])
        )
        await registry.register(
            _make_skill(name="工具B", tags=["文件", "管理"])
        )

        results = await registry.search("截图")
        assert len(results) == 1
        assert results[0].name == "工具A"

    async def test_search_with_category_filter(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="截图", category="tool", description="截取屏幕"))
        await registry.register(_make_skill(name="截图流程", category="workflow", description="截取屏幕流程"))

        results = await registry.search("截图", category="tool")
        assert len(results) == 1
        assert results[0].category == "tool"

    async def test_search_top_k(self, registry: SkillRegistry):
        for i in range(5):
            await registry.register(_make_skill(name=f"截图工具{i}", description="截图"))

        results = await registry.search("截图", top_k=3)
        assert len(results) == 3

    async def test_search_no_results(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="a", description="aaa"))
        results = await registry.search("zzzzz")
        assert results == []

    async def test_search_empty_query(self, registry: SkillRegistry):
        await registry.register(_make_skill(name="a"))
        await registry.register(_make_skill(name="b"))
        results = await registry.search("")
        assert len(results) == 2


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------


class TestPersistence:
    async def test_save_and_reload(self, tmp_path: Path):
        storage_dir = tmp_path / "skills"

        # 创建并注册
        reg1 = SkillRegistry(storage_dir=storage_dir)
        await reg1.initialize()
        await reg1.register(_make_skill(name="持久化测试", description="测试持久化"))
        await reg1.save()

        # 重新加载
        reg2 = SkillRegistry(storage_dir=storage_dir)
        await reg2.initialize()

        assert reg2.count == 1
        fetched = await reg2.get_by_name("持久化测试")
        assert fetched is not None
        assert fetched.description == "测试持久化"

    async def test_memory_mode_no_persistence(self, registry_memory: SkillRegistry):
        """内存模式不应尝试持久化。"""
        await registry_memory.register(_make_skill(name="temp"))
        # save 不应报错
        await registry_memory.save()
        assert registry_memory.count == 1


# ---------------------------------------------------------------------------
# 从 TOOL_REGISTRY 加载
# ---------------------------------------------------------------------------


class TestLoadFromTools:
    async def test_load_from_tools(self, registry: SkillRegistry):
        await registry.load_from_tools()

        # 应加载了一些工具
        assert registry.count > 0

        # 检查加载的工具有正确的 category 和 source
        all_skills = await registry.list_all(category="builtin")
        for skill in all_skills:
            assert skill.source == "tool_registry"
            assert skill.category == "builtin"

    async def test_load_from_tools_idempotent(self, registry: SkillRegistry):
        """重复加载不应创建重复。"""
        await registry.load_from_tools()
        count1 = registry.count

        await registry.load_from_tools()
        count2 = registry.count

        assert count1 == count2
