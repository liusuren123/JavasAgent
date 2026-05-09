"""PluginManager 插件管理器测试。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.tools.plugin_manager import PluginManager
from src.tools.plugin_models import (
    PluginInfo,
    PluginManifest,
    PluginState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def plugins_dir(tmp_path):
    """创建临时插件目录。"""
    d = tmp_path / "plugins"
    d.mkdir()
    return d


@pytest.fixture
def data_dir(tmp_path):
    """创建临时数据目录。"""
    return tmp_path / "data"


@pytest.fixture
def manager(plugins_dir, data_dir):
    """创建使用临时目录的 PluginManager 实例。"""
    return PluginManager(config={
        "plugins_dir": str(plugins_dir),
        "data_dir": str(data_dir),
    })


def make_plugin_dir(
    parent: Path,
    plugin_id: str = "test_plugin",
    name: str = "测试插件",
    version: str = "1.0.0",
    entry_point: str = "main.py",
    dependencies: list[str] | None = None,
    extra_yaml: dict | None = None,
    main_code: str = "VALUE = 42\n",
) -> Path:
    """在 parent 下创建一个完整的插件目录。"""
    plugin_dir = parent / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "id": plugin_id,
        "name": name,
        "version": version,
        "description": f"{name}描述",
        "entry_point": entry_point,
        "dependencies": dependencies or [],
    }
    if extra_yaml:
        manifest.update(extra_yaml)

    (plugin_dir / "plugin.yaml").write_text(
        yaml.dump(manifest, allow_unicode=True), encoding="utf-8"
    )
    (plugin_dir / "main.py").write_text(main_code, encoding="utf-8")
    return plugin_dir


# ---------------------------------------------------------------------------
# PluginManifest 校验
# ---------------------------------------------------------------------------

class TestPluginManifest:
    """测试 PluginManifest 数据模型。"""

    def test_from_dict_minimal(self):
        """最小字段创建。"""
        m = PluginManifest.from_dict({"id": "p1", "name": "P1"})
        assert m.id == "p1"
        assert m.name == "P1"
        assert m.version == "0.1.0"
        assert m.dependencies == []

    def test_from_dict_full(self):
        """完整字段创建。"""
        m = PluginManifest.from_dict({
            "id": "p1", "name": "P1", "version": "2.0.0",
            "description": "desc", "entry_point": "mod.py",
            "dependencies": ["dep1", "dep2"], "author": "test",
            "tags": ["tag1"], "extra": {"key": "val"},
        })
        assert m.version == "2.0.0"
        assert m.dependencies == ["dep1", "dep2"]

    def test_to_dict_roundtrip(self):
        """序列化/反序列化往返。"""
        m = PluginManifest(id="p1", name="P1", version="1.0.0")
        d = m.to_dict()
        restored = PluginManifest.from_dict(d)
        assert restored.id == m.id
        assert restored.name == m.name
        assert restored.version == m.version

    def test_validate_dict_valid(self):
        """有效数据校验通过。"""
        errors = PluginManifest.validate_dict({
            "id": "p1", "name": "P1", "version": "1.0.0",
        })
        assert errors == []

    def test_validate_dict_missing_id(self):
        """缺少 id 字段。"""
        errors = PluginManifest.validate_dict({"name": "P1"})
        assert len(errors) == 1
        assert "id" in errors[0]

    def test_validate_dict_missing_name(self):
        """缺少 name 字段。"""
        errors = PluginManifest.validate_dict({"id": "p1"})
        assert len(errors) == 1
        assert "name" in errors[0]

    def test_validate_dict_empty_id(self):
        """空 id 字段。"""
        errors = PluginManifest.validate_dict({"id": "", "name": "P1"})
        assert len(errors) == 1

    def test_validate_dict_invalid_dependencies(self):
        """dependencies 不是列表。"""
        errors = PluginManifest.validate_dict({
            "id": "p1", "name": "P1", "dependencies": "not_a_list",
        })
        assert any("dependencies" in e for e in errors)

    def test_validate_dict_invalid_version(self):
        """version 不是字符串。"""
        errors = PluginManifest.validate_dict({
            "id": "p1", "name": "P1", "version": 123,
        })
        assert any("version" in e for e in errors)


# ---------------------------------------------------------------------------
# PluginState 枚举
# ---------------------------------------------------------------------------

class TestPluginState:
    """测试 PluginState 枚举。"""

    def test_values(self):
        assert PluginState.INSTALLED.value == "installed"
        assert PluginState.ENABLED.value == "enabled"
        assert PluginState.DISABLED.value == "disabled"
        assert PluginState.ERROR.value == "error"

    def test_from_string(self):
        assert PluginState("enabled") == PluginState.ENABLED


# ---------------------------------------------------------------------------
# PluginInfo
# ---------------------------------------------------------------------------

class TestPluginInfo:
    """测试 PluginInfo 数据模型。"""

    def test_from_manifest(self):
        m = PluginManifest(id="p1", name="P1")
        info = PluginInfo.from_manifest(m, install_path="/tmp/p1")
        assert info.plugin_id == "p1"
        assert info.state == PluginState.INSTALLED
        assert info.install_time is not None

    def test_to_dict(self):
        m = PluginManifest(id="p1", name="P1")
        info = PluginInfo(plugin_id="p1", manifest=m, install_path="/tmp/p1")
        d = info.to_dict()
        assert d["plugin_id"] == "p1"
        assert d["state"] == "installed"
        assert "manifest" in d


# ---------------------------------------------------------------------------
# 安装插件
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_install_from_local(manager, plugins_dir, tmp_path):
    """测试从本地路径安装插件。"""
    source = make_plugin_dir(tmp_path / "source_plugins")
    result = await manager.execute("install_plugin", {"source": str(source)})
    assert result["success"] is True
    assert result["data"]["plugin_id"] == "test_plugin"
    assert result["data"]["state"] == "installed"
    assert (plugins_dir / "test_plugin").exists()


@pytest.mark.asyncio
async def test_install_duplicate_id(manager, tmp_path):
    """测试安装相同 ID 的插件会覆盖。"""
    source1 = make_plugin_dir(tmp_path / "s1", plugin_id="dup", version="1.0.0")
    source2 = make_plugin_dir(tmp_path / "s2", plugin_id="dup", version="2.0.0")

    await manager.execute("install_plugin", {"source": str(source1)})
    result = await manager.execute("install_plugin", {"source": str(source2)})
    assert result["success"] is True
    assert result["data"]["manifest"]["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_install_missing_plugin_yaml(manager, tmp_path):
    """测试安装缺少 plugin.yaml 的插件。"""
    bad_dir = tmp_path / "bad_plugin"
    bad_dir.mkdir()
    (bad_dir / "main.py").write_text("pass")
    result = await manager.execute("install_plugin", {"source": str(bad_dir)})
    assert result["success"] is False
    assert "plugin.yaml" in result["error"]


@pytest.mark.asyncio
async def test_install_invalid_yaml(manager, tmp_path):
    """测试安装 plugin.yaml 格式无效的插件。"""
    bad_dir = tmp_path / "invalid_plugin"
    bad_dir.mkdir()
    (bad_dir / "plugin.yaml").write_text("not: valid\n: yaml: [", encoding="utf-8")
    (bad_dir / "main.py").write_text("pass")
    result = await manager.execute("install_plugin", {"source": str(bad_dir)})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_install_missing_id_in_yaml(manager, tmp_path):
    """测试安装 plugin.yaml 缺少 id 的插件。"""
    bad_dir = tmp_path / "no_id_plugin"
    bad_dir.mkdir()
    (bad_dir / "plugin.yaml").write_text(
        yaml.dump({"name": "无ID", "version": "1.0.0"}), encoding="utf-8"
    )
    (bad_dir / "main.py").write_text("pass")
    result = await manager.execute("install_plugin", {"source": str(bad_dir)})
    assert result["success"] is False
    assert "id" in result["error"]


@pytest.mark.asyncio
async def test_install_no_source(manager):
    """测试安装缺少 source 参数。"""
    result = await manager.execute("install_plugin", {})
    assert result["success"] is False
    assert "source" in result["error"]


@pytest.mark.asyncio
async def test_install_invalid_source(manager):
    """测试安装无效的源路径。"""
    result = await manager.execute("install_plugin", {"source": "/nonexistent/path"})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 卸载插件
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_uninstall(manager, tmp_path):
    """测试卸载插件。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})
    result = await manager.execute("uninstall_plugin", {"plugin_id": "test_plugin"})
    assert result["success"] is True
    assert result["data"]["uninstalled_plugin_id"] == "test_plugin"


