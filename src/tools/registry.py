"""工具自动注册器。

根据配置文件自动将工具注册到 Agent，替代手动逐个 import + 注册的模式。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from src.tools import TOOL_METADATA, TOOL_REGISTRY

if TYPE_CHECKING:
    from src.agents.base_agent import BaseAgent
    from src.utils.config import AppConfig


class ToolRegistry:
    """工具自动注册器。

    从 TOOL_REGISTRY 读取所有工具类，根据配置决定是否注册，
    自动处理别名和初始化参数。

    用法::

        from src.tools.registry import ToolRegistry

        agent = BaseAgent(config)
        ToolRegistry.auto_register(agent, config)
    """

    @staticmethod
    def auto_register(agent: BaseAgent, config: AppConfig) -> dict[str, list[str]]:
        """自动注册所有已启用的工具。

        遍历 TOOL_REGISTRY，对每个工具：
        1. 检查 config.tools 中是否有对应配置且 enabled=True
        2. 构建初始化参数（如 llm_client）
        3. 实例化并注册到 agent
        4. 处理别名（aliases），同一实例以多个名称注册

        Args:
            agent: BaseAgent 实例
            config: 应用配置

        Returns:
            注册结果摘要，格式为 {"registered": [...], "skipped": [...]}
        """
        registered: list[str] = []
        skipped: list[str] = []

        # 获取配置中所有工具属性的名称
        tools_cfg = config.tools
        # Pydantic v2: model_fields 包含所有字段名
        configured_names = set(type(tools_cfg).model_fields.keys())

        for tool_name, tool_cls in TOOL_REGISTRY.items():
            # 检查配置中是否有此工具
            tool_cfg = getattr(tools_cfg, tool_name, None)
            if tool_cfg is None or not getattr(tool_cfg, "enabled", False):
                reason = "配置中不存在" if tool_cfg is None else "已禁用"
                skipped.append(f"{tool_name} ({reason})")
                logger.debug(f"工具跳过: {tool_name} — {reason}")
                continue

            # 获取元数据
            meta = TOOL_METADATA.get(tool_name)

            # 构建初始化参数
            init_kwargs = ToolRegistry._build_init_kwargs(
                tool_name, tool_cls, agent, meta
            )

            # 实例化工具
            try:
                tool_instance = tool_cls(**init_kwargs)
            except Exception as e:
                logger.error(f"工具实例化失败: {tool_name} — {e}")
                skipped.append(f"{tool_name} (实例化失败: {e})")
                continue

            # 获取描述
            description = meta.description if meta else ""

            # 注册主名称
            agent.register_tool(tool_name, tool_instance, description=description)
            registered.append(tool_name)
            logger.info(f"工具已注册: {tool_name}")

            # 注册别名（同一实例，不同名称）
            if meta and meta.aliases:
                for alias in meta.aliases:
                    agent.register_tool(alias, tool_instance, description=description)
                    registered.append(f"{alias} (alias of {tool_name})")
                    logger.info(f"工具别名已注册: {alias} → {tool_name}")

        # 打印注册摘要
        logger.info(
            f"工具注册完成: {len(registered)} 个已注册, {len(skipped)} 个跳过"
        )

        return {"registered": registered, "skipped": skipped}

    @staticmethod
    def _build_init_kwargs(
        tool_name: str,
        tool_cls: type,
        agent: BaseAgent,
        meta: Any | None,
    ) -> dict[str, Any]:
        """根据工具类型构建初始化参数。

        目前支持的特殊处理：
        - code_dev: 需要 llm_client 参数
        - 其他工具: 使用默认参数

        可通过扩展此方法来支持更多特殊初始化需求。

        Args:
            tool_name: 工具名称
            tool_cls: 工具类
            agent: Agent 实例（用于提取 llm_client 等）
            meta: 工具元数据

        Returns:
            初始化关键字参数字典
        """
        kwargs: dict[str, Any] = {}

        # 需要 LLM 客户端的工具
        if meta and meta.requires_llm:
            kwargs["llm_client"] = agent._llm

        return kwargs

    @staticmethod
    def list_available_tools() -> dict[str, dict[str, Any]]:
        """列出所有可用工具及其元数据。

        Returns:
            工具信息字典，格式为 {name: {class, description, aliases, requires_llm}}
        """
        result: dict[str, dict[str, Any]] = {}
        for tool_name, tool_cls in TOOL_REGISTRY.items():
            meta = TOOL_METADATA.get(tool_name)
            result[tool_name] = {
                "class": tool_cls.__name__,
                "description": meta.description if meta else "",
                "aliases": meta.aliases if meta else [],
                "requires_llm": meta.requires_llm if meta else False,
            }
        return result
