"""方案：先关闭 Edits diff 视图（点击 diff 切换按钮或 Escape），然后输入。"""
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

# 1. 先点击 Zed 编辑区确保焦点
pyautogui.click(1500, 500)
time.sleep(0.5)

# 2. Escape 关闭 diff/edits 视图
print("Escape 关闭 edits...")
for _ in range(10):
    pyautogui.press("escape")
    time.sleep(0.2)

time.sleep(0.5)

# 3. 截图看状态
img = ImageGrab.grab(bbox=(0, 880, 960, 960))
img.save("scripts/after_escape_bar.png")

# 4. 复制任务到剪贴板
ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n" + task + "\n'@)"
subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
print("剪贴板 OK")

# 5. 点击 Agent 面板输入框区域 - 尝试面板最底部
print("点击输入框（面板底部）...")
pyautogui.click(450, 940)
time.sleep(0.8)

# 6. 粘贴
print("粘贴...")
pyautogui.hotkey("ctrl", "v")
time.sleep(2.0)

# 7. 截图确认输入框内容
img2 = ImageGrab.grab(bbox=(0, 900, 960, 960))
img2.save("scripts/input_v7_check.png")

# 8. 发送
print("Enter 发送...")
pyautogui.press("enter")
time.sleep(3)

# 9. 最终截图
img3 = ImageGrab.grab(bbox=(0, 0, 960, 500))
img3.save("scripts/task_sent_v7.png")
img4 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img4.save("scripts/full_agent_v7.png")
print("完成！")
