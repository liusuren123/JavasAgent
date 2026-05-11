"""T-HH-05: 拟人打字（有间隔）"""
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
    
    # 拟人打字 - 纯 ASCII 文本
    test_text = "Hello"
    
    start = time.time()
    await hand.human_type(test_text)
    elapsed = time.time() - start
    print(f"拟人打字 '{test_text}' 耗时: {elapsed:.2f}s")
    
    # 应该有延迟（不是瞬间完成）
    assert elapsed > 0.1, f"打字太快，可能没有间隔: {elapsed}s"
    
    out_dir = "test-evidence/08-real-execution/REAL-HH05-human-type"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "TEST-DESC.md"), "w", encoding="utf-8") as f:
        f.write(f"""# T-HH-05: 拟人打字（有间隔）

## 测试目的
验证 HumanHand.human_type() 逐字输入有延迟。

## 测试参数
- 文本: '{test_text}'
- 预期: 逐字输入，每字之间有间隔

## 测试结果
- 耗时: {elapsed:.2f}s
- 有间隔: {'是' if elapsed > 0.1 else '否'}
- 状态: PASS
""")
    
    print("[OK] T-HH-05 完成")
    return True

if __name__ == "__main__":
    asyncio.run(main())
