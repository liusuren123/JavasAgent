"""列出当前桌面所有可见窗口。"""
import sys
import ctypes
from ctypes import wintypes

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

user32 = ctypes.windll.user32

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

windows = []

def enum_cb(hwnd, lparam):
    if user32.IsWindowVisible(hwnd):
        buff = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buff, 512)
        title = buff.value.strip()
        if title:
            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            windows.append({
                "title": title,
                "hwnd": hwnd,
                "width": w,
                "height": h,
                "minimized": w <= 8 or h <= 8,
            })
    return True

user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

active = [w for w in windows if not w["minimized"]]
minimized = [w for w in windows if w["minimized"]]

print(f"共发现 {len(windows)} 个窗口（{len(active)} 个活动, {len(minimized)} 个最小化）")
print("=" * 70)
print("\n【活动窗口】")
print("-" * 70)
for w in active:
    print(f"  标题: {w['title']}")
    print(f"  大小: {w['width']}x{w['height']}  句柄: {w['hwnd']}")
    print()

if minimized:
    print("\n【最小化窗口】")
    print("-" * 70)
    for w in minimized:
        print(f"  标题: {w['title']}")
        print()
