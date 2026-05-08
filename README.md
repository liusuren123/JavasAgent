# JavasAgent

> 像贾维斯一样的AI智能体，可以帮助用户做人类可以做的事情。
> 遇到不明确的决策点会咨询人类，明确的命令则自动执行。

## 项目目标

打造一个能接管电脑的 AI 智能体，能力覆盖：

- 🖥️ **软件开发** — 写代码、调试、测试、部署
- 📄 **办公自动化** — 操作 Office 文档、处理邮件、日程管理
- 🎨 **创意工具** — 操作 Photoshop、Premiere 等 Adobe 软件
- 🌐 **通用操作** — 文件管理、浏览器操作、信息检索

## 技术栈

- **语言**: Python 3.11+
- **LLM**: 智谱 GLM / OpenAI GPT（多模型可切换）
- **桌面操控**: pyautogui + 平台原生 API
- **向量记忆**: ChromaDB
- **测试**: pytest + pytest-asyncio

## 快速开始

```bash
# 安装依赖
pip install -e ".[dev]"

# 启动交互式对话
javas chat

# 执行单条命令
javas run "帮我创建一个 hello.py 文件"

# 查看状态
javas status
```

## 项目结构

```
JavasAgent/
├── docs/           # 项目文档
├── specs/          # OpenSpec 规范文件
├── src/
│   ├── core/       # 核心引擎（规划、执行、决策、调度）
│   ├── agents/     # Agent 实现
│   ├── tools/      # 工具集（系统控制、代码开发等）
│   ├── memory/     # 记忆系统（短期/长期/知识库）
│   ├── platforms/  # 平台适配（Windows/macOS/Linux）
│   └── utils/      # 工具函数（配置、日志、LLM客户端）
├── tests/          # 测试代码（与业务代码隔离）
├── config/         # 配置文件
└── pyproject.toml
```

## 架构设计

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

核心循环：**感知 → 规划 → 决策 → 执行 → 反馈**

```
用户输入 → Planner(拆解步骤) → Decider(是否问人) → Executor(执行) → 结果反馈
```

## 开发规范

- 每个文件不超过 **20KB**，超过则拆分
- 业务代码与测试代码严格隔离
- 使用 **OpenSpec** 规范驱动开发（见 `specs/` 目录）
- 遵循 `pyproject.toml` 中的 ruff 和 mypy 配置

## License

MIT
