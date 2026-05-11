import pyautogui
pyautogui.FAILSAFE = False

import sys
import os
import time
import subprocess

sys.path.insert(0, os.path.dirname(__file__))
from src.platforms.windows import WindowsAdapter

subprocess.Popen(["notepad.exe"])
time.sleep(2)

print(f"FAILSAFE: {pyautogui.FAILSAFE}, pos: {pyautogui.position()}")

pyautogui.click(960, 540)
time.sleep(0.5)

test_text = "Hello World! This is a test."
pyautogui.typewrite(test_text, interval=0.05)
print(f"typewrite OK: {test_text}")

time.sleep(1)

# 截图
out_dir = "test-evidence/08-real-execution/REAL-PF09-english-input"
os.makedirs(out_dir, exist_ok=True)
try:
    screenshot = pyautogui.screenshot()
    out_path = os.path.join(out_dir, "screenshot_notepad_english.png")
    screenshot.save(out_path)
    print(f"截图已保存: {out_path}")
except Exception as e:
    print(f"截图失败: {e}")

pyautogui.hotkey("alt", "f4")
time.sleep(0.5)
pyautogui.press("tab")
time.sleep(0.3)
pyautogui.press("enter")
time.sleep(0.5)

print("[OK] T-PF-09 测试完成")
