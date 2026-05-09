"""核心引擎包。"""

# 从拆分后的模块统一导出，保持公共 API 不变
from src.core.agent_team import (  # noqa: F401
    AgentInfo,
    AgentStatus,
    AgentTeam,
    CollaborationBus,
    MessagePriority,
    TaskAssignment,
    TaskDistributor,
    TeamMessage,
)
