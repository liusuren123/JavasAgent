"""关闭 Zed Agent 的 Edits 面板，然后输入新任务。"""
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

# 1. 先关闭 Edits 面板 - 点击 Reject All 按钮（Edits 栏右侧）
# Edits 栏在面板底部，Reject All 大概在 x=700~900, y=1780~1810 的区域
print("尝试关闭 Edits 面板...")
# 先点面板底部的 Reject All 区域
pyautogui.click(800, 1800)
time.sleep(0.5)

# 多按 Escape 确保关闭
for i in range(5):
    pyautogui.press("escape")
    time.sleep(0.3)

print("已尝试关闭 Edits")

# 2. 截图确认面板状态
from PIL import ImageGrab
img = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img.save("scripts/after_reject.png")
print("Reject 后截图已保存")

# 3. 复制到剪贴板
ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n" + task + "\n'@)"
result = subprocess.run(
    ["powershell", "-Command", ps_cmd],
    capture_output=True, text=True, timeout=10
)
print(f"剪贴板: {'OK' if result.returncode == 0 else 'FAIL'}")

# 4. 点击输入框
input_x, input_y = 485, 925
print(f"点击输入框 ({input_x}, {input_y})...")
pyautogui.click(input_x, input_y)
time.sleep(1.0)

# 5. 全选+删除
pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

# 6. 粘贴
print("粘贴文本...")
pyautogui.hotkey("ctrl", "v")
time.sleep(1.5)

# 7. 截图确认
img2 = ImageGrab.grab(bbox=(0, 1700, 960, 1970))
img2.save("scripts/input_confirm_v4.png")

# 8. 发送
print("按 Enter 发送...")
pyautogui.press("enter")
time.sleep(3)

# 9. 最终截图
img3 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img3.save("scripts/agent_final.png")
print("完成！")
