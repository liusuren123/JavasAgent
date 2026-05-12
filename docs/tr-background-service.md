# JavasAgent 后台常驻服务 — 技术交底书与可行性报告

> 版本: 1.0 | 日期: 2026-05-12
> 作者: 程序员 | 状态: 待评审

---

## 一、需求背景

JavasAgent 目前是纯 CLI 工具——用户需要手动打开终端、输入命令才能使用。关掉终端，Agent 就停了。

**目标：** 安装后在 Windows 后台常驻运行，支持：
1. 开机自启动
2. 系统托盘图标（状态可视化）
3. 语音唤醒词后台持续监听
4. 热键呼出对话窗口
5. 后台任务持续执行

---

## 二、现状分析

### 2.1 已有能力

| 模块 | 状态 | 说明 |
|------|------|------|
| VoicePipeline | ✅ 已实现 | 唤醒词→VAD→STT→Agent→TTS 完整流程 |
| WakeWordDetector | ✅ 已实现 | Porcupine / OpenWakeWord / VAD 三级降级 |
| VoiceActivityDetector | ✅ 已实现 | Silero VAD + WebRTC VAD |
| AudioStream | ✅ 已实现 | PyAudio / sounddevice 麦克风流 |
| BaseAgent | ✅ 已实现 | 感知→规划→决策→执行循环 |
| CLI (main.py) | ✅ 已实现 | chat / run / voice / status 命令 |
| 配置系统 | ✅ 已实现 | YAML 配置 + 环境变量 |

### 2.2 缺失能力

| 缺什么 | 说明 |
|--------|------|
| 后台进程管理 | 没有守护进程机制，终端关了就死 |
| 系统托盘集成 | 没有托盘图标、没有右键菜单 |
| 开机自启 | 没有注册 Windows 启动项 |
| 热键全局钩子 | 没有全局快捷键（如 Ctrl+Alt+J） |
| IPC 通信 | CLI 命令和后台服务之间没有通信通道 |
| UI 窗口 | 没有 GUI 界面（只有终端） |

---

## 三、技术方案

### 3.1 整体架构

```
┌──────────────────────────────────────────────────┐
│              Windows 用户桌面                       │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐    │
│  │ 托盘图标  │  │ 对话窗口  │  │ 热键 Ctrl+J  │    │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘    │
│       │             │               │              │
│       └─────────────┼───────────────┘              │
│                     ↓                              │
│  ┌──────────────────────────────────────────────┐ │
│  │           JavasAgent Service                  │ │
│  │                                               │ │
│  │  ┌─────────────┐    ┌──────────────────┐     │ │
│  │  │ IPC Server   │    │ Voice Pipeline   │     │ │
│  │  │ (Named Pipe) │    │ (后台持续运行)     │     │ │
│  │  └──────┬───────┘    └────────┬─────────┘     │ │
│  │         │                     │                │ │
│  │         ↓                     ↓                │ │
│  │  ┌─────────────────────────────────────┐      │ │
│  │  │           Core Agent                 │      │ │
│  │  │  (BaseAgent + Memory + Tools)        │      │ │
│  │  └─────────────────────────────────────┘      │ │
│  └──────────────────────────────────────────────┘ │
│                     ↑                              │
│  ┌──────────────────┴─────────────────────────┐   │
│  │           javas CLI (客户端)                 │   │
│  │  javas chat   → 通过 IPC 发送到后台          │   │
│  │  javas status → 查询后台状态                 │   │
│  │  javas stop   → 停止后台服务                 │   │
│  └────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────┘
```

### 3.2 核心组件设计

#### 组件 1：JavasService（后台服务守护进程）

**职责：** 作为 Windows 后台进程持续运行，管理所有子系统。

**实现方式：** Python `multiprocessing` 或 `subprocess` 启动子进程，父进程作为守护进程。

**不用 Windows Service 的原因：**
- Windows Service 运行在 Session 0，无法访问用户桌面（无法截屏、操作鼠标键盘）
- 语音助手必须能看到和操作桌面
- 改用"用户级后台进程 + 开机自启"更合适

