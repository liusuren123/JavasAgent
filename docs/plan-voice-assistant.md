# JavasAgent 语音助手开发计划

> 版本: 1.0 | 日期: 2026-05-11
> 状态: 待执行
> 预计步骤: 5 步 | 每步约 1 个 cron 周期（10 分钟）

---

## 1. 目标

将 JavasAgent 从"文字指令驱动的自动化工具"升级为"语音唤醒的智能助手"，实现：

- **本地低延迟唤醒词检测**（< 300ms，CPU < 5%）
- **语音活动检测（VAD）**：自动判断用户何时说完
- **完整语音管道**：唤醒 → 录音 → STT → Agent → TTS → 打断支持
- **CLI 集成**：`javas voice` 命令启动语音模式

---

## 2. 现有代码分析

### 已有模块（无需重写，需扩展）

| 文件 | 类 | 现状 |
|------|-----|------|
| `src/tools/voice_stt.py` | VoiceSTT | Google SR + Whisper fallback，能用但延迟高 |
| `src/tools/voice_tts.py` | VoiceTTS | edge-tts + pyttsx3 fallback，功能完整 |
| `src/tools/voice_ops.py` | VoiceOps | STT/TTS 统一门面，execute() 模式 |
| `src/core/voice_chat.py` | VoiceChatLoop | 基础 STT→Agent→TTS 循环，缺少唤醒词/VAD/打断 |

### 缺失模块（需新建）

| 文件 | 类 | 职责 |
|------|-----|------|
| `src/voice/__init__.py` | — | voice 子包 |
| `src/voice/wake_word.py` | WakeWordDetector | 本地唤醒词检测，后台持续监听 |
| `src/voice/vad.py` | VoiceActivityDetector | 语音活动检测，判断说话/静音 |
| `src/voice/audio_stream.py` | AudioStream | 麦克风音频流管理（连续录音） |
| `src/voice/pipeline.py` | VoicePipeline | 完整语音管道，协调所有组件 |

---

## 3. 技术选型

### 唤醒词检测：Porcupine（Picovoice）

- 延迟 < 200ms，CPU 1-2%
- 免费个人使用（AccessKey 免费注册）
- 支持自定义唤醒词（Picovoice Console 在线训练）
- 内置唤醒词：porcupine、hey barista、grasshopper 等
- 备选：如果 Porcupine 注册麻烦，用 OpenWakeWord（开源，需 ONNX Runtime）

### VAD：Silero VAD

- 基于 PyTorch，模型仅 2MB
- 准确率高，延迟 < 50ms
- 输出：每帧语音概率（0.0 ~ 1.0）
- 备选：WebRTC VAD（更轻量，但准确率较低）

### STT：保留现有，新增 faster-whisper

- 优先：faster-whisper（本地 CTranslate2 加速，CPU 也可用）
- 备选：Google SR（在线，现有实现）
- 兜底：现有 Whisper 实现

### 音频流：PyAudio

- 跨平台麦克风录音
- 回调模式支持持续流式录音
- 备选：sounddevice（更现代但 PyAudio 生态更成熟）

---

## 4. 开发步骤

### Step 1：音频基础设施 + VAD

**新建文件：**
- `src/voice/__init__.py`
- `src/voice/audio_stream.py` — AudioStream 类
- `src/voice/vad.py` — VoiceActivityDetector 类

**AudioStream 设计：**
```python
class AudioStream:
    """麦克风音频流管理。"""
    
    def __init__(self, sample_rate=16000, channels=1, chunk_size=512):
        ...
    
    async def start(self, callback: Callable[[bytes], None]) -> None:
        """启动音频流，每个 chunk 调用 callback。"""
    
    async def stop(self) -> None:
        """停止音频流。"""
    
    async def record_until_silence(self, vad, max_duration=30.0, 
                                     silence_threshold=1.5) -> bytes:
        """录音直到静音，返回完整 WAV 数据。"""
```

**VoiceActivityDetector 设计：**
```python
class VoiceActivityDetector:
    """语音活动检测。"""
    
    def __init__(self, threshold=0.5, sample_rate=16000):
        ...
    
    def is_speech(self, audio_chunk: bytes) -> bool:
        """判断音频帧是否包含语音。"""
    
    def get_speech_probability(self, audio_chunk: bytes) -> float:
        """返回语音概率 0.0 ~ 1.0。"""
```

**测试文件：**
- `tests/voice/test_audio_stream.py`
- `tests/voice/test_vad.py`

