# JavasAgent 后台常驻服务 — 开发计划

> 版本: 1.0 | 日期: 2026-05-12
> 基于技术交底书: docs/TR-background-service.md
> 总任务数: 28 个原子任务 | 预计 8 个 Step（cron 轮次）

---

## Step 1: 基础骨架 — service.py + daemon 包

### Task 1.1: 创建 daemon 包结构
- 新建 `src/daemon/__init__.py`
- 内容：导出 JavasService 类
- 文件大小：< 1KB

### Task 1.2: 实现 JavasService 基础类
- 新建 `src/daemon/service.py`
- 实现 `JavasService.__init__()` — 初始化所有子系统引用为 None
- 实现 `JavasService.start()` 骨架 — 按顺序调用各子系统 start，异常处理，日志
- 实现 `JavasService.stop()` — 按逆序停止各子系统
- 实现 `JavasService.status()` — 返回各子系统运行状态 dict
- 不依赖任何未实现的子系统，每个子系统 start/stop 用 try/except 包裹
- 预留：self._agent, self._voice_pipeline, self._ipc_server, self._tray, self._hotkey, self._chat_window
- 文件大小：< 8KB

### Task 1.3: 编写 JavasService 单元测试
- 新建 `tests/daemon/__init__.py`
- 新建 `tests/daemon/test_service.py`
- 测试 `__init__` 所有属性为 None
- 测试 `start()` 在无子系统时不崩溃
- 测试 `stop()` 可重复调用
- 测试 `status()` 返回正确结构
- 所有测试用 mock，不依赖真实 Agent

---

## Step 2: IPC 通信 — Named Pipe 服务端 + 客户端

### Task 2.1: 实现 IPC 消息协议
- 新建 `src/daemon/ipc_protocol.py`
- 定义 `IPCMessage` dataclass：method, params, id, result, error
- 定义 `IPCRequest` — 请求消息构造
- 定义 `IPCResponse` — 响应消息构造
- 定义 `IPCError` — 错误响应构造
- 定义方法常量：`METHOD_CHAT`, `METHOD_STATUS`, `METHOD_STOP`, `METHOD_VOICE_TOGGLE`
- 序列化/反序列化：`encode_message()` / `decode_message()` — JSON 格式，4 字节长度前缀
- 文件大小：< 5KB

### Task 2.2: 实现 IPC 服务端
- 新建 `src/daemon/ipc_server.py`
- 实现 `IPCServer.__init__(pipe_name="javasagent_pipe")`
- 实现 `IPCServer.start()` — 创建 Named Pipe，开始监听循环
- 实现 `IPCServer.stop()` — 关闭 pipe，通知所有连接断开
- 实现 `_handle_connection()` — 读取请求，路由到 handler，返回响应
- 实现 `_route_request()` — 根据 method 调用对应 handler
- handler 注册机制：`register_handler(method, callback)`
- 使用 `win32pipe` + `win32file`（pywin32）
- 文件大小：< 10KB

### Task 2.3: 实现 IPC 客户端
- 新建 `src/daemon/ipc_client.py`
- 实现 `IPCClient.__init__(pipe_name="javasagent_pipe", timeout=5.0)`
- 实现 `IPCClient.connect()` — 连接 Named Pipe，超时抛异常
- 实现 `IPCClient.send_request(method, params)` — 发送请求，等待响应
- 实现 `IPCClient.close()` — 断开连接
- 实现 `IPCClient.is_connected` 属性
- 实现 `check_service_running()` 类方法 — 尝试连接判断服务是否在运行
- 文件大小：< 6KB

### Task 2.4: 编写 IPC 测试
- 新建 `tests/daemon/test_ipc_protocol.py`
  - 测试 IPCRequest/Response 构造
  - 测试 encode/decode 往返一致
  - 测试错误消息构造
  - 测试长度前缀正确
- 新建 `tests/daemon/test_ipc_server_client.py`
  - 测试服务端启动/停止
  - 测试客户端连接/断开
  - 测试请求-响应往返（mock handler）
  - 测试超时断开
  - 测试多客户端并发连接
- 使用 mock pipe（monkeypatch win32pipe/win32file）

---

## Step 3: 系统托盘 — TrayIcon

### Task 3.1: 实现 TrayIcon
- 新建 `src/daemon/tray_icon.py`
- 实现 `TrayIcon.__init__(on_quit, on_chat, on_voice_toggle, on_settings)`
- 使用 `pystray` 库
- 实现 `_create_icon()` — 创建绿色/黄色/红色/灰色图标（用 Pillow 动态生成纯色圆形 PNG）
- 实现 `_create_menu()` — 右键菜单：打开对话、语音开关、设置、退出
- 实现 `start()` — 在独立线程中运行 `icon.run()`
- 实现 `stop()` — `icon.stop()`
- 实现 `update_status(status)` — 根据状态切换图标颜色
- 实现 `set_tooltip(text)` — 设置鼠标悬停提示
- 文件大小：< 8KB