**实现方案：**
```python
# src/daemon/service.py
class JavasService:
    """后台服务主类。"""
    
    def __init__(self):
        self._agent = None          # BaseAgent 实例
        self._voice_pipeline = None # VoicePipeline 实例
        self._ipc_server = None     # IPC 通信服务端
        self._tray = None           # 系统托盘
        self._hotkey = None         # 全局热键
    
    async def start(self):
        """启动所有子系统。"""
        await self._init_agent()
        self._start_tray()         # 托盘图标（线程）
        self._start_hotkey()       # 全局热键（线程）
        self._start_ipc()          # IPC 服务器
        await self._start_voice()  # 语音管道（后台）
    
    async def stop(self):
        """优雅停止所有子系统。"""
        ...
```

#### 组件 2：系统托盘（TrayIcon）

**职责：** 托盘图标 + 右键菜单 + 状态切换。

**技术选型：`pystray`**

| 方案 | 优点 | 缺点 |
|------|------|------|
| **pystray** | 纯 Python，跨平台，轻量 | 依赖 Pillow |
| pywinauto tray | Windows 原生 | Windows only，API 复杂 |
| Win32 API 直接调 | 最原生 | 代码量大，维护难 |

**推荐 pystray** — 一个 pip install 就能用，30 行代码搞定托盘。

**右键菜单：**
```
🟢 JavasAgent
├── 📋 打开对话窗口        → 弹出 TUI 对话界面
├── 🎤 语音模式 开/关       → 切换语音监听
├── ⚙️ 设置               → 打开 config.yaml
├── 📊 状态               → 显示 Agent 状态
├── ─────────────
└── ❌ 退出               → 停止服务
```

**托盘图标状态：**
- 🟢 绿色：语音监听中
- 🟡 黄色：处理任务中
- 🔴 红色：未连接 LLM / 出错
- ⚪ 灰色：已暂停

#### 组件 3：全局热键（HotkeyManager）

**职责：** 注册系统级快捷键，无论焦点在哪个应用都能响应。

**技术选型：`keyboard` 库**

| 方案 | 优点 | 缺点 |
|------|------|------|
| **keyboard** | 全局钩子，简单易用 | 需要管理员权限（Windows） |
| pynput | 不需要管理员 | 某些场景全局钩子不稳定 |
| Win32 SetWindowsHookEx | 最原生 | 代码量大 |

**推荐 keyboard** — 全局热键最可靠的 Python 方案。

**默认热键：**
- `Ctrl + Alt + J` — 呼出对话窗口
- `Ctrl + Alt + V` — 切换语音模式
- `Ctrl + Alt + S` — 停止当前任务

**为什么需要管理员权限：**
Windows 的全局键盘钩子（`SetWindowsHookEx`）需要低级别访问。`keyboard` 库内部用的就是这个 API。这是 Windows 的安全限制，无法绕过。
- **替代方案：** 如果不想每次管理员启动，可以注册为 Windows 计划任务（以最高权限运行）

#### 组件 4：IPC 通信（Named Pipe）

**职责：** CLI 客户端和后台服务之间的通信通道。

**为什么需要 IPC：**
用户在终端输入 `javas chat` 时，不是启动新 Agent，而是连接到已经在后台运行的 Agent。这样才能共享记忆、上下文、语音状态。

**技术选型：Windows Named Pipes**

| 方案 | 优点 | 缺点 |
|------|------|------|
| **Named Pipe** | Windows 原生，快，支持双向 | Windows only |
| TCP Socket | 跨平台 | 需要端口，可能被防火墙拦 |
| Unix Socket | 简单 | Windows 支持差 |
| ZeroMQ | 高性能 | 重依赖 |

**推荐 Named Pipe** — JavasAgent 当前主要支持 Windows，Named Pipe 是最自然的 IPC 方式。未来支持 Linux/Mac 时切换到 Unix Socket。

**通信协议：JSON-RPC 2.0**

```json
// CLI → Service
{"jsonrpc": "2.0", "method": "chat", "params": {"text": "帮我写个脚本"}, "id": 1}
{"jsonrpc": "2.0", "method": "status", "params": {}, "id": 2}
{"jsonrpc": "2.0", "method": "stop", "params": {}, "id": 3}

// Service → CLI
{"jsonrpc": "2.0", "result": {"status": "ok", "response": "脚本已创建"}, "id": 1}
```

#### 组件 5：对话窗口（ChatWindow）

**职责：** 热键呼出的对话界面，替代终端。

