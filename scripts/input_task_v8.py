"""使用 Win32 API 精确操作：截图找 Reject All，点击，然后输入。"""
import sys
import time
import subprocess

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pyautogui
from PIL import ImageGrab, Image, ImageDraw

# 先截取面板底部区域
img = ImageGrab.grab(bbox=(0, 870, 960, 960))
img.save("scripts/edits_bar_raw.png")

# 放大图片以便 OCR 识别
img_large = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)

# 不管 OCR 结果，直接用视觉模型分析
print("尝试另一种方案：直接点击 Reject All 估计位置")

# 根据之前的分析，Reject All 在 Edits 栏右侧
# Edits 栏 y 范围约 890-915
# Reject All 大概在 x=850-940 范围
reject_x, reject_y = 900, 903
print(f"点击 Reject All 估计位置 ({reject_x}, {reject_y})...")
pyautogui.click(reject_x, reject_y)
time.sleep(1.0)

# 再试一次稍微偏左
pyautogui.click(870, 903)
time.sleep(1.0)

# 截图确认
img2 = ImageGrab.grab(bbox=(0, 870, 960, 960))
img2.save("scripts/after_reject_v8.png")

# Escape 再清理
for _ in range(5):
    pyautogui.press("escape")
    time.sleep(0.2)

# 截图
img3 = ImageGrab.grab(bbox=(0, 870, 960, 960))
img3.save("scripts/after_reject_escape_v8.png")

# 复制任务
task = """请分析 Zed Agent 中内置 LLM provider 与自定义 provider 在思考过程与工具调用方面的区别：

1. 内置 provider（如 Anthropic、OpenAI）和自定义 provider 在处理 tool_use/tool_call 时，代码路径有什么不同？
2. 为什么同一个模型（比如通过 OpenAI 兼容接口接入），作为内置 provider 和自定义 provider 时，工具调用的表现会不一致？
3. 思考过程（thinking/reasoning）在内置和自定义 provider 之间的处理差异是什么？
4. 请找出相关的源码文件和函数，说明这些差异的具体实现位置。

请给出详细的技术分析，包括具体的代码引用。"""

ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n" + task + "\n'@)"
subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)

# 点击输入框
pyautogui.click(450, 940)
time.sleep(0.8)
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)
pyautogui.hotkey("ctrl", "v")
time.sleep(1.5)

img4 = ImageGrab.grab(bbox=(0, 900, 960, 960))
img4.save("scripts/input_v8.png")

pyautogui.press("enter")
time.sleep(3)

img5 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img5.save("scripts/final_v8.png")
print("完成！")
