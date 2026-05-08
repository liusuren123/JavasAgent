# JavasAgent - 系统架构设计文档

> 版本: 0.1.0 | 日期: 2026-05-09
> 状态: 初始设计阶段

---

## 1. 项目愿景

打造一个类似钢铁侠中"贾维斯(Jarvis)"的AI智能体系统，能够：

- **接管用户电脑**，自主完成各类任务
- **软件开发**：写代码、调试、测试、部署
- **办公自动化**：操作Office文档、处理邮件、日程管理
- **创意工具**：操作Photoshop、Premiere等Adobe软件
- **通用操作**：文件管理、浏览器操作、信息检索

### 核心原则

- 遇到**不明确的决策点** → 询问人类
- 人类命令**明确** → 自主执行
- **渐进式能力扩展**：从基础能力开始，逐步增加高级技能

---

## 2. 系统架构总览

```
┌─────────────────────────────────────────────────────┐
│                    用户交互层                         │
│  (CLI / GUI / 语音 / API)                           │
├─────────────────────────────────────────────────────┤
│                  Agent 编排引擎                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐     │
│  │ 任务规划  │ │ 执行调度  │ │ 决策判断         │     │
│  │ Planner  │ │ Executor │ │ Decider          │    │
│  └──────────┘ └──────────┘ └──────────────────┘     │
├─────────────────────────────────────────────────────┤
│                   记忆与知识层                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐     │
│  │ 短期记忆  │ │ 长期记忆  │ │ 知识库           │     │
│  │ (Context) │ │ (Vector) │ │ (Rules/Skills)   │    │
│  └──────────┘ └──────────┘ └──────────────────┘     │
├─────────────────────────────────────────────────────┤
│                   工具与能力层                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐     │
│  │ 系统控制  │ │ 软件操控  │ │ 代码开发工具集    │    │
│  │ (OS)     │ │ (App)    │ │ (Dev Tools)      │     │
│  └──────────┘ └──────────┘ └──────────────────┘     │
├─────────────────────────────────────────────────────┤
│                   平台适配层                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐     │
│  │  Windows  │ │   macOS  │ │    Linux         │     │
│  └──────────┘ └──────────┘ └──────────────────┘     │
└─────────────────────────────────────────────────────┘
```

---

## 3. 模块详细设计

### 3.1 Agent 编排引擎 (`src/core/`)

| 组件 | 职责 | 文件 |
|------|------|------|
| **Planner** | 解析用户意图，拆解任务为步骤链 | `planner.py` |
| **Executor** | 按步骤执行，管理执行状态 | `executor.py` |
| **Reflector** | 定期反思审查，保证质量与目标对齐 | `reflector.py` |
| **Decider** | 决策点判断——问人还是自己做 | `decider.py` |
| **Scheduler** | 任务队列管理与调度 | `scheduler.py` |

### 3.2 工具与能力层 (`src/tools/`)

| 工具集 | 能力 | 说明 |
|--------|------|------|
| **SystemControl** | 文件操作、进程管理、窗口控制 | 基础能力，优先实现 |
| **CodeDev** | 代码生成、调试、测试、Git操作 | 软件开发能力 |
| **OfficeOps** | Word/Excel/PPT/邮件操作 | 办公自动化 |
| **CreativeTools** | PS/PR/AE 等 Adobe 系列操控 | 创意工具 |
| **BrowserControl** | 网页自动化、信息检索 | 浏览器操控 |

### 3.3 记忆与知识层 (`src/memory/`)

| 组件 | 职责 |
|------|------|
| **ShortTermMemory** | 当前对话上下文、任务执行状态 |
| **LongTermMemory** | 向量数据库存储的历史经验与知识 |
| **SkillRegistry** | 已注册的技能/工具清单及其使用说明 |
| **KnowledgeBase** | 规则、偏好、项目知识 |

### 3.4 平台适配层 (`src/platforms/`)

| 平台 | 控制方式 |
|------|----------|
| **Windows** | pyautogui + Win32 API + COM 接口 |
| **macOS** | AppleScript + pyautogui + Accessibility API |
| **Linux** | xdotool + DBus + pyautogui |