@pytest.mark.asyncio
async def test_uninstall_not_found(manager):
    """测试卸载不存在的插件。"""
    result = await manager.execute("uninstall_plugin", {"plugin_id": "nope"})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_uninstall_missing_id(manager):
    """测试卸载缺少 plugin_id。"""
    result = await manager.execute("uninstall_plugin", {})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 启用 / 禁用
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enable_plugin(manager, tmp_path):
    """测试启用插件。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})

    result = await manager.execute("enable_plugin", {"plugin_id": "test_plugin"})
    assert result["success"] is True
    assert result["data"]["state"] == "enabled"


@pytest.mark.asyncio
async def test_enable_already_enabled(manager, tmp_path):
    """测试重复启用插件。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})
    await manager.execute("enable_plugin", {"plugin_id": "test_plugin"})

    result = await manager.execute("enable_plugin", {"plugin_id": "test_plugin"})
    assert result["success"] is True


@pytest.mark.asyncio
async def test_enable_not_found(manager):
    """测试启用不存在的插件。"""
    result = await manager.execute("enable_plugin", {"plugin_id": "nope"})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_disable_plugin(manager, tmp_path):
    """测试禁用插件。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})
    await manager.execute("enable_plugin", {"plugin_id": "test_plugin"})

    result = await manager.execute("disable_plugin", {"plugin_id": "test_plugin"})
    assert result["success"] is True
    assert result["data"]["state"] == "disabled"


@pytest.mark.asyncio
async def test_disable_not_enabled(manager, tmp_path):
    """测试禁用未启用的插件。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})

    result = await manager.execute("disable_plugin", {"plugin_id": "test_plugin"})
    assert result["success"] is True
    assert result["data"]["state"] == "disabled"


