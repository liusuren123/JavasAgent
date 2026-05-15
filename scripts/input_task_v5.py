"""先点 Reject All 关闭 Edits，再精确输入新任务。"""
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyautogui

task = """请分析 Zed Agent 中内置 LLM provider 与自定义 provider 在思考过程与工具调用方面的区别：

1. 内置 provider（如 Anthropic、OpenAI）和自定义 provider 在处理 tool_use/tool_call 时，代码路径有什么不同？
2. 为什么同一个模型（比如通过 OpenAI 兼容接口接入），作为内置 provider 和自定义 provider 时，工具调用的表现会不一致？
3. 思考过程（thinking/reasoning）在内置和自定义 provider 之间的处理差异是什么？
4. 请找出相关的源码文件和函数，说明这些差异的具体实现位置。

请给出详细的技术分析，包括具体的代码引用。"""

from PIL import ImageGrab

# 1. 点击 Reject All 按钮（局部坐标 x=938, y=905 → 全屏就是这个坐标）
print("点击 Reject All...")
pyautogui.click(938, 905)
time.sleep(1.0)

# 确认 Edits 是否关闭
img = ImageGrab.grab(bbox=(0, 880, 960, 950))
img.save("scripts/after_reject_v5.png")

# 2. Escape 多次确保关闭
for _ in range(3):
    pyautogui.press("escape")
    time.sleep(0.3)

# 3. 复制到剪贴板
ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n" + task + "\n'@)"
subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
print("剪贴板 OK")

# 4. 精确点击输入框（y=925 附近，x=485 面板中间）
print("点击输入框...")
pyautogui.click(485, 930)
time.sleep(1.0)

# 5. 清空
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# 6. 粘贴
print("粘贴...")
pyautogui.hotkey("ctrl", "v")
time.sleep(2.0)

# 7. 截图确认
img2 = ImageGrab.grab(bbox=(0, 900, 960, 960))
img2.save("scripts/input_box_check.png")

# 8. 发送
print("Enter 发送...")
pyautogui.press("enter")
time.sleep(3)

# 9. 最终确认
img3 = ImageGrab.grab(bbox=(0, 0, 960, 400))
img3.save("scripts/agent_new_task_top.png")
img4 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img4.save("scripts/agent_final_v5.png")
print("完成！")