---

## 4. 技术选型

| 领域 | 技术方案 | 理由 |
|------|----------|------|
| 语言 | Python 3.11+ | AI 生态最成熟，适合自动开发 |
| LLM 接入 | OpenAI API / 智谱 API | 多模型可切换 |
| GUI 控制 | pyautogui + platform API | 跨平台桌面操控 |
| 向量存储 | ChromaDB | 轻量级本地向量数据库 |
| 任务队列 | 内置 asyncio + 优先级队列 | 无外部依赖 |
| 配置管理 | YAML + pydantic | 人类可读 + 类型安全 |
| 测试框架 | pytest | Python 标准选择 |
| 日志 | loguru | 开箱即用，结构化日志 |
| 包管理 | uv / pip | 现代 Python 包管理 |

---

## 5. 开发阶段规划

### Phase 1: 基础骨架 (当前)
- [ ] 项目结构搭建
- [ ] Agent 核心循环（感知→规划→执行→反思）
- [ ] 基础 CLI 交互
- [ ] LLM 接入层
- [ ] 简单任务执行（文件操作级别）

### Phase 2: 桌面操控
- [ ] 屏幕截图与识别
- [ ] 鼠标键盘模拟
- [ ] 窗口管理
- [ ] 基础 GUI 操作

### Phase 3: 开发能力
- [ ] 代码生成与编辑
- [ ] 终端操作
- [ ] Git 工作流
- [ ] 调试与测试

### Phase 4: 办公自动化
- [ ] Office 文档操作
- [ ] 邮件处理
- [ ] 浏览器自动化

### Phase 5: 创意工具
- [ ] Photoshop 脚本控制
- [ ] Premiere 自动剪辑
- [ ] 其他 Adobe 工具

### Phase 6: 高级能力
- [ ] 语音交互
- [ ] 多 Agent 协作
- [ ] 自我学习与技能扩展

---

## 6. 文件结构规范

```
JavasAgent/
├── docs/                    # 项目文档
│   ├── ARCHITECTURE.md      # 架构设计（本文件）
│   ├── ROADMAP.md           # 开发路线图
│   └── CONTRIBUTING.md      # 贡献指南
├── specs/                   # OpenSpec 规范文件
│   └── *.spec.md            # 每个功能模块的规格说明
├── src/
│   ├── __init__.py
│   ├── main.py              # 入口
│   ├── core/                # 核心引擎
│   │   ├── __init__.py
│   │   ├── planner.py       # 任务规划
│   │   ├── executor.py      # 执行引擎
│   │   ├── reflector.py     # 反思审查
│   │   ├── decider.py       # 决策判断
│   │   └── scheduler.py     # 任务调度
│   ├── agents/              # Agent 实现
│   │   ├── __init__.py
│   │   └── base_agent.py    # 基础 Agent 类
│   ├── tools/               # 工具集
│   │   ├── __init__.py
│   │   ├── system_control.py
│   │   ├── code_dev.py
│   │   ├── office_ops.py
│   │   ├── creative_tools.py
│   │   └── browser_control.py
│   ├── memory/              # 记忆系统
│   │   ├── __init__.py
│   │   ├── short_term.py
│   │   ├── long_term.py
│   │   └── knowledge.py
│   ├── platforms/            # 平台适配
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── windows.py
│   │   ├── macos.py
│   │   └── linux.py
│   └── utils/                # 工具函数
│       ├── __init__.py
│       ├── config.py
│       ├── logger.py
│       └── llm_client.py
├── tests/                    # 测试代码（与业务隔离）
│   ├── __init__.py
│   ├── conftest.py
│   ├── core/
│   ├── agents/
│   ├── tools/
│   ├── platforms/
│   └── memory/
├── config/                   # 配置文件
│   ├── default.yaml          # 默认配置
│   └── development.yaml      # 开发环境配置
├── pyproject.toml            # 项目配置
├── README.md
├── LICENSE
└── .gitignore
```

**约束：** 每个文件不超过 20KB，超过则拆分。
