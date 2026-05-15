"""精确操作：输入框在 y=2101~2111 区域。"""
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

# 1. 复制到剪贴板
ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n" + task + "\n'@)"
subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
print("剪贴板 OK")

# 2. 点击输入框（x=400 面板中间，y=2106 输入框中间）
input_x, input_y = 400, 2106
print(f"点击输入框 ({input_x}, {input_y})...")
pyautogui.click(input_x, input_y)
time.sleep(1.0)

# 3. 清空
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# 4. 粘贴
print("粘贴...")
pyautogui.hotkey("ctrl", "v")
time.sleep(2.0)

# 5. 截图确认
img = ImageGrab.grab(bbox=(50, 2095, 900, 2120))
img.save("scripts/input_v10_check.png")

# 6. 发送
print("Enter 发送...")
pyautogui.press("enter")
time.sleep(5)

# 7. 最终截图
img2 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img2.save("scripts/agent_v10_final.png")
print("完成！")