### Task 3.2: 编写 TrayIcon 测试
- 新建 `tests/daemon/test_tray_icon.py`
- 测试 `__init__` 回调存储
- 测试 `_create_menu()` 菜单项数量和文本
- 测试 `update_status()` 切换不同状态
- 测试 `start()` 和 `stop()` 线程行为
- 使用 mock pystray（monkeypatch）

### Task 3.3: 安装 pystray 依赖
- 执行 `pip install pystray`
- 更新 `pyproject.toml` dependencies 添加 `pystray>=0.19`

---

## Step 4: 全局热键 — HotkeyManager

### Task 4.1: 实现 HotkeyManager
- 新建 `src/daemon/hotkey_manager.py`
- 实现 `HotkeyManager.__init__()`
- 实现 `register(key_combo, callback)` — 注册快捷键和回调
- 实现 `unregister(key_combo)` — 取消注册
- 实现 `start()` — 调用 `keyboard.hook()` 开始监听
- 实现 `stop()` — 调用 `keyboard.unhook_all()`
- 内置默认热键：
  - `Ctrl+Alt+J` → 打开对话窗口
  - `Ctrl+Alt+V` → 切换语音模式
  - `Ctrl+Alt+S` → 停止当前任务
- 实现 `_parse_combo()` — 解析 "Ctrl+Alt+J" 为 keyboard 库格式
- 优雅降级：keyboard 不可用时（无管理员权限）打印警告，所有热键跳过
- 文件大小：< 6KB

### Task 4.2: 编写 HotkeyManager 测试
- 新建 `tests/daemon/test_hotkey_manager.py`
- 测试 `register()` 存储回调
- 测试 `unregister()` 移除回调
- 测试 `_parse_combo()` 解析各种格式
- 测试 keyboard 不可用时优雅降级（mock import 失败）
- 测试 `start()` 和 `stop()` 行为
- 使用 mock keyboard

### Task 4.3: 安装 keyboard 依赖
- 执行 `pip install keyboard`
- 更新 `pyproject.toml` dependencies 添加 `keyboard>=0.13`

---

## Step 5: 对话窗口 — ChatWindow

### Task 5.1: 实现 ChatWindow
- 新建 `src/daemon/chat_window.py`
- 使用 `tkinter`（Python 内置）
- 实现 `ChatWindow.__init__(on_send_message)`
- 实现 `_build_ui()` — 创建主窗口、标题、消息区域（Text widget）、输入框、发送按钮
- 实现 `show()` — `root.mainloop()` 在独立线程
- 实现 `hide()` — `root.withdraw()`
- 实现 `add_message(role, text)` — 追加消息到显示区（🤖 / 👤 前缀）
- 实现 `set_status(text)` — 更新底部状态栏
- 实现 `clear_input()` — 清空输入框
- 窗口属性：标题 "JavasAgent"，大小 600x400，置顶显示（`attributes('-topmost', True)`）
- 线程安全：所有 UI 操作通过 `root.after()` 调度到主线程
- 关闭窗口 = 隐藏（不是退出服务）
- 文件大小：< 10KB

### Task 5.2: 编写 ChatWindow 测试
- 新建 `tests/daemon/test_chat_window.py`
- 测试 `__init__` 回调存储
- 测试 `_build_ui()` 组件存在性
- 测试 `add_message()` 文本追加
- 测试 `set_status()` 状态更新
- 测试 `show()` 和 `hide()` 行为
- 测试关闭窗口 = 隐藏不退出
- 注意：tkinter 测试需要 mock 或 headless 模式

---

## Step 6: 开机自启 — AutoStart

### Task 6.1: 实现 AutoStart
- 新建 `src/daemon/autostart.py`
- 实现 `AutoStart.enable()` — 写入注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
  - 键名：`JavasAgent`
  - 键值：`pythonw.exe "脚本路径" service --background`
- 实现 `AutoStart.disable()` — 删除注册表项
- 实现 `AutoStart.is_enabled()` — 检查注册表项是否存在
- 使用 `winreg`（Python 内置，无需额外依赖）
- 获取当前脚本路径：`sys.executable` + `__file__`
- 文件大小：< 4KB

### Task 6.2: 编写 AutoStart 测试
- 新建 `tests/daemon/test_autostart.py`
- 测试 `enable()` 写入注册表（mock winreg）
- 测试 `disable()` 删除注册表项
- 测试 `is_enabled()` 返回正确状态
- 测试注册表路径和键名正确

---

## Step 7: 集成 — service.py 串联所有组件 + CLI 命令

### Task 7.1: 完善 JavasService.start()
- 修改 `src/daemon/service.py`
- 在 `start()` 中按顺序初始化和启动：
  1. BaseAgent（现有 create_agent()）
  2. VoicePipeline（现有，可选）
  3. IPCServer（注册 chat/status/stop/voice_toggle handler）
  4. TrayIcon（传入 on_quit/on_chat/on_voice_toggle 回调）
  5. HotkeyManager（注册默认热键）
