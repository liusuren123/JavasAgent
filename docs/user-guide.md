# 使用指南

> JavasAgent 完整使用说明书

---

## CLI 命令一览

JavasAgent 通过 `javas` 命令行工具交互。所有命令：

```bash
javas chat          # 交互式对话模式
javas run "任务"     # 单次执行任务
javas voice          # 语音助手模式
javas status         # 查看 Agent 状态
javas history        # 查看任务执行历史
javas memory "查询"  # 检索长期记忆
javas remember "内容" # 存入长期记忆
javas team           # 查看多 Agent 团队状态
javas service start  # 启动后台服务
javas service stop   # 停止后台服务
javas service status # 查询后台服务状态
javas service install   # 设置开机自启
javas service uninstall # 取消开机自启
javas --version      # 查看版本
javas --help         # 查看帮助
```

---

## 对话模式（chat）

最常用的交互方式，支持多轮对话和上下文记忆。

```bash
javas chat
```

进入后：

```
🤖 Welcome
 JavasAgent v0.1.0
 像贾维斯一样的AI智能体
 输入 exit 或 quit 退出

你 > 帮我创建一个 hello.py
Javas > 已创建 hello.py，内容为 print("Hello, World!")

你 > 再加一个 say_hello 函数
Javas > 已在 hello.py 中添加 say_hello 函数

你 > 运行测试
Javas > ...

你 > exit
再见，老板。
```

- **退出**：输入 `exit`、`quit` 或 `q`，或按 `Ctrl+C`
- **上下文**：对话历史保存在短期记忆中（默认 50 条），Agent 理解上下文
- **决策**：Agent 遇到不明确的地方会主动询问，涉及高风险操作也会确认

---

## 单次执行模式（run）

适合脚本调用和一次性任务。

```bash
# 创建文件
javas run "帮我创建一个 hello.py"

# 搜索信息
javas run "搜索 Python 最新版本"

# 系统操作
javas run "查看当前目录下的文件"
```

执行完毕后自动退出，结果直接输出到终端。

---

## 语音助手模式（voice）

完整的语音交互体验。详见 [voice-guide.md](voice-guide.md)。

```bash
# 标准语音模式（需唤醒词）
javas voice

# 免唤醒直接对话
javas voice --no-wake

# 连续对话模式
javas voice --continuous

# 指定唤醒词
javas voice --keyword 贾维斯

# 查看可用唤醒词
javas voice --list-keywords
```

---

## 任务执行历史（history）

查看已提交的任务记录：

```bash
# 最近 10 条（默认）
javas history

# 最近 20 条
javas history --limit 20

# 简写
javas history -n 20
```

输出表格包含：任务 ID、意图、状态（排队/运行/完成/失败）、提交时间。

---

## 记忆管理

### 检索长期记忆

```bash
javas memory "Python 最佳实践" -k 5
```

返回相关记忆条目，包含 ID、分类、内容和相关度。

### 存入长期记忆

```bash
# 默认分类：experience
javas remember "用户偏好深色主题"

# 指定分类
javas remember "React Hooks 用法" --category knowledge
javas remember "每周一上午开会" --category preference
javas remember "如何部署到服务器" --category skill
```

分类选项：`experience` / `knowledge` / `preference` / `skill`

---

## 多 Agent 团队（team）

启用多 Agent 协作模式后，可查看团队状态：

```bash
javas team
```

输出包含：
- 团队名称
- 各 Agent ID、角色、状态（idle/busy/offline）、能力列表
- 成员数和已委派任务数

在 `config/default.yaml` 中设置 `team.enabled=true` 启用。

---

## 工具使用

Agent 根据任务自动选择工具，无需手动调用。以下是可用工具分类：

### 系统控制

| 工具 | 能力 |
|------|------|
| SystemControl | 文件/文件夹操作、进程管理 |
| ProcessManager | 启动/停止/查询进程 |
| ClipboardOps | 剪贴板读写 |
| NetworkOps | 网络请求、文件下载 |
| ArchiveOps | 压缩/解压文件 |

### 代码开发

| 工具 | 能力 |
|------|------|
| CodeDev | 代码生成、编辑、调试 |
| 完整支持 | Git 工作流、运行测试 |

### 办公自动化

| 工具 | 能力 |
|------|------|
| OfficeOps | Word/Excel/PPT/PDF 操作 |
| EmailOps | 邮件收发（IMAP + SMTP） |
| CalendarOps | 日程管理 |

### 浏览器控制

| 工具 | 能力 |
|------|------|
| BrowserControl | 网页自动化操作 |
| BrowserSession | 浏览器会话管理 |
| BrowserContent | 网页内容提取 |

