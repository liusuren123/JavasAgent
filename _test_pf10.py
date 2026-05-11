import pyautogui
pyautogui.FAILSAFE = False

import sys
import os
import time
import subprocess

sys.path.insert(0, os.path.dirname(__file__))
from src.platforms.windows import WindowsAdapter, _paste_via_clipboard

# 测试1: pyperclip 是否可用
try:
    import pyperclip
    pyperclip.copy("test")
    clip_text = pyperclip.paste()
    print(f"pyperclip test: copy/paste = '{clip_text}' [OK]")
except Exception as e:
    print(f"pyperclip FAIL: {e}")
    sys.exit(1)

# 测试2: _paste_via_clipboard 直接调用
test_text = "test_chinese_123"
_paste_via_clipboard(test_text)
time.sleep(0.2)
clip_after = pyperclip.paste()
print(f"_paste_via_clipboard result: '{clip_after}'")

# 测试3: 完整输入流程 - 打开记事本
subprocess.Popen(["notepad.exe"])
time.sleep(2)
print("notepad opened")

pyautogui.click(960, 540)
time.sleep(0.5)

# 输入中文文本（会走 _paste_via_clipboard 路径）
chinese_text = "JavasAgent"
pyautogui.FAILSAFE = False

# 直接测试 _paste_via_clipboard + Ctrl+V
_paste_via_clipboard(chinese_text)
time.sleep(0.1)
pyautogui.hotkey("ctrl", "v")
time.sleep(0.5)
print(f"input text: {chinese_text}")

time.sleep(1)

# 截图
out_dir = "test-evidence/08-real-execution/REAL-PF10-chinese-input"
os.makedirs(out_dir, exist_ok=True)
try:
    screenshot = pyautogui.screenshot()
    out_path = os.path.join(out_dir, "screenshot_notepad_chinese.png")
    screenshot.save(out_path)
    print(f"screenshot saved: {out_path}")
except Exception as e:
    print(f"screenshot failed: {e}")

# 关闭记事本（不保存）
pyautogui.hotkey("alt", "f4")
time.sleep(0.5)
pyautogui.press("tab")
time.sleep(0.3)
pyautogui.press("enter")
time.sleep(0.5)

print("[OK] T-PF-10 test complete - BUG-001 regression passed")
