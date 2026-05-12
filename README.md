# JavasAgent

> 像贾维斯一样的 AI 智能体，接管你的电脑。

JavasAgent 是一个桌面 AI Agent，能自主完成软件开发、办公自动化、创意工具操控、浏览器操作等任务。遇到不明确的决策点会主动询问人类，明确的命令则自动执行。

## ✨ 功能特性

| 模块 | 能力 | 说明 |
|------|------|------|
| 🖥️ 系统控制 | 文件管理、进程管理、窗口控制 | 基础能力，优先实现 |
| 💻 代码开发 | 代码生成、调试、测试、Git 操作 | 支持多种语言和框架 |
| 📄 办公自动化 | Word / Excel / PPT / 邮件 / 日程 | 覆盖日常办公场景 |
| 🎨 创意工具 | Photoshop / Premiere / After Effects | Adobe 系列脚本控制 |
| 🌐 浏览器控制 | 网页自动化、信息检索 | 内容抓取与操作 |
| 🎤 语音助手 | 唤醒词检测、语音对话、连续交互 | 三级降级，开箱即用 |
| 🔄 后台服务 | 托盘图标、全局热键、IPC 通信 | 后台常驻，随时调用 |

## 🚀 快速开始

```bash
# 克隆项目
git clone https://github.com/JavasAgent/JavasAgent.git
cd JavasAgent

# 安装（Windows 一键脚本）
.\scripts\install.ps1

# 或手动安装
python -m venv venv
.\venv\Scripts\activate          # Windows
pip install -e ".[dev]"

# 启动交互式对话
javas chat

# 执行单条命令
javas run "帮我创建一个 hello.py 文件"

# 语音模式
javas voice --no-wake
```

> 📖 完整安装指南见 [docs/getting-started.md](docs/getting-started.md)

## 📁 项目结构

```
JavasAgent/
├── src/
│   ├── main.py              # CLI 入口（click 命令组）
│   ├── agents/              # Agent 实现（BaseAgent 核心循环）
│   ├── core/                # 核心引擎
│   │   ├── planner.py       #   任务规划——意图拆解为步骤链
│   │   ├── executor.py      #   执行引擎——按步骤执行 + 重试
│   │   ├── decider.py       #   决策判断——问人还是自己做
│   │   ├── scheduler.py     #   任务调度——优先级队列 + 并发
│   │   ├── workflow_engine.py  # 工作流引擎
│   │   └── models.py        #   数据模型（TaskPlan / Step / ...）
│   ├── tools/               # 工具集（30+ 工具模块）
│   │   ├── system_control.py    # 系统控制
│   │   ├── code_dev.py          # 代码开发
│   │   ├── office_ops.py        # 办公操作
│   │   ├── browser_control.py   # 浏览器控制
│   │   ├── creative_tools.py    # 创意工具
│   │   ├── voice_ops.py         # 语音操作
│   │   └── ...                  # 更多工具
│   ├── perception/          # 视觉感知层
│   │   ├── vision_eye.py    #   视觉感知器（截图 + 目标定位）
│   │   ├── screen_analyzer.py   # 屏幕分析
│   │   ├── ocr_engine.py    #   OCR 引擎
│   │   └── context_engine.py    # 上下文感知
│   ├── platforms/           # 平台适配层
│   │   ├── base.py          #   平台抽象基类
│   │   ├── windows.py       #   Windows 适配
│   │   ├── human_hand.py    #   拟人手部模拟（贝塞尔曲线）
│   │   └── motor_controller.py  # 闭环控制器
│   ├── memory/              # 记忆系统
│   │   ├── short_term.py    #   短期记忆（对话上下文）
│   │   ├── long_term.py     #   长期记忆（ChromaDB 向量存储）
│   │   ├── knowledge.py     #   知识库
│   │   └── skill_registry.py    # 技能注册表
│   ├── voice/               # 语音模块
│   │   ├── pipeline.py      #   语音管道（状态机）
│   │   ├── wake_word.py     #   唤醒词检测（三级降级）
│   │   ├── vad.py           #   语音活动检测（三级降级）
│   │   └── audio_stream.py  #   麦克风音频流
│   ├── daemon/              # 后台常驻服务
│   │   ├── service.py       #   服务主类（生命周期管理）
│   │   ├── ipc_server.py    #   IPC 服务端（Named Pipe）
│   │   ├── ipc_client.py    #   IPC 客户端
│   │   ├── ipc_protocol.py  #   IPC 协议定义
│   │   ├── hotkey_manager.py#   全局热键管理
│   │   ├── tray_icon.py     #   系统托盘图标
│   │   ├── chat_window.py   #   对话悬浮窗
│   │   └── autostart.py     #   开机自启管理
│   └── utils/               # 工具函数
│       ├── config.py        #   配置管理（YAML + pydantic）
│       ├── llm_client.py    #   LLM 客户端（多 Provider）
│       └── logger.py        #   日志（loguru）
├── config/
│   └── default.yaml         # 默认配置
├── tests/                   # 测试代码
├── docs/                    # 项目文档
├── scripts/                 # 安装脚本
└── pyproject.toml           # 项目配置
```

