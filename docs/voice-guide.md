# 语音助手使用指南

> JavasAgent 语音交互完整指南

---

## 前置条件

语音模块是可选的，不安装不影响核心功能。需要额外安装：

```bash
# 音频录制（二选一）
pip install pyaudio        # 首选，需先安装 PortAudio
pip install sounddevice    # 备选，开箱即用

# TTS（推荐安装）
pip install edge-tts       # 免费，微软语音

# STT（可选）
pip install faster-whisper  # 本地语音转文字

# 唤醒词（可选）
pip install pvporcupine    # Porcupine（精度最高）
```

不安装这些依赖时，语音模块会自动降级，不会崩溃。

---

## 启动语音模式

```bash
# 标准模式（需要唤醒词）
javas voice

# 免唤醒直接对话
javas voice --no-wake

# 连续对话模式（唤醒后不回到 IDLE）
javas voice --continuous

# 指定唤醒词
javas voice --keyword 贾维斯
javas voice -k jarvis

# 查看可用唤醒词
javas voice --list-keywords

# 调整 TTS 语速（-10 到 10）
javas voice --tts-rate 5
```

---

## 使用流程

### 标准模式

```
[等待] → 说唤醒词 → [听你说] → [思考] → [语音回复] → [等待]
```

1. Agent 处于 IDLE 状态，等待唤醒
2. 你说出唤醒词（如 "Jarvis"）
3. Agent 进入 LISTENING 状态，开始录音
4. 说完后自动检测静音，停止录音
5. Agent 进入 PROCESSING 状态，理解并处理
6. Agent 进入 SPEAKING 状态，语音回复
7. 回到 IDLE，等待下次唤醒

### 免唤醒模式

```
[听你说] → [思考] → [语音回复] → [听你说] → ...
```

启动后直接进入 LISTENING，无需唤醒词。适合安静环境。

### 连续对话模式

```
[唤醒] → [听你说] → [思考] → [回复] → [听你说] → ...（超时后回到等待）
```

唤醒后持续监听，直到超过 `continuous_timeout`（默认 30 秒）无输入才回到 IDLE。

### 退出

- 语音说"退出"或"再见"
- 按 `Ctrl+C`

---

## 唤醒词

### 内置唤醒词

Porcupine 内置唤醒词（如已安装 pvporcupine）：

| 唤醒词 | 说明 |
|--------|------|
| porcupine | 默认 |
| jarvis | 钢铁侠风格 |
| computer | 星际迷航风格 |
| alexa | Alexa 风格 |
| hey barista | 咖啡师 |
| grasshopper | 蚱蜢 |
| picovoice | Picovoice |
| terminator | 终结者 |
| bumblebee | 大黄蜂 |

### 自定义唤醒词

通过 [Porcupine Console](https://console.picovoice.ai/) 创建自定义唤醒词模型，下载后放入指定目录，在配置中指定路径。

### 三级降级策略

```
Porcupine（精度最高，需 AccessKey）
    ↓ 不可用
OpenWakeWord（开源方案，需 onnxruntime）
    ↓ 不可用
VAD 模拟（检测持续语音，非真正唤醒词）
```

缺少依赖时自动降级，不会报错。

---

## 高级配置

所有配置在 `config/default.yaml` → `voice` 节：

```yaml
voice:
  # 唤醒词配置
  wake_word:
    enabled: true
    keywords: ["porcupine"]
    sensitivity: 0.5          # 0-1，越高越灵敏（也越容易误触发）

  # 语音活动检测
  vad:
    engine: "silero"          # silero / webrtcvad / energy
    threshold: 0.5            # 语音检测阈值
    silence_timeout: 1.5      # 静音多久认为说完（秒）

  # 语音转文字
  stt:
    engine: "auto"            # auto / faster-whisper / cloud
    language: "zh-CN"         # 识别语言

  # 文字转语音
  tts:
    engine: "auto"            # auto / edge-tts / cloud
    voice: ""                 # 留空使用默认
    rate: 200                 # 语速（字符/分钟）
    volume: 1.0               # 音量 0-1

  # 管道配置
  pipeline:
    continuous_mode: false       # 默认是否连续模式
    continuous_timeout: 30.0     # 连续模式超时（秒）
    interruption_enabled: true   # 允许打断 Agent 回复
    greeting: "我在，请说。"     # 唤醒后问候语
    farewell: "再见。"           # 退出时告别语
```

### VAD 引擎选择

| 引擎 | 精度 | 依赖 | 推荐 |
|------|------|------|------|
| silero | 最高 | PyTorch（~2GB） | 本地高精度 |
| webrtcvad | 中等 | webrtcvad（轻量） | 平衡方案 |
| energy | 基础 | 无 | 兜底方案 |

### STT 引擎选择

| 引擎 | 说明 |
|------|------|
| auto | 自动选择（优先本地） |
| faster-whisper | 本地 whisper 模型，需安装 faster-whisper |
| cloud | 云端 API（需配置） |

---

## 状态提示

语音模式运行时会显示当前状态：

- 🎤 **正在听...** — LISTENING，等待/录制你的语音
- 🧠 **思考中...** — PROCESSING，Agent 正在处理
- 🔊 **回复中...** — SPEAKING，Agent 正在语音回复
- 等待中... — IDLE，等待唤醒