@pytest.mark.asyncio
async def test_disable_not_found(manager):
    """测试禁用不存在的插件。"""
    result = await manager.execute("disable_plugin", {"plugin_id": "nope"})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 热重载
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reload_plugin(manager, tmp_path):
    """测试热重载插件。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})
    await manager.execute("enable_plugin", {"plugin_id": "test_plugin"})

    result = await manager.execute("reload_plugin", {"plugin_id": "test_plugin"})
    assert result["success"] is True
    assert result["data"]["state"] == "enabled"


@pytest.mark.asyncio
async def test_reload_not_found(manager):
    """测试重载不存在的插件。"""
    result = await manager.execute("reload_plugin", {"plugin_id": "nope"})
    assert result["success"] is False


@pytest.mark.asyncio
async def test_reload_missing_id(manager):
    """测试重载缺少 plugin_id。"""
    result = await manager.execute("reload_plugin", {})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 列出插件
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_plugins_empty(manager):
    """测试空插件列表。"""
    result = await manager.execute("list_plugins", {})
    assert result["success"] is True
    assert result["data"]["count"] == 0
    assert result["data"]["plugins"] == []


@pytest.mark.asyncio
async def test_list_plugins(manager, tmp_path):
    """测试列出插件。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})
    result = await manager.execute("list_plugins", {})
    assert result["success"] is True
    assert result["data"]["count"] == 1


