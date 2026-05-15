"""在 Zed Agent 输入框中输入任务并发送。"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyautogui

# 输入框中心坐标（根据截屏分析）
input_x, input_y = 145, 925

# 1. 点击输入框激活
print(f"点击输入框 ({input_x}, {input_y})...")
pyautogui.click(input_x, input_y)
time.sleep(0.8)

# 2. 清空输入框（以防有内容）
pyautogui.hotkey("ctrl", "a")
time.sleep(0.3)

# 3. 输入任务内容
task = """请分析 Zed Agent 中内置 LLM provider 与自定义 provider 在思考过程与工具调用方面的区别：

1. 内置 provider（如 Anthropic、OpenAI）和自定义 provider 在处理 tool_use/tool_call 时，代码路径有什么不同？
2. 为什么同一个模型（比如通过 OpenAI 兼容接口接入），作为内置 provider 和自定义 provider 时，工具调用的表现会不一致？
3. 思考过程（thinking/reasoning）在内置和自定义 provider 之间的处理差异是什么？
4. 请找出相关的源码文件和函数，说明这些差异的具体实现位置。

请给出详细的技术分析，包括具体的代码引用。"""

print(f"输入任务文本（{len(task)} 字符）...")
pyautogui.write(task, interval=0.01)
time.sleep(0.5)

# 4. 发送（Enter）
print("按 Enter 发送...")
pyautogui.press("enter")

print("任务已发送！")

# 5. 等待一下再截图确认
time.sleep(3)

from PIL import ImageGrab
img = ImageGrab.grab()
img.save("scripts/after_input.png")
print(f"确认截图已保存: {img.size}")
