"""用键盘操作 Zed Agent：先新建对话避开 Edits，再输入任务。"""
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyautogui
from PIL import ImageGrab

task = """请分析 Zed Agent 中内置 LLM provider 与自定义 provider 在思考过程与工具调用方面的区别：

1. 内置 provider（如 Anthropic、OpenAI）和自定义 provider 在处理 tool_use/tool_call 时，代码路径有什么不同？
2. 为什么同一个模型（比如通过 OpenAI 兼容接口接入），作为内置 provider 和自定义 provider 时，工具调用的表现会不一致？
3. 思考过程（thinking/reasoning）在内置和自定义 provider 之间的处理差异是什么？
4. 请找出相关的源码文件和函数，说明这些差异的具体实现位置。

请给出详细的技术分析，包括具体的代码引用。"""

# 策略：用 Zed 命令面板新建一个 Agent 对话
# 1. 先确保焦点在 Zed 窗口
print("激活 Zed 窗口...")
pyautogui.click(500, 500)  # 点击 Zed 编辑区
time.sleep(0.5)

# 2. 打开 Zed 命令面板（Ctrl+Shift+P）
print("打开命令面板...")
pyautogui.hotkey("ctrl", "shift", "p")
time.sleep(1.0)

# 3. 输入 "agent: new thread" 搜索
print("搜索 agent new thread...")
# 用剪贴板避免输入问题
ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText('agent: new thread')"
subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
pyautogui.hotkey("ctrl", "v")
time.sleep(0.5)

img = ImageGrab.grab()
img.save("scripts/cmd_palette.png")

# 4. 按 Enter 执行
print("执行命令...")
pyautogui.press("enter")
time.sleep(1.5)

# 5. 现在应该有新的 Agent 对话了，输入框在底部
# 复制任务到剪贴板
ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n" + task + "\n'@)"
subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
print("剪贴板已设置")

# 6. 点击输入框（新对话的输入框应该在面板底部）
print("点击输入框...")
pyautogui.click(485, 930)
time.sleep(0.8)

# 7. 粘贴
print("粘贴任务...")
pyautogui.hotkey("ctrl", "v")
time.sleep(1.5)

img2 = ImageGrab.grab(bbox=(0, 1700, 960, 1970))
img2.save("scripts/new_thread_input.png")

# 8. 发送
print("发送...")
pyautogui.press("enter")
time.sleep(3)

img3 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img3.save("scripts/new_thread_result.png")
print("完成！")
