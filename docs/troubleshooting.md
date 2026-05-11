# 常见问题排查

> JavasAgent 使用中常见问题的解决方案

---

## 安装问题

### pip install 失败

**症状**：`pip install -e .` 报错

**排查**：

```bash
# 1. 确认 Python 版本 >= 3.11
python --version

# 2. 确认在虚拟环境中
which python   # Linux/macOS
where python   # Windows

# 3. 升级 pip
pip install --upgrade pip

# 4. 清除缓存重试
pip install -e . --no-cache-dir
```

### PyAudio 编译失败

**症状**：`pip install pyaudio` 报编译错误

**解决方案**：

```bash
# 方案一：使用 SoundDevice 替代
pip install sounddevice

# 方案二（Windows）：安装预编译 wheel
pip install pipwin
pipwin install pyaudio

# 方案二（Ubuntu）：先装系统依赖
sudo apt-get install portaudio19-dev
pip install pyaudio

# 方案二（macOS）：用 Homebrew
brew install portaudio
pip install pyaudio
```

JavasAgent 会自动降级到 SoundDevice，不影响使用。

### torch 安装包太大

**症状**：安装 Silero VAD 时 PyTorch 太大

**解决方案**：

```bash
# 方案一：安装 CPU 版本（小很多）
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 方案二：使用 WebRTC VAD 替代（轻量）
pip install webrtcvad
```

VAD 模块会自动降级，不影响核心功能。

### ChromaDB 版本冲突

**症状**：`import chromadb` 报错或 PyJWT 版本冲突

**解决方案**：

```bash
pip install chromadb --upgrade
# 如果 PyJWT 冲突
pip install PyJWT==2.8.0
```

---

## 运行时问题

### LLM 连接失败

**症状**：`Connection refused` 或 `API Key 错误`

**Ollama 未启动**：

```bash
# 检查 Ollama 是否运行
curl http://localhost:11434/api/tags

# 启动 Ollama
ollama serve
```

**API Key 错误（智谱/OpenAI）**：

```bash
# 检查环境变量
echo $OPENAI_API_KEY      # Linux/macOS
echo %ZHIPUAI_API_KEY%    # Windows CMD
$env:ZHIPUAI_API_KEY      # Windows PowerShell

# 设置环境变量
export OPENAI_API_KEY=sk-xxx        # Linux/macOS
$env:OPENAI_API_KEY = "sk-xxx"     # Windows PowerShell
```

### 鼠标键盘操作无反应

**可能原因**：

1. **远程桌面（RDP）**：RDP 会话最小化后 pyautogui 无法操作
   - 保持远程桌面窗口可见
   - 或使用 VNC 替代

2. **权限不足**（macOS/Linux）：
   - macOS：系统偏好设置 → 安全性与隐私 → 辅助功能 → 添加终端
   - Linux：检查 X11 权限

3. **操作延迟太短**：调大 `config/default.yaml` → `platform.action_delay`

### 截屏黑屏

**症状**：截图是全黑的

**原因**：远程桌面或虚拟显示器问题

**解决方案**：
- 确保显示器处于活动状态
- 远程桌面窗口不要最小化
- Windows：使用 "瘦客户端" 模式或物理显示器

### 中文输入失败

**症状**：pyautogui 输入中文失败

**解决方案**：

Agent 内部使用剪贴板方式输入中文（`pyautogui.hotkey('ctrl', 'v')`），如果仍有问题：
- 检查剪贴板工具是否正常
- 确认输入法切换到中文模式

---

## 语音问题

### 麦克风无反应

**排查**：

```bash
# 测试麦克风
python -c "import sounddevice as sd; print(sd.query_devices())"

# 检查默认输入设备
python -c "import sounddevice as sd; print(sd.default.device)"
```

**常见原因**：
- 麦克风被其他程序占用
- 麦克风权限未授予（macOS 系统偏好设置 → 安全性与隐私 → 麦克风）
- 设备被禁用

### Porcupine AccessKey

Porcupine 免费版需要 AccessKey：

1. 注册 [Picovoice Console](https://console.picovoice.ai/)
2. 获取免费 AccessKey（每月有限额）
3. 不想注册？Agent 会自动降级到 VAD 模拟模式

### Silero VAD 模型下载失败

**症状**：首次运行时下载模型超时

**解决方案**：

```bash
# 手动下载模型
python -c "import torch; torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)"

# 或使用 WebRTC VAD
pip install webrtcvad
# Agent 自动降级
```

### 延迟过高

**优化建议**：

1. 使用本地 STT（faster-whisper）替代云端
2. 减小 VAD `silence_timeout`（默认 1.5 秒，可降到 1.0）
3. 使用本地 LLM（Ollama）减少网络延迟
4. 使用 GPU 加速（如果有）

---

## 测试问题

### pytest 部分测试失败

```bash
# 只跑单元测试（跳过慢测试和集成测试）
pytest tests/ -q -m "not slow and not integration"

# 查看详细输出
pytest tests/ -v

# 指定模块
pytest tests/core/ -q
```

### ChromaDB 兼容性

```bash
# ChromaDB 数据损坏时，删除重建
rm -rf ./data/memory/chroma
# 重启 Agent 会自动重建
```

---

## 诊断命令

```bash
# Agent 状态总览
javas status

# 检查模块可导入
python -c "import src; print(src.__file__)"

# 检查各模块
python -c "from src.voice.pipeline import VoicePipeline; print('voice OK')"
python -c "from src.perception.vision_eye import VisionEye; print('vision OK')"
python -c "from src.memory.long_term import LongTermMemory; print('memory OK')"

# 运行完整测试
pytest tests/ -q
```