**技术选型：`rich` TUI（终端 UI）或 `tkinter` GUI**

| 方案 | 优点 | 缺点 |
|------|------|------|
| **tkinter** | Python 内置，无需安装 | 界面丑 |
| rich + 新终端窗口 | 当前已用 rich | 需要启动新终端进程 |
| PyQt / PySide | 界面专业 | 太重（100MB+） |
| customtkinter | tkinter 的现代皮肤 | 额外依赖 |

**推荐方案：先做 tkinter 最小窗口，后续迭代升级。**

理由：
1. tkinter 是 Python 内置，零额外依赖
2. 只需要一个输入框 + 输出区域 + 发送按钮
3. 不需要花哨的 UI——语音助手主要靠语音交互，窗口是辅助

**tkinter 窗口设计：**
```
┌─────────────────────────────────┐
│ JavasAgent                 — □ ×│
├─────────────────────────────────┤
│ 🤖: 你好，我是 JavasAgent       │
│ 👤: 帮我写个 Python 脚本         │
│ 🤖: 好的，已创建 script.py      │
│                                  │
│                                  │
├─────────────────────────────────┤
│ [输入消息...              ] [发送]│
└─────────────────────────────────┘
```

#### 组件 6：开机自启（AutoStart）

**实现方式：Windows 注册表或启动文件夹**

```python
# 方案 A：注册表（推荐，更可靠）
# HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Run
# 值: "JavasAgent" = "pythonw.exe C:\path\to\service.pyw"

# 方案 B：启动文件夹（更简单）
# %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\javasagent.lnk
```

**推荐方案 A（注册表）** — 更可靠，不会被用户误删。

---

## 四、为什么这么做（技术决策理由）

### 4.1 为什么不直接用 Windows Service？

| | Windows Service | 用户进程 + 自启 |
|---|---|---|
| 桌面访问 | ❌ Session 0 隔离 | ✅ 用户桌面 |
| 截屏/鼠标 | ❌ 无法操作 | ✅ 完全控制 |
| 麦克风 | ❌ 无法录音 | ✅ 正常录音 |
| 安装复杂度 | 需要 sc.exe 注册 | 写注册表就行 |
| 权限 | SYSTEM 账户 | 用户账户 |

**结论：** JavasAgent 的核心价值是"接管电脑"，必须能操作桌面。Windows Service 做不到。

### 4.2 为什么用 Python 而不是 Electron / Tauri？

- JavasAgent 核心逻辑全在 Python（Agent、工具、记忆、感知）
- 加 Electron 就是多了一层壳，增加复杂度
- 托盘 + 热键 + 后台进程，Python 完全能做
- 如果未来需要更精美的 GUI，再用 Tauri 包一层 Web UI

### 4.3 为什么用 Named Pipe 而不是 TCP？

- Named Pipe 不需要端口，不会被防火墙拦截
- 同机器通信，Named Pipe 比 TCP 快
- 安全性更好（只有本地可以连接）
- 唯一缺点是 Windows only，但 JavasAgent 当前就是 Windows first

### 4.4 为什么先做 tkinter 而不是更好的 UI？

- 最小可用原则：先能弹出窗口、输入文字、看到回复
- tkinter 零依赖，不会增加安装负担
- 语音助手主要靠语音，窗口只是辅助
- 未来可以换成 Web UI（Tauri 嵌套 WebView）

---

## 五、可行性评估

### 5.1 技术可行性

| 组件 | 可行性 | 风险 | 备选 |
|------|--------|------|------|
| 后台进程 | ✅ 高 | 低 | subprocess + pythonw.exe |
| 系统托盘 pystray | ✅ 高 | 低 | Win32 API 直接调 |
| 全局热键 keyboard | ⚠️ 中 | 需管理员权限 | pynput（不需管理员但不够稳定） |
| Named Pipe IPC | ✅ 高 | 低 | TCP Socket |
| tkinter 对话窗口 | ✅ 高 | 极低 | — |
| 开机自启注册表 | ✅ 高 | 极低 | 启动文件夹 |
| 语音后台监听 | ⚠️ 中 | 需持续占用麦克风 | — |

### 5.2 性能评估

