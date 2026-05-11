# JavasAgent 文档体系完善计划

> 版本: 1.0 | 日期: 2026-05-11
> 状态: 待执行

---

## 1. 现状

docs/ 目录只有 2 个文件：
- `architecture.md` — 系统架构（偏高层设计，缺少详细设计）
- `plan-voice-assistant.md` — 语音助手开发计划（临时文件，不属于正式文档）

README.md 存在但内容简陋，且 Windows 终端编码导致中文乱码。

---

## 2. 目标文档体系

```
docs/
├── architecture.md          # [更新] 系统架构设计文档（补充详细设计）
├── tech-stack.md            # [新建] 技术栈说明
├── getting-started.md       # [新建] 快速开始（构建、安装、配置）
├── user-guide.md            # [新建] 使用说明书
├── voice-guide.md           # [新建] 语音助手使用指南
├── troubleshooting.md       # [新建] 常见问题排查
├── contributing.md          # [新建] 贡献指南（开发规范）
└── api-reference.md         # [新建] API 参考文档

scripts/
├── install.ps1              # [新建] Windows 一键安装脚本
└── install.sh               # [新建] Linux/Mac 一键安装脚本

README.md                    # [重写] 项目首页（修复中文乱码）
```

---

## 3. 各文档内容大纲

### 3.1 README.md（重写）

```
# JavasAgent

一句话介绍 + 项目愿景

## 功能特性（6 大模块概览）
## 快速开始（3 步上手）
## 项目结构（树形图）
## 文档导航（链接到 docs/ 各文档）
## 技术栈（简表）
## 开发（简要）
## License
```

### 3.2 docs/tech-stack.md（新建）

```
# 技术栈说明

## 核心依赖
| 库 | 版本 | 用途 | 必选/可选 |

## 分层技术栈
- 语言层：Python 3.11+
- LLM 层：Ollama / 智谱 / OpenAI
- 平台层：pyautogui + Win32 API
- 感知层：OpenCV + GroundingDINO + OCR
- 语音层：Porcupine + Silero VAD + faster-whisper + edge-tts
- 记忆层：ChromaDB
- 测试层：pytest + pytest-asyncio

## 可选依赖
| 库 | 功能 | 安装命令 |

## 系统要求
- OS: Windows 10+（主要支持）/ macOS / Linux
- Python: 3.11+
- 内存: 8GB+（本地 LLM 需 16GB+）
- GPU: 可选（本地 STT 加速）
```

### 3.3 docs/getting-started.md（新建）

```
# 快速开始

## 环境要求
- Python 3.11+
- Git
- （可选）Ollama 运行本地 LLM

## 一键安装
  scripts/install.ps1（Windows）
  scripts/install.sh（Linux/Mac）

## 手动安装
  git clone ...
  python -m venv venv
  pip install -e ".[dev]"

## 配置
  config/default.yaml 说明
  LLM 配置（Ollama / 智谱 / OpenAI）
  语音模块配置

## 验证安装
  javas status
  python -m pytest tests/ -q

## Docker 安装（可选，未来支持）
```

### 3.4 docs/user-guide.md（新建）

```
# 使用说明书

## CLI 命令
  javas chat          # 对话模式
  javas run "任务"     # 单次执行
  javas voice          # 语音模式
  javas status         # 状态查看

## 对话模式详解
  多轮对话、上下文记忆、退出

## 任务执行模式
  任务语法、参数、示例

## 语音助手模式
  唤醒词、连续对话、打断（详见 voice-guide.md）

## 工具使用
  系统控制、文件操作、代码开发、办公自动化、
  浏览器控制、邮件、日程、创意工具、语音

## 配置调优
  常用配置项说明和推荐值
```

### 3.5 docs/voice-guide.md（新建）

```
# 语音助手使用指南

## 前置条件
  pip install pyaudio silero-vad pvporcupine

## 启动语音模式
  javas voice
  javas voice --no-wake       # 免唤醒
  javas voice --continuous    # 连续对话

## 唤醒词配置
  内置唤醒词列表
  自定义唤醒词（Porcupine Console）

## 使用流程
  唤醒 → 说话 → Agent 回复 → 继续/等待

## 高级配置
  config/default.yaml voice 节说明
  STT 引擎选择
  TTS 语音选择
  灵敏度调节

## 常见问题
  麦克风无反应
  识别不准确
  延迟过高
```

### 3.6 docs/troubleshooting.md（新建）

```
# 常见问题排查

## 安装问题
  pip install 失败
  PyAudio 编译失败 → 用 sounddevice 替代
  torch 安装包太大 → 用 webrtcvad 替代
  PyJWT 版本冲突

## 运行时问题
  LLM 连接失败（Ollama 未启动 / API Key 错误）
  鼠标键盘操作无反应（权限/远程桌面）
  中文输入失败
  截屏黑屏（远程桌面/虚拟显示器）
  ChromaDB 初始化失败

## 语音问题
  麦克风权限
  Porcupine AccessKey 获取
  silero-vad 模型下载失败

## 测试问题
  pytest 部分测试失败
  ChromaDB 兼容性

## 诊断命令
  javas status
  python -c "import src; print(src.__file__)"
```

### 3.7 docs/contributing.md（新建）

```
# 贡献指南

## 开发环境搭建
## 代码规范
  ruff + mypy
  每个文件 < 20KB
  业务代码与测试分离

## Git 规范
  commit message 格式
  分支策略

## 测试规范
  pytest 目录结构
  测试命名规范
  mock vs 真实测试

## PR 流程
## 发布流程
```

### 3.8 docs/api-reference.md（新建）

```
# API 参考文档

## 核心层 API
  BaseAgent.process()
  Planner.plan()
  Executor.execute()
  Decider.decide()
  Scheduler.schedule()

## 平台层 API
  WindowsPlatform 截屏/鼠标/键盘/窗口

## 语音层 API
  VoicePipeline.start()
  WakeWordDetector
  VoiceActivityDetector
  AudioStream

## 工具层 API
  各工具 execute() 方法签名和参数

## 配置参考
  config/default.yaml 完整字段说明
```

### 3.9 docs/architecture.md（更新）

补充内容：
- 语音管道架构图
- 感知闭环架构（VisionEye + MotorController + HumanHand）
- 模块依赖关系图
- 数据流图

---

## 4. 安装脚本

### 4.1 scripts/install.ps1

```powershell
# Windows 一键安装脚本
# 1. 检查 Python 版本
# 2. 创建 venv
# 3. 安装依赖
# 4. 安装可选依赖（语音等）
# 5. 复制配置模板
# 6. 验证安装
```

### 4.2 scripts/install.sh

```bash
# Linux/Mac 一键安装脚本
# 同上
```

---

## 5. 执行步骤

| Step | 文件 | 说明 |
|------|------|------|
| 1 | README.md | 重写项目首页，修复中文乱码 |
| 2 | docs/tech-stack.md | 技术栈说明 |
| 3 | docs/getting-started.md + scripts/install.ps1 + scripts/install.sh | 快速开始 + 安装脚本 |
| 4 | docs/user-guide.md | 使用说明书 |
| 5 | docs/voice-guide.md + docs/troubleshooting.md | 语音指南 + 问题排查 |
| 6 | docs/contributing.md + docs/api-reference.md + 更新 architecture.md | 贡献指南 + API 参考 + 架构更新 |

每步 commit: `docs: 描述`