## 🔄 后台常驻服务

JavasAgent 可以后台运行，通过全局热键和托盘图标随时调用，无需每次打开终端。

### 启动后台服务

```bash
# 前台启动（可看到日志输出）
javas service start

# 后台静默启动
javas service start --background

# 查询服务状态
javas service status

# 停止服务
javas service stop
```

### 开机自启

```bash
# 设置开机自动启动
javas service install

# 取消开机自启
javas service uninstall
```

### 全局热键

服务运行时，无论焦点在哪个应用，都可以用热键触发：

| 热键 | 功能 |
|------|------|
| `Ctrl+Alt+J` | 打开对话窗口 |
| `Ctrl+Alt+V` | 语音开关（启用/禁用） |
| `Ctrl+Alt+S` | 停止当前任务 |

> ⚠️ 热键需要**管理员权限**运行才能生效。如果没有管理员权限，热键将静默降级（不影响其他功能）。

### 托盘图标

服务启动后，系统托盘会出现 JavasAgent 图标：

| 颜色 | 状态 |
|------|------|
| 🟢 绿色 | 活跃 — 正常运行 |
| 🟡 黄色 | 处理中 — 正在执行任务 |
| 🔴 红色 | 出错 — 服务异常 |
| ⚪ 灰色 | 已暂停 |

右键托盘图标可打开菜单：**打开对话**、**语音开关**、**设置**、**退出**。

### IPC 通信

后台服务通过 **Named Pipe**（Windows 命名管道）与客户端通信，支持：

- `javas service status` — 查询运行状态
- `javas service stop` — 远程停止服务
- `javas chat` — 连接后台对话窗口

Named Pipe 名称默认为 `javasagent_pipe`，可在 `config/default.yaml` 中修改。

---

## 🏗️ 架构

核心循环：**感知 → 规划 → 决策 → 执行 → 反馈**

```
用户输入 → Planner（拆解步骤）→ Decider（是否问人）→ Executor（执行）→ 结果反馈
```

感知闭环：**VisionEye（看）→ MotorController（判断）→ HumanHand（动作）→ 验证**

详见 [docs/architecture.md](docs/architecture.md)

## 🔧 技术栈

| 领域 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| LLM | Ollama / 智谱 GLM / OpenAI GPT |
| 桌面操控 | pyautogui + Win32 API |
| 视觉感知 | OpenCV + OCR |
| 语音 | Porcupine + Silero VAD + faster-whisper + edge-tts |
| 向量记忆 | ChromaDB |
| 后台服务 | pystray + keyboard + Pillow |
| IPC 通信 | Named Pipe（win32）|
| CLI | click + rich |
| 测试 | pytest + pytest-asyncio |

详见 [docs/tech-stack.md](docs/tech-stack.md)

## 📖 文档

| 文档 | 说明 |
|------|------|
| [快速开始](docs/getting-started.md) | 环境搭建、安装、配置 |
| [使用指南](docs/user-guide.md) | CLI 命令、对话模式、工具使用 |
| [语音助手](docs/voice-guide.md) | 语音模式配置与使用 |
| [架构设计](docs/architecture.md) | 系统架构与模块设计 |
| [技术栈](docs/tech-stack.md) | 完整技术栈说明 |
| [API 参考](docs/api-reference.md) | 核心 API 签名 |
| [问题排查](docs/troubleshooting.md) | 常见问题与解决方案 |
| [贡献指南](docs/contributing.md) | 开发规范与 PR 流程 |

## 🛠️ 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -q

# 代码检查
ruff check src/
mypy src/
```

详见 [docs/contributing.md](docs/contributing.md)

## 📄 License

MIT