### 创意工具

| 工具 | 能力 |
|------|------|
| CreativeTools | 创意类操作入口 |
| PhotoshopControl | Photoshop 脚本控制 |
| PremiereControl | Premiere 自动剪辑 |
| AfterEffectsControl | After Effects 脚本控制 |
| ImageOps | 图像处理（滤镜、水印、格式转换） |

### 语音操作

| 工具 | 能力 |
|------|------|
| VoiceOps | 语音操作入口 |
| VoiceSTT | 语音转文字 |
| VoiceTTS | 文字转语音 |

### 自动化

| 工具 | 能力 |
|------|------|
| AutomationEngine | 自动化任务执行 |
| MacroRecorder | 宏录制与回放 |
| SmartScheduler | 智能调度 |

### 插件系统

| 工具 | 能力 |
|------|------|
| PluginManager | 插件加载与管理 |
| PluginLoader | 插件热加载 |
| PluginValidator | 插件校验 |

---

## 配置调优

所有配置在 `config/default.yaml`，常用调整：

### 调整决策阈值

```yaml
agent:
  ask_human_threshold: 0.6  # 默认 0.6，越高越保守
```

- `0.3` — 更自主，少确认
- `0.6` — 平衡（默认）
- `0.9` — 很保守，几乎事事确认

### 调整执行参数

```yaml
agent:
  max_task_duration: 3600    # 单任务最大时间（秒）
  max_step_retries: 3        # 单步骤最大重试次数

platform:
  action_delay: 0.5          # 操作间延迟（秒），防止太快
```

### 切换 LLM

```yaml
llm:
  default_provider: "ollama"  # 改为 zhipuai / openai
```

### 启用/禁用工具

```yaml
tools:
  browser_control:
    enabled: true
  email_ops:
    enabled: false            # 不需要邮件功能就关掉
```

---

## 后台常驻服务

JavasAgent 可以作为后台服务运行，通过全局热键和托盘图标随时调用，无需每次打开终端。

### 启动与停止

```bash
# 前台启动（终端显示日志，Ctrl+C 停止）
javas service start

# 后台静默启动
javas service start --background

# 查询服务状态
javas service status

# 停止后台服务
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

服务运行期间，以下热键在**任何应用**中都有效：

| 热键 | 功能 | 说明 |
|------|------|------|
| `Ctrl+Alt+J` | 打开对话窗口 | 弹出悬浮对话窗口，直接与 Agent 交互 |
| `Ctrl+Alt+V` | 语音开关 | 切换语音监听的开/关状态 |
| `Ctrl+Alt+S` | 停止当前任务 | 中断 Agent 正在执行的任务 |

> ⚠️ 热键需要管理员权限。非管理员运行时，热键功能静默降级，不报错但不生效。

### 系统托盘

服务启动后，系统托盘（任务栏右下角）会出现 JavasAgent 图标。

**图标颜色含义：**

| 颜色 | 状态 | 说明 |
|------|------|------|
| 🟢 绿色 | 活跃 | 正常运行，空闲等待 |
| 🟡 黄色 | 处理中 | 正在执行任务 |
| 🔴 红色 | 出错 | 服务异常，检查日志 |
| ⚪ 灰色 | 已暂停 | 服务暂停 |

**右键菜单：**

| 菜单项 | 功能 |
|--------|------|
| 打开对话 | 打开悬浮对话窗口（等同于 `Ctrl+Alt+J`） |
| 语音开关 | 启用/禁用语音监听 |
| 设置 | 打开配置面板 |
| 退出 | 停止服务并退出 |

### 后台服务配置

在 `config/default.yaml` 中添加 `daemon` 节可自定义后台服务：

```yaml
daemon:
  enabled: true               # 是否启用后台服务
  pipe_name: "javasagent_pipe" # Named Pipe 名称
  autostart: false             # 是否开机自启（推荐用 javas service install）
  tray_enabled: true           # 是否显示托盘图标
  hotkeys:
    chat: "ctrl+alt+j"         # 打开对话窗口热键
    voice_toggle: "ctrl+alt+v" # 语音开关热键
    stop_task: "ctrl+alt+s"    # 停止任务热键
  window_width: 600            # 对话窗口宽度
  window_height: 400           # 对话窗口高度
  window_always_on_top: true   # 对话窗口置顶
```

### IPC 通信

后台服务通过 **Named Pipe**（Windows 命名管道）与客户端通信。客户端命令（如 `javas service status`、`javas service stop`）通过 IPC 协议连接到后台服务。

Named Pipe 名称默认 `javasagent_pipe`，同一台机器上只允许一个实例运行。
