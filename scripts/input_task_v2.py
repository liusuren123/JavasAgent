"""通过剪贴板在 Zed Agent 输入框中粘贴任务并发送。"""
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyautogui

# 任务内容
task = """请分析 Zed Agent 中内置 LLM provider 与自定义 provider 在思考过程与工具调用方面的区别：

1. 内置 provider（如 Anthropic、OpenAI）和自定义 provider 在处理 tool_use/tool_call 时，代码路径有什么不同？
2. 为什么同一个模型（比如通过 OpenAI 兼容接口接入），作为内置 provider 和自定义 provider 时，工具调用的表现会不一致？
3. 思考过程（thinking/reasoning）在内置和自定义 provider 之间的处理差异是什么？
4. 请找出相关的源码文件和函数，说明这些差异的具体实现位置。

请给出详细的技术分析，包括具体的代码引用。"""

# 1. 将文本复制到剪贴板（用 PowerShell）
ps_cmd = f'''
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.Clipboard]::SetText(@'
{task}
'@)
'''
result = subprocess.run(
    ["powershell", "-Command", ps_cmd],
    capture_output=True, text=True, timeout=10
)
if result.returncode != 0:
    print(f"剪贴板设置失败: {result.stderr}")
    sys.exit(1)
print("已复制到剪贴板")

# 2. 点击输入框
input_x, input_y = 145, 925
print(f"点击输入框 ({input_x}, {input_y})...")
pyautogui.click(input_x, input_y)
time.sleep(0.8)

# 3. 全选+删除（清空）
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# 4. 粘贴
print("Ctrl+V 粘贴...")
pyautogui.hotkey("ctrl", "v")
time.sleep(1.0)

# 5. 截图确认输入内容
from PIL import ImageGrab
img = ImageGrab.grab(bbox=(0, 1750, 960, 1970))
img.save("scripts/input_confirm.png")
print("输入确认截图已保存")

# 6. 发送
print("按 Enter 发送...")
pyautogui.press("enter")

time.sleep(3)

# 7. 最终截图
img2 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img2.save("scripts/agent_sent.png")
print(f"发送后截图已保存: {img2.size}")
print("完成！")
