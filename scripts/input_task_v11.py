"""在正确的 y 范围内定位输入框。"""
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

# 先精确扫描 y=2040~2080 区域
img = ImageGrab.grab(bbox=(0, 2040, 900, 2080))
for screen_y in range(2040, 2080):
    local_y = screen_y - 2040
    # 取 x=100 和 x=400 的像素
    p100 = img.getpixel((100, local_y))
    p400 = img.getpixel((400, local_y))
    # 只打印颜色变化明显的行
    if abs(p400[0] - 32) > 30 or abs(p100[0] - 32) > 30:
        print(f"y={screen_y}: x100={p100} x400={p400}")

# 根据之前的分析：
# y=2060: R=175 (亮色) - 可能是输入框边框
# y=2050: R=40 (暗色) - 普通背景
# y=2090: R=59 (蓝色) - Edits 栏
# y=2101: R=69 (蓝色) - 输入框内容区
# 输入框应该在 y=2055~2068 之间

# 复制到剪贴板
ps_cmd = "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Clipboard]::SetText(@'\n" + task + "\n'@)"
subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=10)
print("剪贴板 OK")

# 尝试 y=2062（输入框中心，亮色边框内）
input_x, input_y = 400, 2062
print(f"点击输入框 ({input_x}, {input_y})...")
pyautogui.click(input_x, input_y)
time.sleep(1.0)

pyautogui.hotkey("ctrl", "a")
time.sleep(0.2)
pyautogui.press("delete")
time.sleep(0.3)

print("粘贴...")
pyautogui.hotkey("ctrl", "v")
time.sleep(2.0)

# 截图确认
img2 = ImageGrab.grab(bbox=(50, 2045, 850, 2075))
img2.save("scripts/input_v11_check.png")

print("Enter 发送...")
pyautogui.press("enter")
time.sleep(5)

img3 = ImageGrab.grab(bbox=(0, 0, 960, 2160))
img3.save("scripts/agent_v11_final.png")
print("完成！")