| 指标 | 预估值 | 说明 |
|------|--------|------|
| 后台内存占用 | ~80-120MB | Python 进程 + Agent + ChromaDB |
| CPU 空闲时 | < 1% | 语音监听用 Porcupine 约 1-2% |
| 启动时间 | ~3-5秒 | Agent 初始化 + LLM 连接 |
| 热键响应 | < 200ms | keyboard 库全局钩子 |
| IPC 延迟 | < 10ms | Named Pipe 本地通信 |

### 5.3 依赖分析

新增依赖（都是轻量的）：

| 库 | 大小 | 用途 | 必选 |
|---|---|---|---|
| pystray | ~50KB | 系统托盘 | 是 |
| keyboard | ~100KB | 全局热键 | 是 |
| pywin32 | 已安装 | Named Pipe | 是 |

**不引入重依赖** — tkinter 是 Python 内置，不需要额外安装。

---

## 六、安全考量

### 6.1 权限问题

- **keyboard 需要管理员权限** — 这是 Windows 限制，全局钩子必须管理员
- **解决方案：** 安装时通过计划任务注册为"以最高权限运行"，用户不需要手动管理员启动

### 6.2 麦克风权限

- Windows 10+ 要求应用声明麦克风权限
- Python 进程继承终端/启动器的权限
- 首次使用需要用户在 Windows 设置中允许

### 6.3 IPC 安全

- Named Pipe 只允许本地连接
- 可以加简单 token 认证（启动时生成随机 token，CLI 连接时带上）
- 防止其他进程冒充 CLI 发指令

---

## 七、与现有代码的关系

### 7.1 新建文件

```
src/daemon/
├── __init__.py
├── service.py          # JavasService 后台服务主类
├── tray_icon.py        # 系统托盘图标
├── hotkey_manager.py   # 全局热键管理
├── ipc_server.py       # Named Pipe 服务端
├── ipc_client.py       # Named Pipe 客户端（CLI 用）
├── chat_window.py      # tkinter 对话窗口
└── autostart.py        # 开机自启管理
```

### 7.2 修改文件

```
src/main.py             # CLI 命令增加 service 子命令
config/default.yaml     # 增加 daemon 配置节
```

### 7.3 不改动

```
src/voice/              # VoicePipeline 等不变，被 service.py 调用
src/agents/             # BaseAgent 不变
src/tools/              # 所有工具不变
src/core/               # 核心层不变
```

**原则：** 守护进程层是外壳，不动内核。

---

## 八、开发规模估算

| 组件 | 代码量 | 测试量 | 预计时间 |
|------|--------|--------|---------|
| service.py | ~300 行 | ~100 行 | 30 min |
| tray_icon.py | ~150 行 | ~50 行 | 20 min |
| hotkey_manager.py | ~120 行 | ~50 行 | 15 min |
| ipc_server.py | ~200 行 | ~80 行 | 25 min |
| ipc_client.py | ~100 行 | ~40 行 | 15 min |
| chat_window.py | ~200 行 | ~50 行 | 20 min |
| autostart.py | ~80 行 | ~40 行 | 10 min |
| main.py 改动 | ~50 行 | ~30 行 | 10 min |
| config 改动 | ~20 行 | — | 5 min |
| **合计** | **~1220 行** | **~440 行** | **~2.5 小时** |

---

## 九、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| keyboard 管理员权限用户不接受 | 中 | 热键不可用 | 备选 pynput；或提供计划任务方案 |
| pystray 在某些 Windows 版本崩溃 | 低 | 无托盘图标 | 降级到无托盘模式（后台进程仍在） |
| Named Pipe 端口冲突 | 极低 | IPC 失败 | 使用固定名称 `javasagent_pipe` |
| 后台进程被杀毒软件拦截 | 中 | 无法自启 | 白名单引导 |
| 麦克风权限未授予 | 中 | 语音不可用 | 首次启动引导用户授权 |

---

## 十、未来扩展

本次只做 Windows 后台常驻。未来可扩展：

1. **macOS 支持** — LaunchAgent + NSStatusBar + macOS Named Pipe
2. **Linux 支持** — systemd user service + AppIndicator + D-Bus
3. **Web UI** — Tauri + WebView 替代 tkinter
4. **移动端联动** — 手机 App 通过 WebSocket 连接后台服务
5. **多用户** — 每个用户一个服务实例
