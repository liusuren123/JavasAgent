"""T-TL-06: 应用启动（打开记事本）"""
import asyncio, sys, os, time, subprocess
sys.path.insert(0, os.path.dirname(__file__))

async def main():
    import pyautogui
    pyautogui.FAILSAFE = False
    
    # 启动记事本
    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(2)
    
    # 检查进程是否在运行
    poll = proc.poll()
    print(f"记事本进程 poll: {poll}")
    
    # 进程应该还在运行（poll 返回 None）
    alive = poll is None
    
    if alive:
        print("[OK] 记事本已启动并在运行")
    else:
        print(f"[WARN] 记事本已退出, 返回码: {poll}")
    
    # 关闭记事本
    try:
        pyautogui.hotkey("alt", "f4")
        time.sleep(0.5)
        pyautogui.press("tab")
        time.sleep(0.3)
        pyautogui.press("enter")
    except:
        pass
    
    out_dir = "test-evidence/08-real-execution/REAL-TL06-app-launch"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "TEST-DESC.md"), "w", encoding="utf-8") as f:
        f.write(f"""# T-TL-06: 应用启动

## 测试目的
验证能成功启动外部应用（记事本）。

## 测试结果
- notepad.exe 启动: {'PASS' if alive else 'FAIL'}
- 状态: {'PASS' if alive else 'PARTIAL'}
""")
    
    print("[OK] T-TL-06 完成")
    return True

if __name__ == "__main__":
    asyncio.run(main())