**依赖安装：**
```bash
pip install pyaudio silero-vad torch
```

**提交信息：** `feat(voice): 音频流管理 + VAD 语音活动检测 - Step 1`

---

### Step 2：唤醒词检测器

**新建文件：**
- `src/voice/wake_word.py` — WakeWordDetector 类

**设计：**
```python
class WakeWordDetector:
    """本地唤醒词检测器。"""
    
    def __init__(self, keywords=None, access_key=None, sensitivity=0.5):
        """
        Args:
            keywords: 唤醒词列表，默认 ["porcupine"]（内置）
            access_key: Porcupine AccessKey（免费注册获取）
            sensitivity: 检测灵敏度 0.0 ~ 1.0
        """
    
    async def start_listening(self, callback: Callable[[], None],
                               audio_stream: AudioStream) -> None:
        """开始后台监听唤醒词，检测到时调用 callback。"""
    
    async def stop_listening(self) -> None:
        """停止监听。"""
    
    @staticmethod
    def list_builtin_keywords() -> list[str]:
        """列出内置可用唤醒词。"""
```

**备选实现（如果 Porcupine 不可用）：**
- 使用 OpenWakeWord + ONNX Runtime
- 或使用 Silero VAD + 关键词匹配（简单但精度较低）
- 代码中做 import 检测，优先 Porcupine，fallback 到 OpenWakeWord

**测试文件：**
- `tests/voice/test_wake_word.py`

**提交信息：** `feat(voice): 唤醒词检测器 - Step 2`

---

### Step 3：VoicePipeline 语音管道

**新建文件：**
- `src/voice/pipeline.py` — VoicePipeline 类

**设计：**
```python
class VoicePipeline:
    """完整语音管道：唤醒词 → VAD → STT → Agent → TTS。"""
    
    def __init__(self, agent, voice_ops, config=None):
        """
        Args:
            agent: BaseAgent 实例
            voice_ops: VoiceOps 实例
            config: VoicePipelineConfig
        """
    
    async def start(self) -> None:
        """启动语音管道（阻塞，持续运行）。"""
    
    async def stop(self) -> None:
        """停止语音管道。"""
    
    # 内部状态机：
    # IDLE → (唤醒词) → LISTENING → (VAD:说完) → PROCESSING → 
    # SPEAKING → (说完/被打断) → IDLE
    
    async def _state_idle(self) -> None:
        """等待唤醒词。"""
    
    async def _state_listening(self) -> None:
        """听取用户指令。"""
    
    async def _state_processing(self, text: str) -> str:
        """Agent 处理。"""
    
    async def _state_speaking(self, text: str) -> None:
        """TTS 朗读，支持打断。"""
```

**VoicePipelineConfig：**
```python
@dataclass
class VoicePipelineConfig:
    wake_words: list[str] = field(default_factory=lambda: ["porcupine"])
    wake_word_enabled: bool = True  # False = 免唤醒直接对话
    vad_threshold: float = 0.5
    silence_timeout: float = 1.5  # 静音多久认为说完
    max_listening_duration: float = 30.0  # 最长听多久
    continuous_mode: bool = False  # True = 唤醒后持续对话，False = 每次需唤醒
    continuous_timeout: float = 30.0  # 连续对话超时回到唤醒等待
    interruption_enabled: bool = True  # 支持打断
    stt_engine: str = "auto"  # auto / google / whisper / faster-whisper
    tts_engine: str = "auto"  # auto / edge-tts / pyttsx3
    greeting: str = "我在，请说。"
    farewell: str = "再见。"
```

**测试文件：**
- `tests/voice/test_pipeline.py`

**提交信息：** `feat(voice): 语音管道 - 唤醒词/VAD/STT/TTS 完整流程 - Step 3`

---

### Step 4：CLI 集成 + 配置

**修改文件：**
- `src/main.py` — 添加 `voice` 子命令
- `config/default.yaml` — 添加语音配置节

**CLI 命令：**
```bash
javas voice                    # 启动语音模式（需唤醒词）
javas voice --no-wake          # 免唤醒直接对话模式
javas voice --continuous       # 唤醒后持续对话
javas voice --keyword 贾维斯   # 指定唤醒词
javas voice --list-keywords    # 列出可用唤醒词
```

