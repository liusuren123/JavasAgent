# 技术栈说明

> JavasAgent 完整技术栈与依赖清单

---

## 核心依赖

| 库 | 版本 | 用途 | 必选 |
|------|------|------|------|
| pydantic | ≥2.0 | 数据模型与配置验证 | ✅ |
| loguru | ≥0.7 | 结构化日志 | ✅ |
| pyyaml | ≥6.0 | YAML 配置解析 | ✅ |
| httpx | ≥0.27 | HTTP 客户端（LLM API 调用） | ✅ |
| pyautogui | ≥0.9 | 跨平台鼠标键盘模拟 | ✅ |
| pillow | ≥10.0 | 图像处理（截图、OCR） | ✅ |
| chromadb | ≥0.4 | 向量数据库（长期记忆） | ✅ |
| openai | ≥1.0 | OpenAI API 客户端 | ✅ |
| zhipuai | ≥2.0 | 智谱 API 客户端 | ✅ |
| rich | ≥13.0 | 终端富文本渲染 | ✅ |
| click | ≥8.0 | CLI 命令框架 | ✅ |
| watchdog | ≥4.0 | 文件系统监控 | ✅ |
| psutil | ≥5.9 | 系统进程管理 | ✅ |

---

## 分层技术栈

### 语言层

- **Python 3.11+** — 类型提示、match/case、异步生成器等现代特性
- 包管理：hatchling（构建后端）

### LLM 层

| Provider | 模型 | 接入方式 |
|----------|------|----------|
| Ollama | qwen3.6（默认） | 本地 REST API `localhost:11434` |
| 智谱 | glm-4-plus | 云端 API |
| OpenAI | gpt-4o | 云端 API |

多模型可切换，配置在 `config/default.yaml` → `llm.providers`。

### 平台层

| 能力 | 技术方案 |
|------|----------|
| 鼠标控制 | pyautogui + 贝塞尔曲线拟人移动 |
| 键盘输入 | pyautogui + 拟人打字间隔 |
| 窗口管理 | Win32 API（Windows）/ AppleScript（macOS）/ xdotool（Linux） |
| 截图 | pyautogui.screenshot() + Pillow |
| 进程管理 | psutil |

### 感知层

| 能力 | 技术方案 |
|------|----------|
| 屏幕分析 | LLM 多模态（Ollama vision 模型） |
| OCR | 本地 OCR 引擎 |
| 目标定位 | TargetMatcher（元素匹配 + 缓存） |
| 上下文感知 | ContextEngine（窗口标题、进程名、时间） |

### 语音层

| 能力 | 技术方案 | 降级策略 |
|------|----------|----------|
| 唤醒词 | Porcupine → OpenWakeWord → VAD 模拟 | 三级自动降级 |
| VAD | Silero-VAD → WebRTC-VAD → 能量检测 | 三级自动降级 |
| STT | faster-whisper（本地）→ 云端 API | 可选 |
| TTS | edge-tts（免费）→ 云端 API | 可选 |
| 音频录制 | PyAudio → SoundDevice | 二级自动降级 |

### 记忆层

| 组件 | 技术方案 |
|------|----------|
| 短期记忆 | 内存列表（默认保留 50 条消息） |
| 长期记忆 | ChromaDB 向量数据库（本地持久化） |
| 技能注册 | SkillRegistry + JSON 文件 |
| 知识库 | KnowledgeBase + 向量检索 |

### 测试层

| 工具 | 版本 | 用途 |
|------|------|------|
| pytest | ≥8.0 | 测试框架 |
| pytest-asyncio | ≥0.23 | 异步测试支持 |
| pytest-cov | ≥5.0 | 覆盖率报告 |
| ruff | ≥0.4 | 代码检查 + 格式化 |
| mypy | ≥1.10 | 类型检查 |

---

## 可选依赖

语音模块需要额外安装（不安装不影响核心功能，会自动降级）：

```bash
# 音频录制
pip install pyaudio        # 首选，需要 PortAudio 库
pip install sounddevice    # 备选

# 唤醒词检测
pip install pvporcupine    # Porcupine（精度最高，需 AccessKey）
pip install openwakeword onnxruntime  # 开源方案

# VAD
pip install torch          # Silero-VAD 依赖（约 2GB）
pip install webrtcvad      # 轻量替代

# STT
pip install faster-whisper  # 本地语音转文字

# TTS
pip install edge-tts        # 免费 TTS
```

### Windows 特有

| 库 | 用途 |
|------|------|
| winotify | ≥1.1 | Windows 桌面通知 |

---

## 系统要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Windows 10+ | Windows 11 |
| Python | 3.11 | 3.12+ |
| 内存 | 4GB | 8GB+ |
| 本地 LLM | — | 16GB+ 内存 + Ollama |
| GPU | — | NVIDIA（本地 STT 加速） |
| 磁盘 | 500MB | 2GB+（含模型） |

macOS 和 Linux 可运行大部分功能，但平台适配层以 Windows 为主。