@pytest.mark.asyncio
async def test_list_plugins_filter_state(manager, tmp_path):
    """测试按状态过滤插件列表。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})

    result = await manager.execute("list_plugins", {"state": "installed"})
    assert result["data"]["count"] == 1

    result = await manager.execute("list_plugins", {"state": "enabled"})
    assert result["data"]["count"] == 0


# ---------------------------------------------------------------------------
# 获取插件信息
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_plugin_info(manager, tmp_path):
    """测试获取插件信息。"""
    source = make_plugin_dir(tmp_path / "src")
    await manager.execute("install_plugin", {"source": str(source)})

    result = await manager.execute("get_plugin_info", {"plugin_id": "test_plugin"})
    assert result["success"] is True
    assert result["data"]["plugin_id"] == "test_plugin"
    assert result["data"]["manifest"]["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_get_plugin_info_not_found(manager):
    """测试获取不存在插件的信息。"""
    result = await manager.execute("get_plugin_info", {"plugin_id": "nope"})
    assert result["success"] is False


# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dependency_check_on_enable(manager, tmp_path):
    """测试启用时检查依赖。"""
    source = make_plugin_dir(
        tmp_path / "src", plugin_id="dep_plugin",
        dependencies=["nonexistent_plugin"],
    )
    await manager.execute("install_plugin", {"source": str(source)})

    result = await manager.execute("enable_plugin", {"plugin_id": "dep_plugin"})
    assert result["success"] is False
    assert "nonexistent_plugin" in result["error"]


@pytest.mark.asyncio
async def test_dependency_satisfied(manager, tmp_path):
    """测试依赖已满足时可以启用。"""
    # 先安装并启用被依赖的插件
    dep_source = make_plugin_dir(tmp_path / "dep_src", plugin_id="base_plugin")
    await manager.execute("install_plugin", {"source": str(dep_source)})
    await manager.execute("enable_plugin", {"plugin_id": "base_plugin"})

    # 安装并启用依赖它的插件
    dep_plugin = make_plugin_dir(
        tmp_path / "main_src", plugin_id="main_plugin",
        dependencies=["base_plugin"],
    )
    await manager.execute("install_plugin", {"source": str(dep_plugin)})
    result = await manager.execute("enable_plugin", {"plugin_id": "main_plugin"})
    assert result["success"] is True


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_save_and_restore_state(plugins_dir, data_dir, tmp_path):
    """测试状态保存和恢复。"""
    mgr1 = PluginManager(config={
        "plugins_dir": str(plugins_dir),
        "data_dir": str(data_dir),
    })
    source = make_plugin_dir(tmp_path / "src")
    await mgr1.execute("install_plugin", {"source": str(source)})

    # 创建新实例，应能恢复状态
    mgr2 = PluginManager(config={
        "plugins_dir": str(plugins_dir),
        "data_dir": str(data_dir),
    })
    result = await mgr2.execute("list_plugins", {})
    assert result["data"]["count"] == 1
    assert result["data"]["plugins"][0]["plugin_id"] == "test_plugin"


@pytest.mark.asyncio
async def test_load_corrupted_state(plugins_dir, data_dir):
    """测试加载损坏的状态文件。"""
    data_dir.mkdir(parents=True, exist_ok=True)
    state_file = data_dir / "plugin_state.json"
    state_file.write_text("not valid json{{{", encoding="utf-8")

    mgr = PluginManager(config={
        "plugins_dir": str(plugins_dir),
        "data_dir": str(data_dir),
    })
    result = await mgr.execute("list_plugins", {})
    assert result["data"]["count"] == 0


# ---------------------------------------------------------------------------
# 未知操作
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_action(manager):
    """测试未知操作。"""
    result = await manager.execute("unknown_action", {})
    assert result["success"] is False
    assert "未知操作" in result["error"]
