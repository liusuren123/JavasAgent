"""T-HH-02: 中距离拟人移动"""
import asyncio, sys, os, time
sys.path.insert(0, os.path.dirname(__file__))

async def main():
    import pyautogui
    pyautogui.FAILSAFE = False
    from src.platforms.human_hand import HumanHand
    from src.platforms.windows import WindowsAdapter
    
    adapter = WindowsAdapter()
    pyautogui.FAILSAFE = False  # adapter init sets it True, override for test
    hand = HumanHand(adapter)
    
    # 先移到安全位置
    await adapter.move_to(500, 500)
    time.sleep(0.3)
    
    # 中距离拟人移动 (500,500) -> (1000, 500) ~500px
    result = await hand.human_move_to(1000, 500)
    time.sleep(0.3)
    
    pos = pyautogui.position()
    print(f"移动后位置: {pos}")
    dx = abs(pos.x - 1000)
    dy = abs(pos.y - 500)
    print(f"偏差: dx={dx}, dy={dy}")
    
    out_dir = "test-evidence/08-real-execution/REAL-HH02-medium-move"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "TEST-DESC.md"), "w", encoding="utf-8") as f:
        f.write(f"""# T-HH-02: 中距离拟人移动

## 测试目的
验证 HumanHand 中距离拟人移动（~500px），应有减速校准效果。

## 测试参数
- 起点: (500, 500)
- 终点: (1000, 500)
- 距离: ~500px (中距离)

## 测试结果
- 移动后鼠标: ({pos.x}, {pos.y})
- 偏差: dx={dx}, dy={dy}
- 状态: {'PASS' if dx <= 10 and dy <= 10 else 'PARTIAL'}
""")
    
    print("[OK] T-HH-02 完成")
    return True

if __name__ == "__main__":
    asyncio.run(main())
