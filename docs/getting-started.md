# 快速开始

> 从零搭建 JavasAgent 开发环境

---

## 环境要求

| 项目 | 要求 |
|------|------|
| Python | 3.11 或更高版本 |
| Git | 任意版本 |
| 操作系统 | Windows 10+（主要支持）/ macOS / Linux |

验证 Python 版本：

```bash
python --version
# Python 3.11.x 或更高
```

---

## 一键安装

### Windows

```powershell
git clone https://github.com/JavasAgent/JavasAgent.git
cd JavasAgent
.\scripts\install.ps1
```

### Linux / macOS

```bash
git clone https://github.com/JavasAgent/JavasAgent.git
cd JavasAgent
chmod +x scripts/install.sh
./scripts/install.sh
```

安装脚本会自动完成：
1. 检查 Python 版本
2. 创建虚拟环境
3. 安装核心依赖
4. 安装可选依赖（语音模块）
5. 复制配置模板
6. 验证安装

---

## 手动安装

```bash
# 1. 克隆项目
git clone https://github.com/JavasAgent/JavasAgent.git
cd JavasAgent

# 2. 创建虚拟环境
python -m venv venv

# 激活（Windows）
.\venv\Scripts\activate

# 激活（Linux/macOS）
source venv/bin/activate

# 3. 安装核心依赖
pip install -e .

# 4. 安装开发依赖（可选）
pip install -e ".[dev]"

# 5. 安装语音依赖（可选）
pip install pyaudio silero-vad pvporcupine edge-tts faster-whisper
```

---

## 配置

配置文件位于 `config/default.yaml`，首次使用可保持默认。

### LLM 配置

默认使用本地 Ollama，最省钱。也可以切换到云端 API：

#### 方案一：本地 Ollama（推荐）

```yaml
llm:
  default_provider: "ollama"
  providers:
    ollama:
      model: "qwen3.6"
      base_url: "http://localhost:11434/v1"
```

安装 Ollama 并拉取模型：

```bash
# 安装 Ollama（见 https://ollama.com）
ollama pull qwen3.6
```

#### 方案二：智谱 GLM

```yaml
llm:
  default_provider: "zhipuai"
  providers:
    zhipuai:
      model: "glm-4-plus"
      api_key_env: "ZHIPUAI_API_KEY"
```

设置环境变量：

```bash
# Windows
set ZHIPUAI_API_KEY=your_api_key

# Linux/macOS
export ZHIPUAI_API_KEY=your_api_key
```

#### 方案三：OpenAI GPT

```yaml
llm:
  default_provider: "openai"
  providers:
    openai:
      model: "gpt-4o"
      api_key_env: "OPENAI_API_KEY"
```

### 语音配置

默认即可使用，如需自定义见 `config/default.yaml` → `voice` 节。完整说明见 [voice-guide.md](voice-guide.md)。

---

## 验证安装

```bash
# 查看 Agent 状态
javas status

# 运行测试
pytest tests/ -q

# 测试对话
javas chat
```

如果 `javas status` 输出状态面板，说明安装成功。

---

## 下一步

- [使用指南](user-guide.md) — 了解所有 CLI 命令和工具
- [语音助手](voice-guide.md) — 配置语音交互
- [架构设计](architecture.md) — 了解系统设计