- 每个组件启动失败不阻塞其他组件
- 日志记录每个组件启动状态

### Task 7.2: 完善 JavasService.stop()
- 在 `stop()` 中按逆序停止：
  1. HotkeyManager
  2. TrayIcon
  3. IPCServer
  4. VoicePipeline
  5. BaseAgent
- 每个组件停止失败不阻塞其他组件
- 设置 `self._running = False`

### Task 7.3: 实现 IPC handler
- 在 `service.py` 中实现 handler 方法：
  - `_handle_chat(params)` → 调用 `self._agent.process(params["text"])` → 返回响应
  - `_handle_status(params)` → 返回 `self.status()`
  - `_handle_stop(params)` → 调用 `self.stop()` → 返回确认
  - `_handle_voice_toggle(params)` → 切换语音管道开/关 → 返回状态

### Task 7.4: 修改 main.py 添加 service 子命令
- 修改 `src/main.py`
- 新增 `javas service start` — 启动后台服务（阻塞运行）
- 新增 `javas service stop` — 通过 IPC 发送 stop 命令
- 新增 `javas service status` — 通过 IPC 查询状态
- 新增 `javas service install` — 启用开机自启
- 新增 `javas service uninstall` — 禁用开机自启
- 修改 `javas chat` — 如果后台服务在运行，通过 IPC 转发；否则本地启动
- 修改 `javas status` — 如果后台服务在运行，查询后台状态；否则本地状态

### Task 7.5: 更新配置文件
- 修改 `config/default.yaml`
- 新增 `daemon` 配置节：
  ```yaml
  daemon:
    enabled: true
    pipe_name: "javasagent_pipe"
    autostart: false
    hotkeys:
      chat: "ctrl+alt+j"
      voice_toggle: "ctrl+alt+v"
      stop_task: "ctrl+alt+s"
    tray:
      enabled: true
      tooltip: "JavasAgent"
    window:
      width: 600
      height: 400
      always_on_top: true
  ```

### Task 7.6: 编写集成测试
- 新建 `tests/daemon/test_integration.py`
- 测试 JavasService 完整 start→stop 流程（mock 所有子系统）
- 测试 IPC chat handler 正确调用 Agent
- 测试 IPC status handler 返回正确结构
- 测试 IPC stop handler 触发服务停止
- 测试 service 子命令 CLI 参数解析

---

## Step 8: 收尾 — 文档更新 + 全量测试

### Task 8.1: 更新 README.md
- 添加后台服务相关内容：
  - `javas service start` 启动后台
  - `javas service install` 开机自启
  - 热键说明
  - 托盘图标说明

### Task 8.2: 更新 getting-started.md
- 添加后台服务安装步骤
- 添加管理员权限说明
- 添加首次启动麦克风权限引导

### Task 8.3: 更新 user-guide.md
- 添加后台服务使用章节
- 添加热键列表
- 添加托盘菜单说明

### Task 8.4: 更新 troubleshooting.md
- 添加后台服务相关常见问题：
  - 热键不生效（管理员权限）
  - 托盘图标不显示
  - IPC 连接失败
  - 麦克风权限

### Task 8.5: 跑全量测试确认
- 执行 `python -m pytest tests/ -q`
- 确认 0 失败
- 确认新增测试全部通过

### Task 8.6: 最终 commit + push
- `git add -A && git commit -m "feat(daemon): 后台常驻服务完整实现" && git push origin main`

---

## 文件清单总览

### 新建文件（14 个）

```
src/daemon/__init__.py              # daemon 包
src/daemon/service.py               # 后台服务主类
src/daemon/ipc_protocol.py          # IPC 消息协议
src/daemon/ipc_server.py            # IPC 服务端
src/daemon/ipc_client.py            # IPC 客户端
src/daemon/tray_icon.py             # 系统托盘
src/daemon/hotkey_manager.py        # 全局热键
src/daemon/chat_window.py           # 对话窗口
src/daemon/autostart.py             # 开机自启
tests/daemon/__init__.py            # 测试包
tests/daemon/test_service.py        # 服务测试
tests/daemon/test_ipc_protocol.py   # 协议测试
tests/daemon/test_ipc_server_client.py  # IPC 测试
tests/daemon/test_tray_icon.py      # 托盘测试
tests/daemon/test_hotkey_manager.py # 热键测试
tests/daemon/test_chat_window.py    # 窗口测试
tests/daemon/test_autostart.py      # 自启测试
tests/daemon/test_integration.py    # 集成测试
```

### 修改文件（4 个）

```
src/main.py                         # 添加 service 子命令
config/default.yaml                 # 添加 daemon 配置节
pyproject.toml                      # 添加 pystray, keyboard 依赖
docs/*.md                           # 文档更新
```