**config/default.yaml 新增节：**
```yaml
voice:
  wake_word:
    enabled: true
    keywords: ["porcupine"]
    sensitivity: 0.5
    # access_key: ""  # Porcupine 免费版 AccessKey
  
  vad:
    engine: "silero"
    threshold: 0.5
    silence_timeout: 1.5
  
  stt:
    engine: "auto"  # auto / google / whisper / faster-whisper
    language: "zh-CN"
  
  tts:
    engine: "auto"  # auto / edge-tts / pyttsx3
    voice: ""       # 留空自动选择
    rate: 200
    volume: 1.0
  
  pipeline:
    continuous_mode: false
    continuous_timeout: 30.0
    interruption_enabled: true
    greeting: "我在，请说。"
    farewell: "再见。"
```

**测试文件：**
- `tests/test_cli_voice.py`

**提交信息：** `feat(voice): CLI 集成 + 语音配置 - Step 4`

---

### Step 5：faster-whisper STT 后端 + 集成测试

**修改文件：**
- `src/tools/voice_stt.py` — 添加 faster-whisper 后端

**新增能力：**
```python
# 在 VoiceSTT 中新增
async def listen_with_vad(self, audio_stream, vad, timeout=30.0):
    """VAD 驱动的 STT：自动检测说话开始/结束，然后识别。"""
```

**faster-whisper 集成：**
```python
# VoiceSTT 新增 faster-whisper 引擎
try:
    from faster_whisper import WhisperModel
    _FASTER_WHISPER_AVAILABLE = True
except ImportError:
    _FASTER_WHISPER_AVAILABLE = False
```

**集成测试（mock + 真实）：**
- 测试 VoicePipeline 与 mock Agent 的完整流程
- 测试唤醒词 → 对话 → 退出流程
- 测试打断机制
- 测试连续对话模式

**依赖安装：**
```bash
pip install faster-whisper  # 可选，CPU 模式即可
```

**测试文件：**
- `tests/voice/test_integration.py`

**提交信息：** `feat(voice): faster-whisper STT + 集成测试 - Step 5`

---

## 5. 文件清单

### 新建文件（10 个）

```
src/voice/__init__.py              # 子包
src/voice/audio_stream.py          # 音频流管理
src/voice/vad.py                   # VAD 语音活动检测
src/voice/wake_word.py             # 唤醒词检测器
src/voice/pipeline.py              # 语音管道
tests/voice/__init__.py            # 测试子包
tests/voice/test_audio_stream.py   # 音频流测试
tests/voice/test_vad.py            # VAD 测试
tests/voice/test_wake_word.py      # 唤醒词测试
tests/voice/test_pipeline.py       # 管道测试
tests/voice/test_integration.py    # 集成测试
tests/test_cli_voice.py            # CLI 语音命令测试
```

### 修改文件（4 个）

```
src/tools/voice_stt.py             # 添加 faster-whisper + VAD 驱动 STT
src/main.py                        # 添加 voice 子命令
config/default.yaml                # 添加 voice 配置节
docs/ARCHITECTURE.md               # 更新架构图
```

### 依赖

```
# 必需
pyaudio            # 麦克风录音
silero-vad         # VAD（需要 torch）
torch              # silero-vad 依赖

# 可选（有则用，无则 fallback）
pvporcupine        # Porcupine 唤醒词（免费个人版）
faster-whisper     # 本地快速 STT
openwakeword       # 备选唤醒词检测
```

---

## 6. 验收标准

| 项目 | 标准 |
|------|------|
| 所有现有测试 | 1911 passed，0 新增失败 |
| 新增测试 | 每个 Step 的测试文件全部通过 |
| 文件大小 | 每个文件 < 20KB |
| 代码风格 | ruff check 通过 |
| 唤醒词延迟 | 本地检测 < 500ms |
| VAD 准确率 | 静音判断 > 95% |
| 打断支持 | Agent 说话时用户开口 → 0.5s 内停止 TTS |
| 依赖优雅降级 | 缺少可选依赖时功能降级但不崩溃 |

---

## 7. 风险与备选

| 风险 | 影响 | 备选 |
|------|------|------|
| Porcupine 需要 AccessKey | 无法使用自定义唤醒词 | 用 OpenWakeWord 或 silero-vad + 关键词匹配 |
| PyAudio 安装失败（Windows 编译） | 无法录音 | 用 sounddevice 替代 |
| torch 太大（silero-vad 依赖） | 安装慢，占空间 | 用 webrtcvad 替代（pip install webrtcvad） |
| faster-whisper 无 GPU | 识别慢 | 用 Google SR 在线模式 |
