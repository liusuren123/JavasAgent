"""工具自动注册器测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.tools import TOOL_METADATA, TOOL_REGISTRY
from src.tools.registry import ToolRegistry
from src.utils.config import AppConfig, ToolConfig, ToolsConfig


# ---------------------------------------------------------------------------
# 辅助 fixtures
# ---------------------------------------------------------------------------


def _make_agent_mock() -> MagicMock:
    """创建一个模拟的 BaseAgent 实例。

    agent._llm 用于需要 LLM 的工具（如 code_dev）。
    agent.register_tool 用于验证注册调用。
    """
    agent = MagicMock()
    agent._llm = MagicMock()
    # 让 register_tool 不做任何事（仅记录调用）
    agent.register_tool = MagicMock()
    return agent


def _make_config(
    enabled_tools: set[str] | None = None,
    disabled_tools: set[str] | None = None,
) -> AppConfig:
    """创建测试配置。

    Args:
        enabled_tools: 指定启用的工具集合（覆盖默认全部启用）
        disabled_tools: 指定禁用的工具集合（从默认配置中禁用）
    """
    config = AppConfig()
    if enabled_tools is not None:
        # 只启用指定的工具，其他全部禁用
        for field_name in type(config.tools).model_fields:
            tc = getattr(config.tools, field_name)
            if isinstance(tc, ToolConfig):
                tc.enabled = field_name in enabled_tools
    if disabled_tools is not None:
        for name in disabled_tools:
            tc = getattr(config.tools, name, None)
            if tc and isinstance(tc, ToolConfig):
                tc.enabled = False
    return config


# ---------------------------------------------------------------------------
# 测试：auto_register 只注册 enabled 的工具
# ---------------------------------------------------------------------------


class TestAutoRegisterEnabled:
    """验证只有 enabled=True 的工具才会被注册。"""

    def test_all_enabled_registers_all(self) -> None:
        """所有工具都启用时，TOOL_REGISTRY 中的每个工具都应该被注册。"""
        agent = _make_agent_mock()
        config = _make_config()  # 默认全部启用

        result = ToolRegistry.auto_register(agent, config)

        # 至少应该有 TOOL_REGISTRY 数量的 register_tool 调用
        # （加上别名的额外调用）
        assert len(result["registered"]) > 0
        assert len(result["skipped"]) == 0

        # 验证 register_tool 被调用
        assert agent.register_tool.called

    def test_only_system_control_enabled(self) -> None:
        """只启用 system_control 时，仅注册它（及别名 shell）。"""
        agent = _make_agent_mock()
        config = _make_config(enabled_tools={"system_control"})

        result = ToolRegistry.auto_register(agent, config)

        # system_control + alias shell = 2 次注册
        registered_names = result["registered"]
        assert "system_control" in registered_names
        # shell 是别名
        assert any("shell" in r for r in registered_names)
        # 不应包含其他工具
        assert "browser_control" not in registered_names
        assert "office_ops" not in registered_names

    def test_no_tools_enabled(self) -> None:
        """所有工具都禁用时，不应注册任何工具。"""
        agent = _make_agent_mock()
        config = _make_config(enabled_tools=set())

        result = ToolRegistry.auto_register(agent, config)

        assert len(result["registered"]) == 0
        assert len(result["skipped"]) > 0


# ---------------------------------------------------------------------------
# 测试：disabled 的工具不注册
# ---------------------------------------------------------------------------


class TestAutoRegisterDisabled:
    """验证 disabled 工具被正确跳过。"""

    def test_disabled_tool_not_registered(self) -> None:
        """禁用特定工具时，不应出现在已注册列表中。"""
        agent = _make_agent_mock()
        config = _make_config(disabled_tools={"browser_control", "email_ops"})

        result = ToolRegistry.auto_register(agent, config)

        registered_names = result["registered"]
        assert "browser_control" not in registered_names
        assert "email_ops" not in registered_names

        # 跳过列表中应该包含禁用的工具
        skipped_str = " ".join(result["skipped"])
        assert "browser_control" in skipped_str
        assert "email_ops" in skipped_str

    def test_skipped_reports_reason(self) -> None:
        """跳过的工具应注明原因（已禁用）。"""
        agent = _make_agent_mock()
        config = _make_config(disabled_tools={"voice_ops"})

        result = ToolRegistry.auto_register(agent, config)

        assert any("voice_ops" in s and "禁用" in s for s in result["skipped"])


# ---------------------------------------------------------------------------
# 测试：别名注册
# ---------------------------------------------------------------------------


class TestAliasRegistration:
    """验证工具别名被正确注册。"""

    def test_system_control_shell_alias(self) -> None:
        """system_control 的别名 shell 应该被注册。"""
        agent = _make_agent_mock()
        config = _make_config(enabled_tools={"system_control"})

        ToolRegistry.auto_register(agent, config)

        # register_tool 应该被调用两次：system_control + shell
        calls = agent.register_tool.call_args_list
        registered_names = [call[0][0] for call in calls]

        assert "system_control" in registered_names
        assert "shell" in registered_names

    def test_alias_same_instance(self) -> None:
        """别名和主名称应该注册同一个工具实例。"""
        agent = _make_agent_mock()
        config = _make_config(enabled_tools={"system_control"})

        ToolRegistry.auto_register(agent, config)

        calls = agent.register_tool.call_args_list
        # 找到 system_control 和 shell 的调用
        instances = {call[0][0]: call[0][1] for call in calls}

        assert instances.get("system_control") is instances.get("shell")

    def test_no_aliases_for_most_tools(self) -> None:
        """大多数工具没有别名，只注册一次。"""
        agent = _make_agent_mock()
        config = _make_config(enabled_tools={"process_manager", "office_ops"})

        ToolRegistry.auto_register(agent, config)

        calls = agent.register_tool.call_args_list
        registered_names = [call[0][0] for call in calls]

        # 这些工具只有主名称
        assert registered_names.count("process_manager") == 1
        assert registered_names.count("office_ops") == 1


# ---------------------------------------------------------------------------
# 测试：元数据读取
# ---------------------------------------------------------------------------


class TestToolMetadata:
    """验证工具元数据的正确性。"""

    def test_all_registry_tools_have_metadata(self) -> None:
        """TOOL_REGISTRY 中的每个工具都应有对应的元数据。"""
        for tool_name in TOOL_REGISTRY:
            assert tool_name in TOOL_METADATA, f"缺少元数据: {tool_name}"

    def test_metadata_description_not_empty(self) -> None:
        """每个工具的描述不应为空。"""
        for name, meta in TOOL_METADATA.items():
            assert meta.description, f"描述为空: {name}"

    def test_code_dev_requires_llm(self) -> None:
        """code_dev 应标记为需要 LLM。"""
        meta = TOOL_METADATA.get("code_dev")
        assert meta is not None
        assert meta.requires_llm is True

    def test_system_control_has_shell_alias(self) -> None:
        """system_control 应有 shell 别名。"""
        meta = TOOL_METADATA.get("system_control")
        assert meta is not None
        assert "shell" in meta.aliases

    def test_list_available_tools(self) -> None:
        """list_available_tools 应返回所有工具的信息。"""
        info = ToolRegistry.list_available_tools()

        assert len(info) == len(TOOL_REGISTRY)
        # 检查每个条目有正确的字段
        for name, data in info.items():
            assert "class" in data
            assert "description" in data
            assert "aliases" in data
            assert "requires_llm" in data
            assert isinstance(data["aliases"], list)
            assert isinstance(data["requires_llm"], bool)


# ---------------------------------------------------------------------------
# 测试：requires_llm 的工具获得 llm_client
# ---------------------------------------------------------------------------


class TestRequiresLLM:
    """验证需要 LLM 的工具在实例化时获得了 llm_client。"""

    def test_code_dev_gets_llm_client(self) -> None:
        """code_dev 实例化时应传入 llm_client。"""
        agent = _make_agent_mock()
        config = _make_config(enabled_tools={"code_dev"})

        ToolRegistry.auto_register(agent, config)

        # 验证 register_tool 被调用
        calls = agent.register_tool.call_args_list
        assert len(calls) >= 1

        # 获取注册的工具实例
        for call in calls:
            name = call[0][0]
            if name == "code_dev":
                tool_instance = call[0][1]
                # 验证工具实例有 _llm_client 属性
                assert hasattr(tool_instance, "_llm_client")
                assert tool_instance._llm_client is agent._llm
                break
        else:
            pytest.fail("code_dev 未被注册")

    def test_non_llm_tool_no_extra_kwargs(self) -> None:
        """不需要 LLM 的工具不应收到 llm_client 参数。"""
        agent = _make_agent_mock()
        config = _make_config(enabled_tools={"process_manager"})

        # 不应该抛异常（ProcessManager 不接受 llm_client 参数）
        result = ToolRegistry.auto_register(agent, config)
        assert "process_manager" in result["registered"]
