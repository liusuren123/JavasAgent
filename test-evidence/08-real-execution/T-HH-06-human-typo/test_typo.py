"""T-HH-06: 拟人打字（有错字）实操测试。

测试 HumanHand.human_type() 的打错再改特性：
1. 使用高 typo_probability 确保 typo 触发
2. 英文测试（逐字符输入，typo 机制可正常工作）
3. 中文测试（剪贴板粘贴）
4. 截图记录结果
"""

import asyncio
import os
import subprocess
import sys
import time

# 添加项目根目录到 sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

import pyautogui

from src.platforms.human_hand import HumanHand, HumanHandConfig
from src.platforms.windows import WindowsAdapter

EVIDENCE_DIR = os.path.dirname(os.path.abspath(__file__))


def close_notepad():
    """关闭所有记事本进程。"""
    subprocess.run("taskkill /F /IM notepad.exe", shell=True, capture_output=True)
    time.sleep(0.5)


def open_notepad():
    """打开记事本并等待窗口出现。"""
    subprocess.Popen("notepad.exe", shell=True)
    time.sleep(2.0)
    # 激活记事本窗口
    try:
        import win32gui
        import win32con

        def _find_notepad(hwnd, result):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if "记事本" in title or "Notepad" in title:
                    result.append(hwnd)

        handles = []
        win32gui.EnumWindows(_find_notepad, handles)
        if handles:
            hwnd = handles[0]
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)
            try:
                win32gui.BringWindowToTop(hwnd)
            except Exception:
                pass
            time.sleep(0.5)
            print(f"[OK] 记事本窗口已激活: hwnd={hwnd}")
            return True
        else:
            print("[WARN] 未找到记事本窗口")
            return False
    except ImportError:
        print("[WARN] pywin32 未安装")
        return False


def take_screenshot(name):
    """截图并保存。"""
    pyautogui.FAILSAFE = False
    path = os.path.join(EVIDENCE_DIR, name)
    try:
        img = pyautogui.screenshot()
        img.save(path)
        print(f"[OK] 截图已保存: {path}")
        return path
    except OSError as e:
        print(f"[WARN] 截图失败（可能运行在无头环境）: {e}")
        return None


def make_adapter(action_delay=0.01):
    """创建 WindowsAdapter 并禁用 fail-safe。"""
    adapter = WindowsAdapter(action_delay=action_delay)
    # WindowsAdapter.__init__ 会设置 pyautogui.FAILSAFE = True
    # 在无头/远程环境中需要禁用
    pyautogui.FAILSAFE = False
    pyautogui.PAUSE = 0.01
    return adapter


async def test_typo_english():
    """测试英文拟人打字（高 typo 概率）。"""
    print("\n" + "=" * 60)
    print("测试 1: 英文拟人打字（typo_probability=0.3）")
    print("=" * 60)

    adapter = make_adapter()
    config = HumanHandConfig(
        typo_probability=0.3,
        base_type_interval=0.06,
    )
    hand = HumanHand(adapter, config=config)

    test_text = "Hello World from JavasAgent"
    print(f"  输入文本: '{test_text}'")
    print(f"  typo 概率: {config.typo_probability}")
    print("  开始输入...")

    await hand.human_type(test_text, base_interval=0.06)

    time.sleep(0.5)
    take_screenshot("01_english_typo.png")
    print("[OK] 英文打字测试完成")


async def test_typo_chinese():
    """测试中文拟人打字。

    注意：中文使用剪贴板粘贴，typo 机制表现为：
    - typo 触发时先打一个随机 ASCII 字母
    - backspace 删除
    - 然后粘贴完整中文字符
    """
    print("\n" + "=" * 60)
    print("测试 2: 中文拟人打字（typo_probability=0.3）")
    print("=" * 60)

    adapter = make_adapter()
    config = HumanHandConfig(
        typo_probability=0.3,
        base_type_interval=0.06,
    )
    hand = HumanHand(adapter, config=config)

    # 按 Enter 换行
    await adapter.press_key("enter")
    await asyncio.sleep(0.3)

    test_text = "你好世界，这是JavasAgent拟人打字测试"
    print(f"  输入文本: '{test_text}'")
    print(f"  typo 概率: {config.typo_probability}")
    print("  开始输入...")

    await hand.human_type(test_text, base_interval=0.06)

    time.sleep(0.5)
    take_screenshot("02_chinese_typo.png")
    print("[OK] 中文打字测试完成")


async def test_typo_100percent():
    """详细测试 typo 机制（100% typo）。"""
    print("\n" + "=" * 60)
    print("测试 3: typo 机制详细验证（typo_probability=1.0，每个字符都打错再改）")
    print("=" * 60)

    adapter = make_adapter()
    config = HumanHandConfig(
        typo_probability=1.0,
        base_type_interval=0.05,
    )
    hand = HumanHand(adapter, config=config)

    # 按 Enter 换行
    await adapter.press_key("enter")
    await asyncio.sleep(0.3)

    test_text = "TEST"
    print(f"  输入文本: '{test_text}'")
    print(f"  typo 概率: {config.typo_probability}（100%）")
    print("  每个字符都会: 打错字符 -> backspace -> 正确字符")
    print("  开始输入...")

    await hand.human_type(test_text, base_interval=0.05)

    time.sleep(0.5)
    take_screenshot("03_typo_100percent.png")
    print("[OK] typo 机制详细测试完成")


async def main():
    print("=" * 60)
    print("T-HH-06: 拟人打字（有错字）实操测试")
    print("=" * 60)

    # 关闭残留记事本
    close_notepad()

    # 打开记事本
    if not open_notepad():
        print("[ERROR] 无法打开记事本，终止测试")
        return

    try:
        # 测试 1: 英文（typo 机制可正常工作）
        await test_typo_english()

        # 测试 2: 中文
        await test_typo_chinese()

        # 测试 3: 100% typo
        await test_typo_100percent()

        # 最终截图
        take_screenshot("04_final_result.png")

    finally:
        # 关闭记事本
        close_notepad()

    print("\n" + "=" * 60)
    print("所有测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
